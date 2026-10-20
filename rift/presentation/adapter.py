"""Typed presentation adapter over immutable artifacts.

Contracts (schema_version 1): CaseView, ClaimView, ComparisonView,
TraceSelection, PatchReview, StudySummary, ArtifactLink. The adapter only
*reads* the artifact store and the case registry; it validates run identities,
reference epochs and digests, and recomputes the evaluator's arithmetic as an
additional consistency defence. It is never a second acceptance authority: a
disagreement is reported as a presentation-integrity error that blocks the
claim, never replaced by the adapter's own calculation.

Sealed held-out definitions (experiments/heldout/) are never served.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from rift.contracts.canonical import digest, read_json
from rift.contracts.config import load_config
from rift.evaluate.compare import classify
from rift.paths import EXPERIMENTS, ROOT, RUNS, STUDIES, rel
from rift.store import load_events, verify_run

REGISTRY = EXPERIMENTS / "cases" / "registry.json"
SPECIMENS = ROOT / "ui" / "specimens" / "illustrative_fixtures.json"
CURRENT_EPOCH_SOURCE = "reference_epoch recorded by every RTL run manifest"

METRIC = {"id": "inclusive_cycle_makespan_v1", "label": "Completion cycles (makespan)", "unit": "cycles", "direction": "lower_is_better",
          "definition": "last valid response cycle - first request-release cycle + 1, at a common abstract clock"}


class IntegrityError(RuntimeError):
    pass


def _manifest(run_id: str) -> dict:
    for base in (RUNS, STUDIES):
        p = base / run_id / "manifest.json"
        if p.exists():
            return read_json(p)
    raise FileNotFoundError(run_id)


def _dir(run_id: str) -> Path:
    for base in (RUNS, STUDIES):
        if (base / run_id).exists():
            return base / run_id
    raise FileNotFoundError(run_id)


def artifact_link(run_id: str, role: str, supports: list[str]) -> dict:
    m = _manifest(run_id)
    files = sorted(m.get("artifacts", {}).keys())
    return {"schema_version": 1, "artifact_id": run_id, "kind": m.get("kind"), "role": role,
            "observation_role": m.get("observation_role"), "evidence_basis": m.get("evidence_basis", "EXECUTED_ARTIFACT"),
            "status": m.get("status"), "manifest_digest": m.get("manifest_digest"), "path": rel(_dir(run_id)),
            "files": [{"name": f, "sha256": m["artifacts"][f]["sha256"], "bytes": m["artifacts"][f]["bytes"]} for f in files],
            "supports": supports}


def _current_epoch() -> str:
    from rift.rtl import reference_epoch, reference_identity
    from rift import toolchain
    cfg = load_config("lic8x8")
    d, _, _ = toolchain.build_dir_for(cfg)
    bm = read_json(d / "build_manifest.json")
    return reference_epoch(reference_identity(cfg, bm))


def comparison_view(cmp_run_id: str) -> dict:
    d = _dir(cmp_run_id)
    c = read_json(d / "comparison.json")
    order = c["admitted_order"]
    integrity = []
    # Re-verify every referenced run and recompute the verdict from the runs' own checks.
    model_checks, rtl_checks = {}, {}
    for dsg in order:
        for kind, ids, store in (("rtl", c.get("rtl_run_ids", {}), rtl_checks), ("model", c.get("model_run_ids", {}), model_checks)):
            rid = ids.get(dsg)
            if rid is None:
                continue
            v = verify_run(rid)
            if not v["ok"]:
                integrity.append(f"{kind} run {rid} failed digest verification: {v['problems']}")
            store[dsg] = read_json(RUNS / rid / "check.json")
    if rtl_checks and model_checks:
        re = classify(order, model_checks, rtl_checks)
        for k in ("verdict", "model_costs", "rtl_costs", "dM", "dR"):
            if re.get(k) != c.get(k):
                integrity.append(f"presentation recomputation of {k} ({re.get(k)}) disagrees with evaluator ({c.get(k)})")
    epochs = set()
    for dsg in order:
        rid = c.get("rtl_run_ids", {}).get(dsg)
        if rid:
            epochs.add(_manifest(rid).get("reference_epoch"))
    view = {
        "schema_version": 1,
        "comparison_run_id": cmp_run_id,
        "verdict": c["verdict"],
        "blocking_reason": c.get("blocking_reason"),
        "admitted_order": order,
        "tie_policy": c.get("tie_policy"),
        "metric_id": c.get("metric_id"),
        "model_costs": c.get("model_costs"),
        "rtl_costs": c.get("rtl_costs"),
        "model_status": c.get("model_status"),
        "rtl_status": c.get("rtl_status"),
        "dM": c.get("dM"), "dR": c.get("dR"),
        "model_margin": c.get("model_margin"), "rtl_margin": c.get("rtl_margin"),
        "model_choice": c.get("model_choice"), "rtl_best": c.get("rtl_best"),
        "selection": c.get("selection"),
        "designs": c.get("designs"),
        "models": c.get("models"),
        "rtl_run_ids": c.get("rtl_run_ids"), "model_run_ids": c.get("model_run_ids"),
        "reference_epoch": c.get("reference_epoch"),
        "epochs_consistent": len(epochs) <= 1,
        "workload_digest": c.get("workload_digest"),
        "provenance": c.get("provenance"), "scope": c.get("scope"), "discovery_credit": c.get("discovery_credit"),
        "integrity_errors": integrity,
        "model_predictions": {d: {"status": model_checks[d].get("status"), "makespan": model_checks[d].get("makespan")} for d in model_checks},
        "rtl_observations": {d: {"status": rtl_checks[d].get("status"), "makespan": rtl_checks[d].get("makespan"),
                                 "violations": sorted({v.get("code") for v in rtl_checks[d].get("violations", [])})[:5]} for d in rtl_checks},
    }
    if integrity or len(epochs) > 1:
        view["display_blocked"] = True
    return view


def workload_view(workload: dict, designs: list[dict]) -> dict:
    from rift.contracts.workload import validate_and_compile
    cfgs = {d["design"]: load_config(d["config"]) for d in designs}
    comp = validate_and_compile(workload, cfgs[designs[0]["design"]])
    initiators = []
    for m, ops in enumerate(comp.per_master):
        runs = []
        for op in ops:
            if runs and runs[-1]["byte_address"] == op.byte_address and runs[-1]["release"] == op.release and runs[-1]["gap"] == op.gap:
                runs[-1]["count"] += 1
                runs[-1]["last_index"] = op.index
            else:
                runs.append({"byte_address": op.byte_address, "word": op.word, "release": op.release, "gap": op.gap, "count": 1,
                             "first_index": op.index, "last_index": op.index,
                             "mapping": {d: {"bank": op.word % cfgs[d].num_out, "row": op.word // cfgs[d].num_out} for d in cfgs}})
        initiators.append({"master": m, "operations": len(ops), "runs": runs,
                           "op_ids": [op.op_id for op in ops]})
    return {"schema_version": 1, "workload_digest": comp.digest, "label": workload.get("label"), "program_kind": workload["program"]["kind"],
            "arrival_policy": workload["arrival_policy"], "total_operations": comp.total_ops, "initiators": initiators,
            "capacity_words": workload["capacity_words"], "held_constant": [
                "same logical program (identical workload digest) on every design and runner",
                "same 4096-word memory image f(q) distributed by each design's bank/row mapping",
                "4 request-free reset cycles; RespLat=1; always-granting banks",
                "each implementation applies its own backpressure (no borrowed schedules)"],
            "designs": {d: {"config_id": cfgs[d].config_id, "topology": cfgs[d].topology, "banks": cfgs[d].num_out,
                            "initiators": cfgs[d].num_in, "rows_per_bank": 1 << cfgs[d].addr_mem_width,
                            "descriptive_name": cfgs[d].raw.get("descriptive_name")} for d in cfgs},
            "workload": workload}


def trace_selection(run_id: str, op_id: str | None = None, cycle_from: int | None = None, cycle_to: int | None = None, limit: int = 5000) -> dict:
    d = RUNS / run_id
    p = d / "events.jsonl" if (d / "events.jsonl").exists() else d / "events.jsonl.gz"
    if not p.exists():
        raise FileNotFoundError(f"{run_id} has no events")
    m = read_json(d / "manifest.json")
    events = load_events(p)
    total = len(events)
    sel = []
    for e in events:
        if e["event_kind"] == "reset":
            continue
        if op_id is not None and e.get("master") is not None:
            if f"m{e['master']}:op{e['operation_index']:04d}" != op_id:
                continue
        if cycle_from is not None and e["cycle"] < cycle_from:
            continue
        if cycle_to is not None and e["cycle"] > cycle_to:
            continue
        sel.append({k: e.get(k) for k in ("cycle", "event_kind", "master", "operation_index", "byte_address", "bank", "row", "read_data", "monitor_id", "detail")})
    cycles = [e["cycle"] for e in events if e["event_kind"] != "reset"]
    return {"schema_version": 1, "run_id": run_id, "runner": m.get("runner"), "observation_role": m.get("observation_role"),
            "config_id": m.get("config_id"), "model_id": m.get("model_id"), "reference_epoch": m.get("reference_epoch"),
            "full_run_extent": {"first_cycle": min(cycles) if cycles else None, "last_cycle": max(cycles) if cycles else None, "events": total},
            "window": {"op_id": op_id, "from": cycle_from, "to": cycle_to}, "returned": min(len(sel), limit), "truncated": len(sel) > limit,
            "events": sel[:limit], "check": read_json(d / "check.json")}


def patch_review(repair_id: str, verification_id: str | None) -> dict:
    rd = STUDIES / repair_id
    sub = read_json(rd / "submission.json")
    table = read_json(rd / "candidate_table.json")
    cand = read_json(rd / "candidate_model.json")
    view = {"schema_version": 1, "repair_id": repair_id, "case_id": sub["case_id"], "candidate_model_id": sub["candidate_model_id"],
            "candidate_model_digest": sub["candidate_model_digest"], "parent_models": sub["parent_models"],
            "parent_model_digest": sub["parent_model_digest"], "patch": sub["patch"], "patch_digest": sub["patch_digest"],
            "semantic_change": sub["patch"]["semantic_change"], "development_result": sub["development_result"],
            "training_evidence": {k: v for k, v in sub["training_evidence"].items() if k != "workload_digests"},
            "candidate_table": table, "candidate_spec": cand, "lifecycle": "SUBMITTED", "verification": None}
    if verification_id:
        v = read_json(STUDIES / verification_id / "verification.json")
        if v.get("submission_digest") != digest(sub, strict=False):
            view["integrity_errors"] = ["verification refers to a different submission"]
        view["lifecycle"] = v["status"]
        view["verification"] = {k: v.get(k) for k in ("verification_id", "status", "failed_rules", "rules", "families", "retained_model",
                                                       "runtime", "contract_id", "basket_id", "scope", "development_replay")}
        view["verification"]["verification_id"] = verification_id
        view["verification"]["heldout_rows"] = v.get("heldout_rows")
    return view


def _curves(screen_run_id: str) -> dict:
    """Cumulative credited strict reversals versus charged RTL executions, per case and arm."""
    out: dict = {}
    for p in sorted((STUDIES / screen_run_id).glob("ledger__*.jsonl")):
        _, case, arm = p.stem.split("__")
        pts, n, rtl = [[0, 0]], 0, 0
        with open(p) as f:
            for line in f:
                e = json.loads(line)
                if e.get("status") != "EVALUATED":
                    continue
                rtl += 2
                n += int(e.get("discovery_credit", 0))
                pts.append([rtl, n])
        out.setdefault(case, {})[arm] = pts
    return out


def study_summary(screen_run_id: str) -> dict:
    s = read_json(STUDIES / screen_run_id / "summary.json")
    study = read_json(STUDIES / screen_run_id / "study.json")
    return {"schema_version": 1, "screen_run_id": screen_run_id, "study_id": s["study_id"], "study_digest": s["study_digest"],
            "budget": s["budget"], "cases": s["cases"], "not_run_arms": s.get("not_run_arms", {}), "executor": s.get("executor"),
            "case_definitions": study["cases"], "arms": study["arms"], "description": study["description"],
            "public_patterns_zero_credit": study["public_patterns_zero_credit"], "curves": _curves(screen_run_id)}


# ---------------------------------------------------------------------------
# Claims and case views
# ---------------------------------------------------------------------------
def decision_claim(case: dict, cmp: dict) -> dict:
    v = cmp["verdict"]
    names = {d: (cmp["designs"] or {}).get(d, {}).get("descriptive_name") or d for d in cmp["admitted_order"]}
    if cmp.get("display_blocked"):
        kind, stmt = "presentation_integrity_error", "Display blocked: the presentation check disagrees with the recorded evaluator result."
    elif v == "VALID_COUNTEREXAMPLE":
        kind = "pairwise_decision_reversal"
        stmt = f"The model selects {cmp['model_choice']}; the reference simulation prefers {cmp['rtl_best']} for this workload."
    elif v == "VALID_NO_REVERSAL":
        kind, stmt = "pairwise_agreement", f"The model and the reference simulation both prefer {cmp['rtl_best']} for this workload."
    elif v == "TIE_OR_SMALL_MARGIN":
        kind, stmt = "small_margin", "No decisive ordering under the declared margin."
    elif v == "MODEL_ERROR":
        kind, stmt = "model_failure", "Comparison unavailable: the fast-model execution failed its checks."
    else:
        kind, stmt = "reference_failure", "Comparison unavailable: reference checks failed."
    return {"schema_version": 1, "claim_id": f"{case['case_id']}/decision", "case_id": case["case_id"], "reference_epoch": cmp["reference_epoch"],
            "claim_kind": kind, "statement": stmt, "evidence_basis": "EXECUTED_ARTIFACT", "observation_role": "INDEPENDENT_EVALUATOR_RESULT",
            "scope": case["scope"], "metric_id": METRIC["id"], "direction": METRIC["direction"],
            "display_eligibility": "BLOCKED" if cmp.get("display_blocked") else ("COMPARATIVE" if v in ("VALID_COUNTEREXAMPLE", "VALID_NO_REVERSAL", "TIE_OR_SMALL_MARGIN") else "NO_COMPARATIVE_CLAIM"),
            "artifact_ids": [cmp["comparison_run_id"]] + list((cmp.get("rtl_run_ids") or {}).values()) + list((cmp.get("model_run_ids") or {}).values()),
            "limitations": case.get("limitations", [])}


@lru_cache(maxsize=1)
def registry() -> dict:
    return read_json(REGISTRY)


def list_cases() -> list[dict]:
    reg = registry()
    out = []
    for c in reg["cases"]:
        cmp = read_json(_dir(c["comparison_run_id"]) / "comparison.json")
        out.append({"case_id": c["case_id"], "title": c["title"], "short": c.get("short"), "verdict": cmp["verdict"], "provenance": c["provenance"],
                    "scope": c["scope"], "evidence_basis": "EXECUTED_ARTIFACT", "group": c.get("group", "Executed cases")})
    return out


def case_view(case_id: str) -> dict:
    reg = registry()
    case = next((c for c in reg["cases"] if c["case_id"] == case_id), None)
    if case is None:
        raise KeyError(case_id)
    cmp = comparison_view(case["comparison_run_id"])
    workload = read_json(_dir(case["comparison_run_id"]) / "workload.json") if (_dir(case["comparison_run_id"]) / "workload.json").exists() else None
    designs = [{"design": d, "config": cmp["designs"][d]["config_id"]} for d in cmp["admitted_order"]] if cmp.get("designs") else reg["designs"]
    current = _current_epoch()
    validity = "VALIDATED_FOR_CONTRACT" if (cmp["reference_epoch"] == current and reg.get("gate0a_study") and cmp["verdict"] not in ("HARNESS_INVALID", "FUNCTIONAL_MISMATCH", "TOOL_ERROR", "TIMEOUT")) else (
        "INVALIDATED" if cmp["reference_epoch"] != current else "UNVALIDATED")
    view = {
        "schema_version": 1,
        "case_id": case_id,
        "title": case["title"],
        "question": reg["question"],
        "summary": case.get("summary"),
        "group": case.get("group"),
        "evidence_basis": "EXECUTED_ARTIFACT",
        "presentation_mode": "STATIC_INSPECTION",
        "case_provenance": case["provenance"],
        "evaluation_scope": case["scope"],
        "discovery_credit": case.get("discovery_credit", 0),
        "diagnostic_available": bool(case.get("diagnostic_run_id")),
        "reference_epoch": cmp["reference_epoch"],
        "current_reference_epoch": current,
        "reference_validity": validity,
        "metric": METRIC,
        "designs": designs,
        "comparison": cmp,
        "claims": [decision_claim(case, cmp)],
        "workload": workload_view(workload, designs) if workload else None,
        "mechanism": case.get("mechanism"),
        "reduction": None,
        "repair": None,
        "limitations": case.get("limitations", []) + reg.get("global_limitations", []),
        "evidence": [],
    }
    links = [artifact_link(case["comparison_run_id"], "independent comparison verdict", [f"{case_id}/decision"])]
    for d, rid in (cmp.get("rtl_run_ids") or {}).items():
        links.append(artifact_link(rid, f"RTL reference run, design {d}", [f"{case_id}/decision"]))
    for d, rid in (cmp.get("model_run_ids") or {}).items():
        links.append(artifact_link(rid, f"fast-model prediction, design {d}", [f"{case_id}/decision"]))
    if case.get("reduction_id"):
        r = read_json(STUDIES / case["reduction_id"] / "reduction.json")
        view["reduction"] = {k: r.get(k) for k in ("status", "reduction_ratio_operations", "edit_set", "attempts", "surrogate_rejected", "rtl_rejected",
                                                    "rtl_executions_used", "rtl_budget", "minimality", "minimality_established", "history",
                                                    "surrogate_models", "orientation", "mode")}
        nb = r.get("neighbours")
        view["reduction"]["neighbours"] = {k: nb.get(k) for k in ("total", "surrogate_rejected", "rtl_rechecked", "rtl_rechecked_rejected", "rtl_contradictions")} if nb else None
        view["reduction"]["reduction_id"] = case["reduction_id"]
        view["reduction"]["original"] = {k: r["original"][k] for k in ("workload_digest", "operations", "verdict")}
        view["reduction"]["reduced"] = {k: r["reduced"].get(k) for k in ("workload_digest", "operations", "verdict", "final_rtl_run_ids", "final_model_run_ids", "reference_epoch")}
        view["reduction"]["reduced_workload"] = workload_view(r["reduced"]["workload"], designs)
        view["reduction"]["accepted_edits"] = [l["edit"] for l in r["log"] if l.get("result") in ("ACCEPTED", "ACCEPTED_BY_SURROGATE")]
        links.append(artifact_link(case["reduction_id"], "witness reduction record", [f"{case_id}/reduction"]))
        for d, rid in r["reduced"]["final_rtl_run_ids"].items():
            links.append(artifact_link(rid, f"reduced-witness RTL replay, design {d}", [f"{case_id}/reduction"]))
    if case.get("repair_id"):
        view["repair"] = patch_review(case["repair_id"], case.get("verification_id"))
        if case.get("verification_v2_id"):
            v2 = read_json(STUDIES / case["verification_v2_id"] / "verification.json")
            view["repair"]["verification_v2"] = {k: v2.get(k) for k in ("status", "failed_rules", "rules", "families", "retained_model", "runtime", "contract_id", "basket_id", "scope", "heldout_rows")}
            view["repair"]["verification_v2"]["verification_id"] = case["verification_v2_id"]
            links.append(artifact_link(case["verification_v2_id"], "independent verification, held-out basket v2", [f"{case_id}/repair"]))
        controls = []
        for key, vid in reg.get("verifications", {}).items():
            if vid in (case.get("verification_id"), case.get("verification_v2_id")):
                continue
            v = read_json(STUDIES / vid / "verification.json")
            sub = read_json(STUDIES / v["submission"].split("/")[-2] / "submission.json") if v.get("submission", "").count("/") >= 2 else {}
            controls.append({"label": sub.get("control") or v.get("semantic_change") or key, "status": v["status"], "failed": v.get("failed_rules", []), "verification_id": vid})
            links.append(artifact_link(vid, f"independent verification: {key.replace('_', ' ')}", [f"{case_id}/repair"]))
        view["repair_controls"] = controls
        links.append(artifact_link(case["repair_id"], "candidate repair submission", [f"{case_id}/repair"]))
        if case.get("verification_id"):
            links.append(artifact_link(case["verification_id"], "independent verification", [f"{case_id}/repair"]))
    for key, role in (("gate0a_study", "Gate 0A harness validation"), ("formal_study", "local formal properties (LIC 2x2)"),
                      ("benchmark_study", "runtime benchmark"), ("screen_run_id", "Phase 0 discovery screen"), ("compare_study", "calibration comparison study"),
                     ("map_study", "decision map study")):
        if reg.get(key):
            links.append(artifact_link(reg[key], role, ["project"]))
    view["evidence"] = links
    view["view_digest"] = digest(view, strict=False)
    return view


def project_record() -> dict:
    reg = registry()
    out = {"schema_version": 1, "question": reg["question"], "status": reg.get("status_record", {}), "global_limitations": reg.get("global_limitations", [])}
    if reg.get("gate0a_study"):
        g = read_json(STUDIES / reg["gate0a_study"] / "gate0a_report.json")
        out["gate0a"] = {"study_id": reg["gate0a_study"], "passed": g["passed"], "checks": [{k: c[k] for k in ("check", "passed", "expectation", "observed")} for c in g["checks"]]}
    if reg.get("formal_study"):
        f = read_json(STUDIES / reg["formal_study"] / "formal_result.json")
        out["formal"] = {k: f.get(k) for k in ("properties", "covers", "assumptions", "inventory", "expected_inventory", "claims", "harness_valid", "harness_problems", "configuration", "frontend", "scope_note")}
        out["formal"]["tasks"] = {k: {kk: v.get(kk) for kk in ("outcome", "depth", "elapsed_seconds", "engine")} for k, v in f["tasks"].items()}
        out["formal"]["study_id"] = reg["formal_study"]
    if reg.get("benchmark_study"):
        b = read_json(STUDIES / reg["benchmark_study"] / "benchmark.json")
        out["benchmark"] = {"study_id": reg["benchmark_study"], "target_speedup": b["target_speedup"], "useful_loop_target_met": b["useful_loop_target_met"],
                            "basket": b["basket"], "host": b["host"], "repetitions": b["repetitions"],
                            "results": [{k: r.get(k) for k in ("config_id", "model_id", "median_seconds", "speedup_per_invocation", "speedup_batched", "speedup_batched_vs_model_in_memory",
                                                                "speedup_summary_only_vs_cost_only", "kernel_speedup", "compiled_speedup_summary_only", "compiled_speedup_with_io",
                                                                "target_met", "primary_comparison", "useful_loop_comparison", "useful_loop_target_met")} for r in b["results"]]}
    if reg.get("screen_run_id"):
        out["screen"] = study_summary(reg["screen_run_id"])
    locks = {}
    for name in ("sources.lock.json", "toolchain.lock.json", "assertion_exclusions.json", "preprocessing.json"):
        locks[name] = read_json(ROOT / "locks" / name)
    out["locks"] = locks
    out["reproduce"] = reg.get("reproduce", [])
    return out


def specimens() -> dict:
    """Illustrative fixtures: a separate development namespace, never ingested as results."""
    data = read_json(SPECIMENS)
    data["namespace"] = "example/"
    data["evidence_basis_default"] = "ILLUSTRATIVE_FIXTURE"
    return data


def _compact_verdict(v: dict) -> dict:
    out = {"verdict": v["verdict"], "dM": v.get("dM"), "dR": v.get("dR"), "choice": v.get("model_choice"), "best": v.get("rtl_best"),
           "model_margin_met": (v.get("model_margin") or {}).get("met"), "rtl_margin_met": (v.get("rtl_margin") or {}).get("met")}
    if v.get("selection"):
        s = v["selection"]
        out.update(extra=s["extra_cycles"], regret=[s["regret"]["numerator"], s["regret"]["denominator"]])
    return out


@lru_cache(maxsize=1)
def map_view() -> dict | None:
    """The decision map, re-verified: run digests, recorded costs, every verdict and the summary."""
    sid = registry().get("map_study")
    if not sid:
        return None
    d = STUDIES / sid
    m = read_json(d / "map.json")
    man = read_json(d / "map_manifest.json")
    from rift.contracts.canonical import file_digest
    sm = read_json(d / "manifest.json")
    errors = [f"map study artifact {name} digest mismatch" for name, info in sm["artifacts"].items() if file_digest(d / name) != info["sha256"]]
    cells, more = check_map(m)
    errors += more
    return {
        "schema_version": 1, "map_id": m["map_id"], "map_study_id": sid, "evidence_basis": "EXECUTED_ARTIFACT",
        "reference_epoch": _current_epoch(), "order": m["order"], "configs": m["configs"], "models": m["models"],
        "question": man["question"], "axes": man["axes"], "features_note": man["features_note"], "scope": man["scope"],
        "evaluation": man["evaluation"], "prediction_before_execution": man["prediction_before_execution"],
        "grid": m["grid"], "cells": cells, "summary": m["summary"], "executor": m["executor"],
        "landmarks": [{"name": lm["name"], "case_id": lm["case_id"], "x": lm["features"]["route_sharing"], "y": lm["features"]["crossbar_collisions"],
                       "in_family": lm.get("in_family"), "outside_family_because": lm.get("outside_family_because", []),
                       "verdict": lm["verdict"], "rtl_costs": lm["rtl_costs"], "model_costs": lm["model_costs"], "comparison_run_id": lm["comparison_run_id"]}
                      for lm in m["landmarks"]],
        "integrity_errors": errors[:20], "integrity_error_count": len(errors),
    }


def check_map(m: dict) -> tuple[list[dict], list[str]]:
    """Compact cells for the viewer, plus every disagreement between the map record and its runs."""
    from rift.map import MODELS, summarize
    errors: list[str] = []
    order = m["order"]
    a, b = order
    current = _current_epoch()
    epochs = set()
    checks: dict[str, dict] = {}

    def observed(run: dict) -> dict:
        rid = run["run_id"]
        if rid not in checks:
            vr = verify_run(rid)
            if not vr["ok"]:
                errors.append(f"{rid}: {', '.join(vr['problems'])}")
            ck = read_json(RUNS / rid / "check.json")
            checks[rid] = {"status": ck["status"], "makespan": ck.get("makespan")}
        o = checks[rid]
        if o["status"] != run["status"] or o["makespan"] != run["makespan"]:
            errors.append(f"{rid}: recorded {run['status']}/{run['makespan']} but run says {o['status']}/{o['makespan']}")
        return o

    cells = []
    for c in m["cells"]:
        rtl = {dd: observed(c["rtl"][dd]) for dd in order}
        mod = {k: observed(v) for k, v in c["model"].items()}
        for dd in order:
            epochs.add(read_json(RUNS / c["rtl"][dd]["run_id"] / "manifest.json").get("reference_epoch"))
        view = {"i": c["i"], "j": c["j"], "x": c["features"]["route_sharing"], "y": c["features"]["crossbar_collisions"],
                "rtl": {dd: rtl[dd]["makespan"] for dd in order}, "model": {k: v["makespan"] for k, v in mod.items()},
                "runs": {"rtl_A": c["rtl"][a]["run_id"], "rtl_B": c["rtl"][b]["run_id"], **{f"model_{k}": v["run_id"] for k, v in c["model"].items()}},
                "verdict": {}}
        for k in MODELS:
            re = classify(order, {a: mod["A"], b: mod[k]}, rtl)
            rec = c["verdict"][k]
            for key in ("verdict", "dM", "dR", "model_choice", "rtl_best"):
                if re.get(key) != rec.get(key):
                    errors.append(f"cell ({c['i']},{c['j']}) {k}: recomputed {key} {re.get(key)} != recorded {rec.get(key)}")
            view["verdict"][k] = _compact_verdict(re)
        cells.append(view)
    if summarize(m["cells"], order) != m["summary"]:
        errors.append("recorded map summary differs from its recomputation")
    if epochs != {current}:
        errors.append(f"map RTL runs carry epochs {sorted(e for e in epochs if e)}; current {current}")
    return cells, errors


@lru_cache(maxsize=32)
def diagnostic_view(case_id: str) -> dict | None:
    """Measured internal butterfly activity for a case (supplementary, from a diagnostic trace)."""
    from rift.diagnostics import diagnostic_view as build
    case = next((c for c in registry()["cases"] if c["case_id"] == case_id), None)
    if not case or not case.get("diagnostic_run_id"):
        return None
    cmp = read_json(_dir(case["comparison_run_id"]) / "comparison.json")
    d = case.get("diagnostic_design", "B")
    return build(case_id, case["diagnostic_run_id"], cmp["rtl_run_ids"][d], cmp["designs"][d]["config_id"])
