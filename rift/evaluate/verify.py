"""Independent repair verifier.

Runs as its own command/process. It re-derives the candidate from the
submitted specification, checks the patch boundary, replays development
witnesses on fresh RTL runs, evaluates parent and candidate on the sealed
held-out basket against fresh reference executions, and applies the frozen
acceptance contract. Search-time improvement is never sufficient by itself.
The parent model is always retained as the baseline.
"""

from __future__ import annotations

import json
import random
import statistics
import time
from pathlib import Path

from rift.contracts.canonical import digest, read_json
from rift.contracts.config import load_config
from rift.contracts.workload import validate_and_compile
from rift.evaluate.compare import classify
from rift.model.registry import get_spec, model_digest, run_model
from rift.modelrun import run_model_artifact
from rift.paths import ROOT, STUDIES, rel
from rift.rtl import run_rtl
from rift.store import RunDir
from rift.workloads.generators import fixed_word_streams, random_legal

HELDOUT = ROOT / "experiments" / "heldout" / "heldout_v1.json"
ALLOWED_FAMILIES = {"crossbar", "butterfly", "shared_link", "fitted_penalty"}
ALLOWED_SPEC_KEYS = {"family", "params", "applies_to", "contract", "provenance", "admissible_fast_model", "parent_model_id",
                     "parent_model_digest", "mechanism", "resp_lat", "model_id", "training_evidence", "spec_digest"}
DEV_WITNESS_CAP = 15  # 2 RTL executions each, within the 32-execution repair/revalidation reserve


def heldout_workloads(manifest: dict) -> list[dict]:
    out = []
    for fam in manifest["families"]:
        lo, hi = fam["seeds"]
        for seed in range(lo, hi + 1):
            p = fam["params"]
            if fam["generator"] == "fixed_streams_random":
                rng = random.Random(seed)
                words = [rng.randrange(p["word_range"]) for _ in range(8)]
                w = fixed_word_streams(words, p["reads"], label=f"{fam['family_id']} seed={seed}")
            elif fam["generator"] in ("pair_structured", "pair_two_phase"):
                w = _pair_workload(seed, fam["generator"], p)
                w["label"] = f"{fam['family_id']} seed={seed}"
            elif fam["generator"] == "random_legal":
                w = random_legal(seed, max_ops=p.get("max_ops", 24), p_response=p.get("p_response", 0.3), max_gap=p.get("max_gap", 3),
                                 hot_words=p.get("hot_words"))
                w["label"] = f"{fam['family_id']} seed={seed}"
            else:
                raise ValueError(f"unknown generator {fam['generator']}")
            out.append({"family_id": fam["family_id"], "seed": seed, "designs": fam["designs"], "workload": w})
    return out


def _pair_workload(seed: int, kind: str, p: dict) -> dict:
    """Pair-structured streams from public facts: initiators 2k/2k+1 share a stage-1 router; bank group = (word mod 16) >> 2."""
    from rift.contracts.workload import read_sequences
    rng = random.Random(seed)
    per = []
    words = []
    for pair in range(4):
        g0 = rng.randrange(4)
        share = rng.random() < p.get("p_share", 0.5)
        g1 = g0 if share else rng.choice([g for g in range(4) if g != g0])
        for g in (g0, g1):
            words.append(rng.randrange(4) * 16 + g * 4 + rng.randrange(4))
    for m, wd in enumerate(words):
        rel = {"release": "after_response"} if p.get("after_response") else {}
        if kind == "pair_two_phase":
            other = rng.randrange(64)
            k = rng.randint(4, p["reads"] - 4)
            ops = [dict({"byte_address": wd * 4}, **rel) for _ in range(k)] + [dict({"byte_address": other * 4}, **rel) for _ in range(p["reads"] - k)]
        else:
            ops = [dict({"byte_address": wd * 4}, **rel) for _ in range(p["reads"])]
        per.append(ops)
    return read_sequences(per)


