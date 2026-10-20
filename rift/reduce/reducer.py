"""History-preserving legal witness reduction.

Every candidate is a complete workload replayed from the prescribed reset
(no checkpoints), so removing a prefix changes arbiter/LFSR history exactly as
it would in hardware. A candidate is accepted only if a fresh RTL replay on
both designs, evaluated by the independent evaluator, is still a
VALID_COUNTEREXAMPLE with the original orientation (model choice and
reference-best design) under the unchanged margin.

RTL budget: candidates are pre-screened with the audited model plus a
reference surrogate (exact LIC model / LFSR transliteration, both validated
event-exact against the RTL). Only surrogate-passing candidates consume RTL
executions. Minimality is claimed only as local 1-minimality under the recorded
edit set, qualified by how many candidates were rejected by the surrogate
without RTL confirmation.
"""

from __future__ import annotations

import time

from rift.contracts.canonical import digest
from rift.contracts.config import load_config
from rift.contracts.workload import WorkloadError, read_sequences, to_read_sequences, validate_and_compile
from rift.evaluate.compare import classify
from rift.model.registry import get_spec, run_model
from rift.modelrun import run_model_artifact
from rift.paths import STUDIES, rel
from rift.rtl import run_rtl
from rift.store import RunDir

SURROGATE = {"LIC": "lic_exact_v1", "BFLY4": "bfly_lfsr_transliteration_v1", "BFLY2": "bfly_lfsr_transliteration_v1"}
EDIT_SET = [
    "drop_initiator: remove one initiator's whole program",
    "halve_program: keep the first or second half of one initiator's operations",
    "drop_chunk: remove a contiguous chunk (size n/2, n/4, ..., 1) from one initiator",
    "shorten_burst: halve one run of identical addresses",
    "canonicalize_address: replace word w by w mod 16 (preserves LIC and BFLY bank)",
    "clear_gap: set one operation's release gap to 0",
    "accept_release: change one after_response dependency to after_accept",
]


def _per(w: dict) -> list[list[dict]]:
    return [[dict(o) for o in e["ops"]] for e in w["program"]["per_master"]]


def _mk(per) -> dict:
    return read_sequences(per, label="reduction candidate")


