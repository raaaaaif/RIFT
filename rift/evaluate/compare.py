"""Pairwise decision verdicts and selection regret (exact integer arithmetic).

Strict ranking-reversal witness (handoff section 6):
  dM = M_A - M_B, dR = R_A - R_B, dM*dR < 0 and, independently in each domain,
  |d| >= max(2 cycles, 0.02 * min(cost_A, cost_B)).
The relative term is evaluated exactly: |d| >= 0.02*m  <=>  50*|d| >= m.
Selection uses argmin with the frozen tie policy "first design in the admitted
order". Regret = (R[chosen] - R[best]) / max(1, R[best]) stored as a fraction.
"""

from __future__ import annotations

from fractions import Fraction

RUN_FAILURE_PRECEDENCE = ["TOOL_ERROR", "TIMEOUT", "HARNESS_INVALID", "FUNCTIONAL_MISMATCH"]
TIE_POLICY = "argmin; ties resolved to the first design in the admitted order"
ABS_MARGIN = 2
REL_MARGIN = Fraction(1, 50)


def margin_met(d: int, a: int, b: int) -> bool:
    m = min(a, b)
    return abs(d) >= ABS_MARGIN and abs(d) * REL_MARGIN.denominator >= m * REL_MARGIN.numerator


def margin_value(a: int, b: int) -> dict:
    m = min(a, b)
    rel = Fraction(m) * REL_MARGIN
    thr = max(Fraction(ABS_MARGIN), rel)
    return {"absolute_cycles": ABS_MARGIN, "relative": "0.02", "min_cost": m, "relative_term": f"{rel.numerator}/{rel.denominator}", "threshold": f"{thr.numerator}/{thr.denominator}", "threshold_decimal": float(thr)}


def argmin(costs: dict[str, int], order: list[str]) -> str:
    best = order[0]
    for d in order[1:]:
        if costs[d] < costs[best]:
            best = d
    return best


def frac(f: Fraction) -> dict:
    return {"numerator": f.numerator, "denominator": f.denominator, "decimal": float(f)}


def regret(reference: dict[str, int], chosen: str, order: list[str]) -> dict:
    best = argmin(reference, order)
    r = Fraction(reference[chosen] - reference[best], max(1, reference[best]))
    return {"chosen": chosen, "reference_best": best, "extra_cycles": reference[chosen] - reference[best], "denominator_cycles": max(1, reference[best]), "regret": frac(r)}


def classify(
    order: list[str],
    model: dict[str, dict],
    rtl: dict[str, dict],
    workload_valid: bool = True,
) -> dict:
    """model/rtl map design id -> checker result (status, makespan)."""
    a, b = order
    out = {
        "schema_version": 1,
        "evaluator": "rift.evaluate.compare/v1",
        "admitted_order": order,
        "tie_policy": TIE_POLICY,
        "metric_id": "inclusive_cycle_makespan_v1",
        "direction": "lower_is_better",
        "model_status": {d: model[d]["status"] for d in order} if model else None,
        "rtl_status": {d: rtl[d]["status"] for d in order} if rtl else None,
    }
    if not workload_valid:
        out["verdict"] = "INVALID_WORKLOAD"
        return out
    rtl_statuses = [rtl[d]["status"] for d in order]
    for s in RUN_FAILURE_PRECEDENCE:
        if s in rtl_statuses:
            out["verdict"] = s
            out["blocking_reason"] = f"reference run status {s}; no comparative performance conclusion"
            return out
    if any(model[d]["status"] != "COMPLETED" for d in order):
        out["verdict"] = "MODEL_ERROR"
        out["blocking_reason"] = "fast-model execution invalid; a crashed or malformed model is never a performance win"
        return out
    M = {d: model[d]["makespan"] for d in order}
    R = {d: rtl[d]["makespan"] for d in order}
    dM, dR = M[a] - M[b], R[a] - R[b]
    mM, mR = margin_met(dM, M[a], M[b]), margin_met(dR, R[a], R[b])
    if mM and mR:
        verdict = "VALID_COUNTEREXAMPLE" if dM * dR < 0 else "VALID_NO_REVERSAL"
    else:
        verdict = "TIE_OR_SMALL_MARGIN"
    chosen = argmin(M, order)
    out.update({
        "verdict": verdict,
        "model_costs": M,
        "rtl_costs": R,
        "dM": dM,
        "dR": dR,
        "sign_product": dM * dR,
        "model_margin": {**margin_value(M[a], M[b]), "met": mM},
        "rtl_margin": {**margin_value(R[a], R[b]), "met": mR},
        "model_choice": chosen,
        "rtl_best": argmin(R, order),
        "selection": regret(R, chosen, order),
    })
    return out