def patch_boundary(sub: dict, cand: dict, parent: dict) -> list[str]:
    problems = []
    if cand.get("family") not in ALLOWED_FAMILIES:
        problems.append(f"family {cand.get('family')!r} is outside the editable model surface")
    extra = set(cand) - ALLOWED_SPEC_KEYS
    if extra:
        problems.append(f"unexpected specification fields {sorted(extra)}")
    blob = json.dumps(cand.get("params", {}))
    if "sha256:" in blob or "byte_address" in blob or "workload" in blob:
        problems.append("specification references workload identities or addresses (benchmark-specific predicate)")
    if sub["models"]["A"] != sub["parent_models"]["A"]:
        problems.append("non-editable design's model changed")
    if cand.get("parent_model_digest") and cand["parent_model_digest"] != model_digest(parent):
        problems.append("candidate's recorded parent digest does not match the current parent")
    return problems


def _cost_only_seconds(spec, items) -> float | None:
    reps = []
    for _ in range(3):
        t0 = time.perf_counter()
        for cfg, comp in items:
            try:
                run_model(spec, cfg, comp, record_events=False)
            except Exception:
                return None
        reps.append(time.perf_counter() - t0)
    return statistics.median(reps)


def _safe_model(spec, cfg, comp) -> dict:
    try:
        r = run_model(spec, cfg, comp, record_events=False)
        return {"status": r.status, "makespan": r.makespan}
    except Exception as e:
        return {"status": "MODEL_ERROR", "makespan": None, "detail": f"{type(e).__name__}: {e}"}


