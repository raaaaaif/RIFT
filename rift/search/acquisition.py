"""Decision-directed and error-directed acquisition scores (report section 5).

score(x) = [D * loss + lambda * info + mu * novelty] / cost

computed only from information available before the proposed RTL run:
K permitted model variants evaluated on the candidate pair, a static workload
signature, and historical paired-RTL runtime. These are heuristics; correlated
variants are not a calibrated posterior.
"""

from __future__ import annotations

import math
import statistics

from rift.contracts.config import ArchConfig
from rift.contracts.workload import CompiledWorkload
from rift.evaluate.compare import margin_met
from rift.model.engine import simulate
from rift.model.registry import build_network, get_spec

LAMBDA = 0.2
MU = 0.1
COST_FLOOR = 0.005


def variant_specs(case_models: dict[str, str], fitted_id: str | None) -> list[tuple[dict, dict]]:
    """Permitted model variants: the audited model plus a generic structural hypothesis library."""
    A, B = case_models["A"], case_models["B"]

    def sl(links):
        return {"model_id": f"hyp_shared_link_{links}", "family": "shared_link", "params": {"links": links},
                "applies_to": ["BFLY4", "BFLY2"], "contract": {"promise": "HYPOTHESIS"}}

    variants = [
        (get_spec(A), get_spec(B)),
        (get_spec("lic_exact_v1"), get_spec("bank_only_v1")),
        (get_spec("lic_exact_v1"), sl([[2, 2]])),
        (get_spec("lic_exact_v1"), sl([[2, 1]])),
        (get_spec("lic_exact_v1"), sl([[4, 2]])),
        (get_spec("defect_lic_unfair_arb_v1"), get_spec(B)),
    ]
    if fitted_id:
        variants.append((get_spec(A), get_spec(fitted_id)))
    return variants


def predict(spec: dict, cfg: ArchConfig, compiled: CompiledWorkload) -> int | None:
    try:
        net = build_network(spec, cfg)
    except ValueError:
        return None
    r = simulate(net, compiled, resp_lat=spec.get("resp_lat", 1), record_events=False)
    return r.makespan


def ordering(a: int, b: int) -> int:
    if not margin_met(a - b, a, b):
        return 0
    return -1 if a < b else 1


def signature(compiled_a: CompiledWorkload, cfg_b: ArchConfig) -> tuple:
    """Static signature: bank-collision histogram, internal-route collision class, phase count, dependency bin."""
    first = [ops[0].word if ops else None for ops in compiled_a.per_master]
    banks = {}
    for w in first:
        if w is not None:
            banks[w % cfg_b.num_out] = banks.get(w % cfg_b.num_out, 0) + 1
    hist = tuple(sorted(banks.values(), reverse=True))
    links = {}
    for m, w in enumerate(first):
        if w is not None:
            key = (m // 2, (w % cfg_b.num_out) >> 2)
            links[key] = links.get(key, 0) + 1
    route_class = min(3, sum(1 for v in links.values() if v > 1))
    phases = max((sum(1 for i in range(1, len(ops)) if ops[i].word != ops[i - 1].word) + 1) if ops else 0
                 for ops in compiled_a.per_master)
    total = compiled_a.total_ops
    dep = sum(1 for op in compiled_a.operations() if op.release == "after_response")
    dep_bin = min(3, (4 * dep) // max(1, total))
    return (hist, route_class, min(phases, 4), dep_bin)


def score_candidate(variants, cfg_a, cfg_b, comp_a, comp_b, seen_signatures: dict, cost_history: list[float]) -> dict:
    preds = []
    for va, vb in variants:
        pa, pb = predict(va, cfg_a, comp_a), predict(vb, cfg_b, comp_b)
        preds.append((pa, pb))
    ca, cb = preds[0]
    out = {"audited_prediction": {"A": ca, "B": cb}}
    if ca is None or cb is None:
        out.update(score=0.0, decision_score=0.0, error_score=0.0, valid=False)
        return out
    c = "A" if ca <= cb else "B"
    dissent, losses, cats = 0, [], [0, 0, 0]
    costs_all = []
    usable = [(pa, pb) for pa, pb in preds[1:] if pa is not None and pb is not None]
    for pa, pb in usable:
        choice = "A" if pa <= pb else "B"
        cats[ordering(pa, pb) + 1] += 1
        costs_all.append((pa, pb))
        if choice != c:
            dissent += 1
            best = min(pa, pb)
            hc = pa if c == "A" else pb
            losses.append(min(1.0, (hc - best) / max(1, best)))
    K = max(1, len(usable))
    D = dissent / K
    loss = statistics.mean(losses) if losses else 0.0
    n = sum(cats)
    info = -sum((x / n) * math.log(x / n) for x in cats if x) / math.log(3) if n else 0.0
    sig = signature(comp_a, cfg_b)
    novelty = 1.0 / (1 + seen_signatures.get(sig, 0))
    cost = max(COST_FLOOR, statistics.median(cost_history)) if cost_history else 0.02
    decision = (D * loss + LAMBDA * info + MU * novelty) / cost
    # error-directed proxy: ensemble spread of absolute predicted costs relative to the audited model
    spread = 0.0
    if costs_all:
        spread = statistics.mean(abs(pa - ca) / max(1, ca) + abs(pb - cb) / max(1, cb) for pa, pb in costs_all)
    error = (spread + MU * novelty) / cost
    out.update(valid=True, model_choice=c, disagreement=D, decision_loss_proxy=loss, information=info,
               novelty=novelty, signature=repr(sig), estimated_cost_seconds=cost, decision_score=decision, error_score=error,
               variant_predictions=[{"A": pa, "B": pb} for pa, pb in preds])
    return out
