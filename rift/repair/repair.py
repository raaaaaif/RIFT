"""Structural model repair over a declared model-change grammar.

The repairer may change only the editable design's model specification
(written under models/candidates/). It selects a structure using development
evidence only: previously recorded RTL results from the discovery screen for
the case. It never opens the sealed held-out basket; acceptance is decided by
the separate verifier (rift.evaluate.verify). The search over the grammar is
deterministic.
"""

from __future__ import annotations

import builtins
import copy
import json
import time
from pathlib import Path

from rift.contracts.canonical import digest, read_json, write_json_replace
from rift.contracts.config import load_config
from rift.contracts.workload import validate_and_compile
from rift.evaluate.compare import classify
from rift.model.registry import REPAIRED_DIR, get_spec, model_digest, run_model
from rift.paths import ROOT, STUDIES, rel
from rift.store import RunDir

HELDOUT_DIR = ROOT / "experiments" / "heldout"


class SealedAccessError(PermissionError):
    pass


def _guard_open():
    """Refuse any attempt by the repair code path to read the sealed held-out basket."""
    real_open = builtins.open

    def guarded(file, *a, **kw):
        p = Path(file).resolve() if isinstance(file, (str, Path)) else None
        if p is not None and HELDOUT_DIR.resolve() in p.parents:
            raise SealedAccessError(f"repair may not read sealed held-out data: {p}")
        return real_open(file, *a, **kw)

    return real_open, guarded


def grammar(parent: dict, fitted_id: str | None) -> list[tuple[str, dict]]:
    """Model-change grammar for the editable (butterfly-side) model."""
    cands = [("parent (no change)", copy.deepcopy(parent))]
    for g in (2, 4, 8):
        for s in (0, 1, 2, 3):
            cands.append((f"shared_link [{g},{s}]", {"family": "shared_link", "params": {"links": [[g, s]]}}))
    for s1 in (1, 2, 3):
        for s2 in (0, 1, 2):
            cands.append((f"shared_link [2,{s1}]+[4,{s2}]", {"family": "shared_link", "params": {"links": [[2, s1], [4, s2]]}}))
    cands.append(("arbitration: unfair round robin", {"family": "crossbar", "params": {"fair": False, "lock_in": True}}))
    cands.append(("response latency +1", {**copy.deepcopy(parent), "resp_lat": 2}))
    if fitted_id:
        f = get_spec(fitted_id)
        cands.append(("parametric fit only (fitted per-path penalties)", {k: f[k] for k in ("family", "params")}))
    out = []
    for label, body in cands:
        spec = {"family": body["family"], "params": body["params"], "applies_to": ["BFLY4", "BFLY2"],
                "contract": {"promise": "RANKING_PRESERVATION", "scope": "candidate repair; acceptance decided by the independent verifier",
                             "declared_omissions": ["LFSR-derived priorities (round-robin arbitration)"]}}
        if "resp_lat" in body:
            spec["resp_lat"] = body["resp_lat"]
        out.append((label, spec))
    return out


def development_set(screen_run_id: str, case_id: str) -> list[dict]:
    """Recorded (workload, RTL costs) pairs from every arm of the case's discovery screen."""
    sdir = STUDIES / screen_run_id
    seen, rows = set(), []
    for p in sorted(sdir.glob(f"ledger__{case_id}__*.jsonl")):
        with open(p) as f:
            for line in f:
                e = json.loads(line)
                if e.get("status") != "EVALUATED" or "rtl_costs" not in (e.get("verdict") or {}):
                    continue
                if e["workload_digest"] in seen:
                    continue
                seen.add(e["workload_digest"])
                rows.append({"workload": e["workload"], "workload_digest": e["workload_digest"], "rtl_costs": e["verdict"]["rtl_costs"],
                             "rtl_run_ids": {d: e["rtl"][d]["run_id"] for d in e["rtl"]}, "parent_verdict": e["verdict"]["verdict"],
                             "arm_id": e["arm_id"]})
    return rows