def verify_submission(sub_path: Path, basket: Path | None = None) -> dict:
    sub = read_json(sub_path)
    manifest = read_json(basket or HELDOUT)
    contract = manifest["acceptance_contract"]
    t0 = time.time()
    parent_a = get_spec(sub["parent_models"]["A"])
    parent_b = get_spec(sub["parent_models"]["B"])
    try:
        cand_b = get_spec(sub["candidate_model_id"])
    except KeyError:
        cand_b = None
    rules = {}
    notes = []
    if cand_b is None:
        rules["R6"] = {"passed": False, "detail": "candidate specification not found"}
        return _finish(sub, sub_path, manifest, rules, {}, [], [], notes, t0, inconclusive=False)
    rebuilt_digest = model_digest(cand_b)
    if rebuilt_digest != sub.get("candidate_model_digest"):
        notes.append("candidate digest differs from submission (specification changed after submission)")
    pb = patch_boundary(sub, cand_b, parent_b)
    rules["R6"] = {"passed": not pb and rebuilt_digest == sub.get("candidate_model_digest"), "detail": pb or "only the editable design's specification changed"}
    if pb:
        notes.append("patch boundary violated: the candidate was not built or evaluated")
        return _finish(sub, sub_path, manifest, rules, {}, [], [], notes, t0, inconclusive=False)

    # ---- development witnesses: fresh RTL replay -------------------------
    dev_rows = []
    screen = STUDIES / sub["training_evidence"]["screen_run_id"]
    wanted = set(sub["training_evidence"]["workload_digests"])
    witnesses = []
    for p in sorted(screen.glob(f"ledger__{sub['case_id']}__*.jsonl")):
        with open(p) as f:
            for line in f:
                e = json.loads(line)
                if e.get("workload_digest") in wanted and (e.get("verdict") or {}).get("verdict") == "VALID_COUNTEREXAMPLE":
                    if e["workload_digest"] not in {w["workload_digest"] for w in witnesses}:
                        witnesses.append({"workload_digest": e["workload_digest"], "workload": e["workload"]})
    witnesses = witnesses[:DEV_WITNESS_CAP]
    designs = sub["designs"]
    cfgs = {d["design"]: load_config(d["config"]) for d in designs}
    unresolved = 0
    for w in witnesses:
        comp = {d: validate_and_compile(w["workload"], cfgs[d]) for d in cfgs}
        rtl = {d: run_rtl(cfgs[d], comp[d], compress=True, tags=("verify", "dev_witness")) for d in cfgs}
        mod = {"A": _safe_model(parent_a, cfgs["A"], comp["A"]), "B": _safe_model(cand_b, cfgs["B"], comp["B"])}
        v = classify(["A", "B"], mod, {d: rtl[d]["check"] for d in "AB"})
        unresolved += v["verdict"] == "VALID_COUNTEREXAMPLE"
        dev_rows.append({"workload_digest": w["workload_digest"], "verdict_with_candidate": v["verdict"],
                         "rtl_run_ids": {d: rtl[d]["run_id"] for d in "AB"}, "rtl_costs": v.get("rtl_costs"), "candidate_costs": v.get("model_costs")})
    rules["R5"] = {"passed": unresolved == 0, "detail": f"{unresolved} of {len(witnesses)} replayed development witnesses remain strict reversals"}

    # ---- sealed held-out basket ------------------------------------------
    rows = []
    timing_items = []
    ref_fail = 0
    for item in heldout_workloads(manifest):
        dz = item["designs"]
        cz = {d["design"]: load_config(d["config"]) for d in dz}
        comp = {d: validate_and_compile(item["workload"], cz[d]) for d in cz}
        rtl = {d: run_rtl(cz[d], comp[d], compress=True, tags=("verify", item["family_id"])) for d in cz}
        par = {"A": run_model_artifact(parent_a, cz["A"], comp["A"], compress=True, tags=("verify", "parent")),
               "B": run_model_artifact(parent_b, cz["B"], comp["B"], compress=True, tags=("verify", "parent"))}
        can = {"A": par["A"], "B": run_model_artifact(cand_b, cz["B"], comp["B"], compress=True, tags=("verify", "candidate"))}
        timing_items.append((cz["B"], comp["B"]))
        rc = {d: rtl[d]["check"] for d in "AB"}
        vp = classify(["A", "B"], {d: par[d]["check"] for d in "AB"}, rc)
        vc = classify(["A", "B"], {d: can[d]["check"] for d in "AB"}, rc)
        if any(rc[d]["status"] != "COMPLETED" for d in "AB"):
            ref_fail += 1
        rows.append({"family_id": item["family_id"], "seed": item["seed"], "config_B": dz[1]["config"],
                     "workload_digest": comp["A"].digest, "rtl_costs": vp.get("rtl_costs"), "rtl_run_ids": {d: rtl[d]["run_id"] for d in "AB"},
                     "parent": {"verdict": vp["verdict"], "costs": vp.get("model_costs"), "regret": (vp.get("selection") or {}).get("regret"),
                                "model_run_ids": {d: par[d]["run_id"] for d in "AB"}},
                     "candidate": {"verdict": vc["verdict"], "costs": vc.get("model_costs"), "regret": (vc.get("selection") or {}).get("regret"),
                                   "model_run_ids": {d: can[d]["run_id"] for d in "AB"}}})
    usable = [r for r in rows if r["parent"]["verdict"] not in ("TOOL_ERROR", "TIMEOUT", "HARNESS_INVALID", "FUNCTIONAL_MISMATCH")]
    inconclusive = ref_fail > 0.1 * len(rows)
    cand_model_fail = sum(1 for r in usable if r["candidate"]["verdict"] in ("MODEL_ERROR", "TIMEOUT"))
    rules["R1"] = {"passed": cand_model_fail == 0, "detail": f"{cand_model_fail} candidate MODEL_ERROR/TIMEOUT outcomes"}
    rev_p = sum(1 for r in usable if r["parent"]["verdict"] == "VALID_COUNTEREXAMPLE")
    rev_c = sum(1 for r in usable if r["candidate"]["verdict"] == "VALID_COUNTEREXAMPLE")
    rules["R2"] = {"passed": rev_c < rev_p, "detail": f"strict reversals: parent {rev_p}, candidate {rev_c}"}
    regressions = [r for r in usable if r["candidate"]["verdict"] == "VALID_COUNTEREXAMPLE" and r["parent"]["verdict"] != "VALID_COUNTEREXAMPLE"
                   and (r["parent"]["regret"] or {}).get("numerator", 1) == 0]
    rules["R3"] = {"passed": not regressions, "detail": f"{len(regressions)} regressions",
                   "regressed_workloads": [{"family_id": r["family_id"], "seed": r["seed"], "rtl_costs": r["rtl_costs"], "parent": r["parent"]["costs"], "candidate": r["candidate"]["costs"]} for r in regressions]}
    tp, tc = _cost_only_seconds(parent_b, timing_items), _cost_only_seconds(cand_b, timing_items)
    if tc is None or tp is None:
        rules["R4"] = {"passed": False, "detail": "runtime unavailable: the candidate could not execute every held-out workload", "ratio": None}
    else:
        rules["R4"] = {"passed": tc <= 3 * tp, "detail": f"candidate {tc:.4f}s vs parent {tp:.4f}s (ratio {tc / tp:.2f})", "ratio": tc / tp}
    return _finish(sub, sub_path, manifest, rules, {"parent_seconds": tp, "candidate_seconds": tc}, rows, dev_rows, notes, t0, inconclusive)