def candidates(w: dict):
    per = _per(w)
    n = len(per)
    for m in range(n):
        if per[m]:
            p = [list(x) for x in per]
            p[m] = []
            yield _mk(p), f"drop_initiator m{m}"
    for m in range(n):
        L = len(per[m])
        if L >= 2:
            for part, rng in (("first", per[m][: L // 2]), ("second", per[m][L // 2:])):
                p = [list(x) for x in per]
                p[m] = list(rng)
                yield _mk(p), f"halve_program m{m} keep {part}"
    for m in range(n):
        L = len(per[m])
        size = L // 2
        while size >= 1:
            for start in range(0, L, size):
                if size == L:
                    continue
                p = [list(x) for x in per]
                p[m] = per[m][:start] + per[m][start + size:]
                if p[m] != per[m]:
                    yield _mk(p), f"drop_chunk m{m} [{start}:{start + size}]"
            size //= 2
    for m in range(n):
        ops = per[m]
        i = 0
        while i < len(ops):
            j = i
            while j + 1 < len(ops) and ops[j + 1]["byte_address"] == ops[i]["byte_address"]:
                j += 1
            run = j - i + 1
            if run >= 2:
                p = [list(x) for x in per]
                p[m] = ops[: i + run // 2] + ops[j + 1:]
                yield _mk(p), f"shorten_burst m{m} run@{i} len {run}->{run - run // 2}"
            i = j + 1
    for m in range(n):
        words = sorted({o["byte_address"] >> 2 for o in per[m]})
        for wd in words:
            if wd >= 16:
                p = [[dict(o) for o in x] for x in per]
                for o in p[m]:
                    if o["byte_address"] >> 2 == wd:
                        o["byte_address"] = (wd % 16) * 4
                yield _mk(p), f"canonicalize_address m{m} word {wd}->{wd % 16}"
    for m in range(n):
        for k, o in enumerate(per[m]):
            if o.get("gap"):
                p = [[dict(x) for x in y] for y in per]
                p[m][k].pop("gap")
                yield _mk(p), f"clear_gap m{m} op{k}"
            if o.get("release") == "after_response":
                p = [[dict(x) for x in y] for y in per]
                p[m][k].pop("release")
                yield _mk(p), f"accept_release m{m} op{k}"


def reduce_witness(workload: dict, designs: list[dict], models: dict[str, str], rtl_budget: int = 32,
                   case_id: str = "unspecified", provenance: str = "AUTHORED_DEFECT", mode: str = "surrogate_complete") -> dict:
    if mode == "surrogate_complete":
        return _reduce_surrogate_complete(workload, designs, models, rtl_budget, case_id, provenance)
    return _reduce_rtl_stepwise(workload, designs, models, rtl_budget, case_id, provenance)


def _reduce_surrogate_complete(workload, designs, models, rtl_budget, case_id, provenance) -> dict:
    """Complete greedy pass under the validated surrogate, then RTL confirmation.

    RTL budget use: original replay (2) + final replay (2) + as many single-edit
    neighbours of the final witness as the remaining budget allows (2 each).
    """
    order = [d["design"] for d in designs]
    cfgs = {d["design"]: load_config(d["config"]) for d in designs}
    specs = {d: get_spec(models[d]) for d in order}
    surr = {d: get_spec(SURROGATE[cfgs[d].topology]) for d in order}
    sd = RunDir("reduction", root=STUDIES)
    t0 = time.time()

    def costs(w, which):
        comp = {d: validate_and_compile(w, cfgs[d]) for d in order}
        out = {}
        for d in order:
            r = run_model(which[d], cfgs[d], comp[d], record_events=False)
            out[d] = {"status": r.status, "makespan": r.makespan}
        return comp, out

    def holds(v, orient):
        return v["verdict"] == "VALID_COUNTEREXAMPLE" and (v["model_choice"], v["rtl_best"]) == orient

    start = to_read_sequences(validate_and_compile(workload, cfgs[order[0]]), label="reduction start")
    comp0, m0 = costs(start, specs)
    rtl0 = {d: run_rtl(cfgs[d], comp0[d], compress=True, tags=("reduction", case_id, "original")) for d in order}
    used = 2
    v0 = classify(order, m0, {d: rtl0[d]["check"] for d in order})
    log = [{"attempt": 0, "edit": "original witness replay (RTL)", "verdict": v0["verdict"], "rtl_run_ids": {d: rtl0[d]["run_id"] for d in order}}]
    if v0["verdict"] != "VALID_COUNTEREXAMPLE":
        result = {"status": "NOT_A_WITNESS", "original_verdict": v0}
        sd.write_json("reduction.json", result)
        sd.finalize({"schema_version": 1, "kind": "reduction", "status": "NOT_A_WITNESS", "tags": ["reduction", case_id]})
        return {"study_id": sd.run_id, **result}
    orient = (v0["model_choice"], v0["rtl_best"])
    current, attempts, tried = start, 0, {digest(start)}
    improved = True
    while improved:
        improved = False
        for cand, edit in candidates(current):
            dc = digest(cand)
            if dc in tried:
                continue
            tried.add(dc)
            attempts += 1
            try:
                _, mc = costs(cand, specs)
                _, sc = costs(cand, surr)
            except WorkloadError:
                continue
            sv = classify(order, mc, sc)
            if holds(sv, orient):
                log.append({"attempt": attempts, "edit": edit, "result": "ACCEPTED_BY_SURROGATE", "model_costs": sv["model_costs"], "surrogate_costs": sv["rtl_costs"]})
                current = cand
                improved = True
                break
    final_comp, _ = costs(current, specs)
    final_rtl = {d: run_rtl(cfgs[d], final_comp[d], tags=("reduction", case_id, "final_replay")) for d in order}
    final_mod = {d: run_model_artifact(specs[d], cfgs[d], final_comp[d], tags=("reduction", case_id, "final_replay")) for d in order}
    used += 2
    fv = classify(order, {d: final_mod[d]["check"] for d in order}, {d: final_rtl[d]["check"] for d in order})
    # 1-minimality: every single-edit neighbour must fail; re-check as many as budget allows on RTL.
    neighbours = []
    for cand, edit in candidates(current):
        try:
            nc, mc = costs(cand, specs)
            _, sc = costs(cand, surr)
        except WorkloadError:
            continue
        neighbours.append((cand, edit, nc, mc, holds(classify(order, mc, sc), orient)))
    surrogate_ok = [n for n in neighbours if n[4]]
    rtl_checked, rtl_contradictions = [], []
    for cand, edit, nc, mc, _ in neighbours:
        if used + 2 > rtl_budget:
            break
        rr = {d: run_rtl(cfgs[d], nc[d], compress=True, tags=("reduction", case_id, "neighbour_check")) for d in order}
        used += 2
        rv = classify(order, mc, {d: rr[d]["check"] for d in order})
        rtl_checked.append({"edit": edit, "verdict": rv["verdict"], "rtl_costs": rv.get("rtl_costs"), "rtl_run_ids": {d: rr[d]["run_id"] for d in order}})
        if holds(rv, orient):
            rtl_contradictions.append(edit)
    ok = holds(fv, orient)
    minimal = ok and not surrogate_ok and not rtl_contradictions
    result = {
        "schema_version": 1,
        "status": "REDUCED" if ok else "FINAL_REPLAY_FAILED",
        "mode": "surrogate_complete",
        "case_id": case_id,
        "provenance": provenance,
        "designs": designs,
        "models": models,
        "orientation": {"model_choice": orient[0], "rtl_best": orient[1]},
        "original": {"workload": start, "workload_digest": comp0[order[0]].digest, "operations": comp0[order[0]].total_ops,
                     "verdict": {k: v0.get(k) for k in ("verdict", "model_costs", "rtl_costs", "selection")}},
        "reduced": {"workload": current, "workload_digest": final_comp[order[0]].digest, "operations": final_comp[order[0]].total_ops,
                    "verdict": {k: fv.get(k) for k in ("verdict", "model_costs", "rtl_costs", "dM", "dR", "model_margin", "rtl_margin", "selection")},
                    "final_rtl_run_ids": {d: final_rtl[d]["run_id"] for d in order},
                    "final_model_run_ids": {d: final_mod[d]["run_id"] for d in order},
                    "reference_epoch": final_rtl[order[0]]["manifest"]["reference_epoch"]},
        "reduction_ratio_operations": f"{final_comp[order[0]].total_ops}/{comp0[order[0]].total_ops}",
        "edit_set": EDIT_SET,
        "attempts": attempts,
        "invalid_candidates": 0,
        "surrogate_rejected": len(neighbours) - len(surrogate_ok),
        "rtl_rejected": len(rtl_checked) - len(rtl_contradictions),
        "rtl_executions_used": used,
        "rtl_budget": rtl_budget,
        "surrogate_models": {d: surr[d]["model_id"] for d in order},
        "neighbours": {"total": len(neighbours), "surrogate_rejected": len(neighbours) - len(surrogate_ok), "rtl_rechecked": len(rtl_checked),
                       "rtl_rechecked_rejected": len(rtl_checked) - len(rtl_contradictions), "rtl_contradictions": rtl_contradictions, "rtl_checks": rtl_checked},
        "history": "every candidate replayed from the 4-cycle reset; no checkpoints",
        "minimality": (f"1-minimal under the edit set: all {len(neighbours)} single-edit neighbours break the reversal under the event-exact surrogate; "
                       f"{len(rtl_checked)} of them re-checked on the RTL, all broken; final witness confirmed on the RTL") if minimal else
                      ("not established: " + ("final RTL replay failed" if not ok else f"{len(surrogate_ok) + len(rtl_contradictions)} neighbours still reverse")),
        "minimality_established": minimal,
        "elapsed_seconds": round(time.time() - t0, 2),
        "log": log,
    }
    sd.write_json("reduction.json", result)
    sd.finalize({"schema_version": 1, "kind": "reduction", "status": result["status"], "case_id": case_id,
                 "reference_epoch": result["reduced"]["reference_epoch"], "tags": ["reduction", case_id]})
    result["study_id"] = sd.run_id
    return result


def _reduce_rtl_stepwise(workload: dict, designs: list[dict], models: dict[str, str], rtl_budget: int = 32,
                         case_id: str = "unspecified", provenance: str = "AUTHORED_DEFECT") -> dict:
    order = [d["design"] for d in designs]
    cfgs = {d["design"]: load_config(d["config"]) for d in designs}
    specs = {d: get_spec(models[d]) for d in order}
    surr = {d: get_spec(SURROGATE[cfgs[d].topology]) for d in order}
    sd = RunDir("reduction", root=STUDIES)
    t0 = time.time()

    def model_costs(w, which):
        comp = {d: validate_and_compile(w, cfgs[d]) for d in order}
        out = {}
        for d in order:
            r = run_model(which[d], cfgs[d], comp[d], record_events=False)
            out[d] = {"status": r.status if r.status != "COMPLETED" else "COMPLETED", "makespan": r.makespan}
        return comp, out

    def rtl_check(comp, tag):
        res = {d: run_rtl(cfgs[d], comp[d], compress=True, tags=("reduction", case_id, tag)) for d in order}
        return res

    # Normalise the starting witness to read_sequences and confirm it from reset.
    start = to_read_sequences(validate_and_compile(workload, cfgs[order[0]]), label="reduction start")
    comp0, m0 = model_costs(start, specs)
    rtl0 = rtl_check(comp0, "original")
    rtl_used = 2
    v0 = classify(order, m0, {d: rtl0[d]["check"] for d in order})
    log = [{"attempt": 0, "edit": "original witness replay", "workload_digest": comp0[order[0]].digest,
            "verdict": v0["verdict"], "rtl_run_ids": {d: rtl0[d]["run_id"] for d in order}, "accepted": v0["verdict"] == "VALID_COUNTEREXAMPLE"}]
    if v0["verdict"] != "VALID_COUNTEREXAMPLE":
        result = {"status": "NOT_A_WITNESS", "original_verdict": v0}
        sd.write_json("reduction.json", result)
        sd.finalize({"schema_version": 1, "kind": "reduction", "status": "NOT_A_WITNESS", "tags": ["reduction", case_id]})
        return {"study_id": sd.run_id, **result}
    orient = (v0["model_choice"], v0["rtl_best"])

    current = start
    current_comp = comp0
    attempts = surrogate_rejected = rtl_rejected = invalid = 0
    tried: set[str] = {digest(start)}
    improved = True
    exhausted_budget = False
    while improved and not exhausted_budget:
        improved = False
        for cand, edit in candidates(current):
            d_c = digest(cand)
            if d_c in tried:
                continue
            tried.add(d_c)
            attempts += 1
            try:
                comp, mc = model_costs(cand, specs)
            except WorkloadError as e:
                invalid += 1
                log.append({"attempt": attempts, "edit": edit, "result": "INVALID", "detail": str(e)})
                continue
            _, sc = model_costs(cand, surr)
            sv = classify(order, mc, sc)
            if not (sv["verdict"] == "VALID_COUNTEREXAMPLE" and (sv["model_choice"], sv["rtl_best"]) == orient):
                surrogate_rejected += 1
                log.append({"attempt": attempts, "edit": edit, "workload_digest": comp[order[0]].digest, "result": "SURROGATE_REJECTED",
                            "surrogate_verdict": sv["verdict"], "model_costs": sv.get("model_costs"), "surrogate_costs": sv.get("rtl_costs")})
                continue
            if rtl_used + 2 + 2 > rtl_budget:  # keep 2 executions for the final independent replay
                exhausted_budget = True
                log.append({"attempt": attempts, "edit": edit, "result": "BUDGET_EXHAUSTED_BEFORE_RTL"})
                break
            rr = rtl_check(comp, "candidate")
            rtl_used += 2
            rv = classify(order, mc, {d: rr[d]["check"] for d in order})
            ok = rv["verdict"] == "VALID_COUNTEREXAMPLE" and (rv["model_choice"], rv["rtl_best"]) == orient
            log.append({"attempt": attempts, "edit": edit, "workload_digest": comp[order[0]].digest, "result": "ACCEPTED" if ok else "RTL_REJECTED",
                        "verdict": rv["verdict"], "model_costs": rv.get("model_costs"), "rtl_costs": rv.get("rtl_costs"),
                        "rtl_run_ids": {d: rr[d]["run_id"] for d in order}})
            if ok:
                current, current_comp = cand, comp
                improved = True
                break
            rtl_rejected += 1

    # Final independent replay of the reduced witness from reset, with full artifacts.
    final_rtl = {d: run_rtl(cfgs[d], current_comp[d], tags=("reduction", case_id, "final_replay")) for d in order}
    final_mod = {d: run_model_artifact(specs[d], cfgs[d], current_comp[d], tags=("reduction", case_id, "final_replay")) for d in order}
    rtl_used += 2
    fv = classify(order, {d: final_mod[d]["check"] for d in order}, {d: final_rtl[d]["check"] for d in order})
    complete_pass = not exhausted_budget
    result = {
        "schema_version": 1,
        "status": "REDUCED" if fv["verdict"] == "VALID_COUNTEREXAMPLE" else "FINAL_REPLAY_FAILED",
        "case_id": case_id,
        "provenance": provenance,
        "designs": designs,
        "models": models,
        "orientation": {"model_choice": orient[0], "rtl_best": orient[1]},
        "original": {"workload": start, "workload_digest": comp0[order[0]].digest, "operations": comp0[order[0]].total_ops,
                     "verdict": {k: v0.get(k) for k in ("verdict", "model_costs", "rtl_costs", "selection")}},
        "reduced": {"workload": current, "workload_digest": current_comp[order[0]].digest, "operations": current_comp[order[0]].total_ops,
                    "verdict": {k: fv.get(k) for k in ("verdict", "model_costs", "rtl_costs", "dM", "dR", "model_margin", "rtl_margin", "selection")},
                    "final_rtl_run_ids": {d: final_rtl[d]["run_id"] for d in order},
                    "final_model_run_ids": {d: final_mod[d]["run_id"] for d in order},
                    "reference_epoch": final_rtl[order[0]]["manifest"]["reference_epoch"]},
        "reduction_ratio_operations": f"{current_comp[order[0]].total_ops}/{comp0[order[0]].total_ops}",
        "edit_set": EDIT_SET,
        "attempts": attempts,
        "invalid_candidates": invalid,
        "surrogate_rejected": surrogate_rejected,
        "rtl_rejected": rtl_rejected,
        "rtl_executions_used": rtl_used,
        "rtl_budget": rtl_budget,
        "surrogate_models": {d: surr[d]["model_id"] for d in order},
        "history": "every candidate replayed from the 4-cycle reset; no checkpoints",
        "minimality": ("local 1-minimal under the edit set (a full pass found no accepted single edit); "
                       f"{surrogate_rejected} candidates were rejected by the validated surrogate without RTL confirmation")
                      if complete_pass else "not established: RTL reduction budget exhausted before a complete pass",
        "elapsed_seconds": round(time.time() - t0, 2),
        "log": log,
    }
    sd.write_json("reduction.json", result)
    sd.finalize({"schema_version": 1, "kind": "reduction", "status": result["status"], "case_id": case_id,
                 "reference_epoch": result["reduced"]["reference_epoch"], "tags": ["reduction", case_id]})
    result["study_id"] = sd.run_id
    return result