def evaluate_candidate(spec_a: dict, spec_b: dict, cfg_a, cfg_b, rows: list[dict]) -> dict:
    errors = reversals = 0
    regret_sum = 0.0
    abs_err = 0
    witnesses_left = 0
    t0 = time.perf_counter()
    for r in rows:
        ca, cb = validate_and_compile(r["workload"], cfg_a), validate_and_compile(r["workload"], cfg_b)
        ma = run_model(spec_a, cfg_a, ca, record_events=False)
        mb = run_model(spec_b, cfg_b, cb, record_events=False)
        if ma.makespan is None or mb.makespan is None:
            return {"valid": False}
        v = classify(["A", "B"], {"A": {"status": "COMPLETED", "makespan": ma.makespan}, "B": {"status": "COMPLETED", "makespan": mb.makespan}},
                     {d: {"status": "COMPLETED", "makespan": r["rtl_costs"][d]} for d in ("A", "B")})
        reversals += v["verdict"] == "VALID_COUNTEREXAMPLE"
        if r["parent_verdict"] == "VALID_COUNTEREXAMPLE" and v["verdict"] == "VALID_COUNTEREXAMPLE":
            witnesses_left += 1
        reg = v["selection"]["regret"]["decimal"]
        regret_sum += reg
        errors += reg > 0
        abs_err += abs(mb.makespan - r["rtl_costs"]["B"])
    return {"valid": True, "strict_reversals": reversals, "wrong_choices": errors, "mean_regret": regret_sum / max(1, len(rows)),
            "mae_B": abs_err / max(1, len(rows)), "unresolved_witnesses": witnesses_left, "seconds": time.perf_counter() - t0}


def submit_control(case_path: Path, model_id: str, spec: dict, label: str) -> dict:
    """Submit a deliberately chosen candidate (negative control or conventional baseline) for verification."""
    case = read_json(case_path)
    parent_a = get_spec(case["parent_models"]["A"])
    parent_b = get_spec(case["parent_models"]["B"])
    write_json_replace(REPAIRED_DIR / f"{model_id}.json", spec)
    cand = get_spec(model_id)
    patch = {"editable_design": "B", "allowed_surface": "models/candidates/<model_id>.json (model specification only)",
             "parent": {"model_id": parent_b["model_id"], "family": parent_b["family"], "params": parent_b["params"]},
             "candidate": {"model_id": model_id, "family": spec["family"], "params": spec["params"]}, "semantic_change": label}
    sub = {"schema_version": 1, "case_id": case["case_id"], "designs": case["designs"],
           "models": {"A": parent_a["model_id"], "B": model_id}, "parent_models": {"A": parent_a["model_id"], "B": parent_b["model_id"]},
           "parent_model_digest": model_digest(parent_b), "candidate_model_id": model_id, "candidate_model_digest": model_digest(cand),
           "patch": patch, "patch_digest": digest(patch, strict=False),
           "training_evidence": {"screen_run_id": case["screen_run_id"], "development_workloads": 0, "development_witnesses": 0,
                                 "workload_digests": [r["workload_digest"] for r in development_set(case["screen_run_id"], case["case_id"])]},
           "development_result": None, "status": "SUBMITTED", "control": label}
    sd = RunDir("repair", root=STUDIES)
    sd.write_json("case.json", case)
    sd.write_json("candidate_table.json", [])
    sd.write_json("candidate_model.json", cand)
    sd.write_json("submission.json", sub)
    sd.finalize({"schema_version": 1, "kind": "repair", "status": "SUBMITTED", "case_id": case["case_id"], "candidate_model_id": model_id,
                 "control": label, "tags": ["repair", "control", case["case_id"]]})
    return {"repair_id": sd.run_id, "submission_path": rel(sd.path / "submission.json")}


def run_repair(case_path: Path) -> dict:
    case = read_json(case_path)
    real_open, guarded = _guard_open()
    builtins.open = guarded
    try:
        return _run_repair(case, case_path)
    finally:
        builtins.open = real_open