def _family_summary(rows):
    fams = {}
    for r in rows:
        f = fams.setdefault(r["family_id"], {"workloads": 0, "parent_reversals": 0, "candidate_reversals": 0, "parent_mean_regret": 0.0,
                                              "candidate_mean_regret": 0.0, "parent_wrong_choices": 0, "candidate_wrong_choices": 0, "config_B": r["config_B"]})
        f["workloads"] += 1
        for who in ("parent", "candidate"):
            f[f"{who}_reversals"] += r[who]["verdict"] == "VALID_COUNTEREXAMPLE"
            reg = (r[who]["regret"] or {}).get("decimal", 0.0)
            f[f"{who}_mean_regret"] += reg
            f[f"{who}_wrong_choices"] += reg > 0
    for f in fams.values():
        for who in ("parent", "candidate"):
            f[f"{who}_mean_regret"] /= max(1, f["workloads"])
    return fams


def _finish(sub, sub_path, manifest, rules, timing, rows, dev_rows, notes, t0, inconclusive):
    order = ["R1", "R2", "R3", "R4", "R5", "R6"]
    failed = [r for r in order if r in rules and not rules[r]["passed"]]
    if inconclusive:
        status = "INCONCLUSIVE"
    elif failed or any(r not in rules for r in order):
        status = "REJECTED"
    else:
        status = "ACCEPTED_UNDER_CONTRACT"
    result = {
        "schema_version": 1,
        "verifier": "rift.evaluate.verify/v1",
        "submission": rel(Path(sub_path)) if Path(sub_path).is_absolute() else str(sub_path),
        "submission_digest": digest(sub, strict=False),
        "case_id": sub["case_id"],
        "contract_id": manifest["acceptance_contract"]["contract_id"],
        "basket_id": manifest["basket_id"],
        "parent_models": sub["parent_models"],
        "candidate_model_id": sub["candidate_model_id"],
        "patch_digest": sub.get("patch_digest"),
        "semantic_change": (sub.get("patch") or {}).get("semantic_change"),
        "status": status,
        "failed_rules": failed,
        "rules": rules,
        "retained_model": sub["parent_models"]["B"] if status != "ACCEPTED_UNDER_CONTRACT" else sub["candidate_model_id"],
        "families": _family_summary(rows),
        "heldout_rows": rows,
        "development_replay": dev_rows,
        "runtime": timing,
        "notes": notes,
        "elapsed_seconds": round(time.time() - t0, 2),
        "scope": "Acceptance under contract repair-acceptance-v1 on basket heldout-v1 (4 families x 12 workloads). Not a full research-study result.",
    }
    sd = RunDir("verify", root=STUDIES)
    sd.write_json("verification.json", result)
    sd.finalize({"schema_version": 1, "kind": "verification", "status": status, "case_id": sub["case_id"],
                 "candidate_model_id": sub["candidate_model_id"], "observation_role": "INDEPENDENT_EVALUATOR_RESULT",
                 "evidence_basis": "EXECUTED_ARTIFACT", "tags": ["verify", sub["case_id"]]})
    result["verification_id"] = sd.run_id
    return result