def _run_repair(case: dict, case_path: Path) -> dict:
    designs = case["designs"]
    cfg_a, cfg_b = load_config(designs[0]["config"]), load_config(designs[1]["config"])
    parent_a = get_spec(case["parent_models"]["A"])
    parent_b = get_spec(case["parent_models"]["B"])
    rows = development_set(case["screen_run_id"], case["case_id"])
    t0 = time.time()
    table = []
    for label, spec in grammar(parent_b, case.get("fitted_model")):
        spec = dict(spec, model_id="(unsaved)")
        res = evaluate_candidate(parent_a, spec, cfg_a, cfg_b, rows)
        complexity = len(spec["params"].get("links", [])) if spec["family"] == "shared_link" else (0 if label.startswith("parent") else 1)
        table.append({"edit": label, "family": spec["family"], "params": spec["params"], "resp_lat": spec.get("resp_lat", 1),
                      "complexity": complexity, **res})
    valid = [t for t in table if t.get("valid")]
    best = min(valid, key=lambda t: (t["unresolved_witnesses"], t["strict_reversals"], t["wrong_choices"], round(t["mean_regret"], 9), t["complexity"], t["mae_B"]))
    parent_row = table[0]
    cand_id = f"repair_{case['case_id']}_{digest({'f': best['family'], 'p': best['params'], 'r': best['resp_lat']})[7:15]}"
    cand_spec = {
        "family": best["family"], "params": best["params"], "applies_to": ["BFLY4", "BFLY2"],
        "contract": {"promise": "RANKING_PRESERVATION", "scope": "candidate repair of " + parent_b["model_id"] + "; acceptance decided by the independent verifier",
                     "declared_omissions": ["LFSR-derived priorities (round-robin arbitration)"]},
        "provenance": f"deterministic structural repair search for case {case['case_id']}",
        "admissible_fast_model": True,
        "parent_model_id": parent_b["model_id"],
        "parent_model_digest": model_digest(parent_b),
        "mechanism": best["edit"],
    }
    if best["resp_lat"] != 1:
        cand_spec["resp_lat"] = best["resp_lat"]
    write_json_replace(REPAIRED_DIR / f"{cand_id}.json", cand_spec)
    cand_spec_full = get_spec(cand_id)
    patch = {
        "editable_design": "B",
        "allowed_surface": "models/candidates/<model_id>.json (model specification only)",
        "parent": {"model_id": parent_b["model_id"], "family": parent_b["family"], "params": parent_b["params"]},
        "candidate": {"model_id": cand_id, "family": cand_spec["family"], "params": cand_spec["params"], "resp_lat": cand_spec.get("resp_lat", 1)},
        "semantic_change": best["edit"],
    }
    submission = {
        "schema_version": 1,
        "case_id": case["case_id"],
        "designs": designs,
        "models": {"A": parent_a["model_id"], "B": cand_id},
        "parent_models": {"A": parent_a["model_id"], "B": parent_b["model_id"]},
        "parent_model_digest": model_digest(parent_b),
        "candidate_model_id": cand_id,
        "candidate_model_digest": model_digest(cand_spec_full),
        "patch": patch,
        "patch_digest": digest(patch),
        "training_evidence": {"screen_run_id": case["screen_run_id"], "development_workloads": len(rows),
                              "development_witnesses": sum(1 for r in rows if r["parent_verdict"] == "VALID_COUNTEREXAMPLE"),
                              "workload_digests": [r["workload_digest"] for r in rows]},
        "development_result": {"parent": {k: parent_row.get(k) for k in ("strict_reversals", "wrong_choices", "mean_regret", "mae_B", "unresolved_witnesses")},
                               "candidate": {k: best.get(k) for k in ("strict_reversals", "wrong_choices", "mean_regret", "mae_B", "unresolved_witnesses")}},
        "status": "SUBMITTED",
    }
    sd = RunDir("repair", root=STUDIES)
    sd.write_json("case.json", case)
    sd.write_json("candidate_table.json", table)
    sd.write_json("candidate_model.json", cand_spec_full)
    sd.write_json("submission.json", submission)
    sd.finalize({"schema_version": 1, "kind": "repair", "status": "SUBMITTED", "case_id": case["case_id"], "candidate_model_id": cand_id,
                 "tags": ["repair", case["case_id"]]})
    return {"repair_id": sd.run_id, "path": rel(sd.path), "submission_path": rel(sd.path / "submission.json"), "submission": submission,
            "elapsed_seconds": round(time.time() - t0, 2), "table": table}
