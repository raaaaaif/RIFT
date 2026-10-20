"""Decision map: the A/B decision measured over a two-knob workload family.

Each cell of the frozen grid in experiments/maps/ is one workload from
`decision_map_cell`. The exact crossbar model, the audited bank-only butterfly
model and the repaired butterfly model predict it first; then both designs are
executed on the RTL. The independent evaluator classifies the audited and the
repaired model pairs with the same margin and tie policy as every comparison.
"""

from __future__ import annotations

from pathlib import Path

from rift.contracts.canonical import digest, read_json
from rift.contracts.config import load_config
from rift.contracts.workload import validate_and_compile
from rift.evaluate.compare import classify
from rift.model.registry import get_spec, model_digest
from rift.paths import ROOT, RUNS, STUDIES, rel
from rift.search.study import Executor
from rift.store import RunDir
from rift.workloads.generators import decision_map_cell, nominal_features

MANIFEST = ROOT / "experiments" / "maps" / "decision_map_v1.json"
VERDICT_KEYS = ("verdict", "dM", "dR", "model_choice", "rtl_best", "selection", "model_margin", "rtl_margin")
MODELS = ("parent", "repaired")


def _run(rec: dict) -> dict:
    return {"run_id": rec["run_id"], "status": rec["status"], "makespan": rec["makespan"]}


def summarize(cells: list[dict], order: list[str]) -> dict:
    """Counts the viewer shows; recomputable from the cells alone."""
    a, b = order
    out: dict = {"cells": len(cells), "hardware": {"A_faster": 0, "B_faster": 0, "within_margin": 0}}
    for c in cells:
        v = c["verdict"]["parent"]
        if v.get("rtl_margin", {}).get("met"):
            out["hardware"]["A_faster" if v["dR"] < 0 else "B_faster"] += 1
        else:
            out["hardware"]["within_margin"] += 1
    for m in MODELS:
        vs = [c["verdict"][m] for c in cells]
        rev = [v for v in vs if v["verdict"] == "VALID_COUNTEREXAMPLE"]
        undecided = [v for v in vs if v["verdict"] == "TIE_OR_SMALL_MARGIN" and v.get("rtl_margin", {}).get("met")]
        counts: dict[str, int] = {}
        for v in vs:
            counts[v["verdict"]] = counts.get(v["verdict"], 0) + 1
        out[m] = {
            "verdicts": counts,
            "strict_reversals": len(rev),
            "model_undecided_hardware_decisive": len(undecided),
            "extra_cycles_strict": sum(v["selection"]["extra_cycles"] for v in rev),
            "max_extra_cycles_strict": max((v["selection"]["extra_cycles"] for v in rev), default=0),
            "max_regret_strict": max((v["selection"]["regret"]["decimal"] for v in rev), default=0.0),
            "max_abs_error_B": max((abs(c["model"][m]["makespan"] - c["rtl"][b]["makespan"]) for c in cells
                                    if c["model"][m]["makespan"] is not None and c["rtl"][b]["makespan"] is not None), default=None),
        }
    rev_cells = [c for c in cells if c["verdict"]["parent"]["verdict"] == "VALID_COUNTEREXAMPLE"]
    above = [c for c in rev_cells if c["features"]["route_sharing"][0] * c["features"]["crossbar_collisions"][1]
             > c["features"]["crossbar_collisions"][0] * c["features"]["route_sharing"][1]]
    out["prediction_checks"] = {
        "parent_B_costs": sorted({c["model"]["parent"]["makespan"] for c in cells if c["model"]["parent"]["makespan"] is not None}),
        "parent_reversals_where_sharing_exceeds_collisions": [len(above), len(rev_cells)],
    }
    return out


def family_differences(compiled, num_banks: int) -> list[str]:
    """Ways a workload falls outside the map's family (equal back-to-back streams, distinct butterfly banks per slot)."""
    per = compiled.per_master
    out = []
    if len({len(p) for p in per}) > 1:
        out.append("streams of unequal length")
    deps = sum(1 for o in compiled.operations() if o.release != "after_accept")
    if deps:
        out.append(f"{deps} response-dependent releases")
    gaps = sum(1 for o in compiled.operations() if o.gap)
    if gaps:
        out.append(f"{gaps} release gaps")
    clash = sum(1 for t in range(max(len(p) for p in per))
                if len(b := [p[t].byte_address // 4 % num_banks for p in per if t < len(p)]) != len(set(b)))
    if clash:
        out.append(f"{clash} slots with a butterfly bank conflict")
    return out


def landmark(name: str, case_id: str, comparison_run_id: str) -> dict:
    cmp = read_json(RUNS / comparison_run_id / "comparison.json")
    w = read_json(RUNS / comparison_run_id / "workload.json")
    cfg = load_config(cmp["designs"]["B"]["config_id"])
    comp = validate_and_compile(w, cfg)
    f = nominal_features(comp)
    diff = family_differences(comp, cfg.num_out)
    return {"name": name, "case_id": case_id, "comparison_run_id": comparison_run_id, "features": f,
            "in_family": not diff, "outside_family_because": diff,
            "verdict": cmp["verdict"], "rtl_costs": cmp.get("rtl_costs"), "model_costs": cmp.get("model_costs"),
            "models": {d: cmp["models"][d]["model_id"] if isinstance(cmp["models"][d], dict) else cmp["models"][d] for d in cmp["models"]}}


def run_decision_map(repaired_model_id: str, landmarks: list[tuple[str, str, str]] = (), manifest_path: Path = MANIFEST, log=None) -> dict:
    man = read_json(manifest_path)
    order = [d["design"] for d in man["designs"]]
    a, b = order
    cfgs = {d["design"]: load_config(d["config"]) for d in man["designs"]}
    specs = {"A": get_spec(man["models"]["A"]), "parent": get_spec(man["models"]["B_parent"]), "repaired": get_spec(repaired_model_id)}
    gen, xs, ys = man["generator"], man["axes"]["x"]["levels"], man["axes"]["y"]["levels"]
    ex = Executor(cfgs, tags=("map", man["map_id"]))
    sd = RunDir("map", root=STUDIES)
    sd.write_json("map_manifest.json", man)
    cells = []
    for i, share in enumerate(xs):
        for j, collide in enumerate(ys):
            seed = gen["seed_base"] + 17 * i + j
            w = decision_map_cell(share, collide, seed, gen["reads_per_initiator"])
            comp = {d: validate_and_compile(w, cfgs[d]) for d in order}
            # Predictions are recorded before the reference pair executes.
            model = {"A": ex.model(specs["A"], a, comp[a])[0], "parent": ex.model(specs["parent"], b, comp[b])[0],
                     "repaired": ex.model(specs["repaired"], b, comp[b])[0]}
            rtl = {d: ex.rtl(d, comp[d])[0] for d in order}
            verdict = {m: {k: v for k, v in classify(order, {a: model["A"], b: model[m]}, rtl).items() if k in VERDICT_KEYS} for m in MODELS}
            cells.append({"i": i, "j": j, "seed": seed, "workload_digest": comp[b].digest, "features": nominal_features(comp[b]),
                          "rtl": {d: _run(rtl[d]) for d in order}, "model": {k: _run(v) for k, v in model.items()},
                          "reference_epoch": rtl[a].get("reference_epoch"), "verdict": verdict})
        if log:
            log(f"    column {i + 1}/{len(xs)}")
    out = {
        "schema_version": 1, "map_id": man["map_id"], "map_run_id": sd.run_id, "manifest_digest": digest(man),
        "order": order, "configs": {d: cfgs[d].config_id for d in order},
        "models": {"A": {"model_id": specs["A"]["model_id"], "model_digest": model_digest(specs["A"])},
                   **{m: {"model_id": specs[m]["model_id"], "model_digest": model_digest(specs[m])} for m in MODELS}},
        "grid": {"x": xs, "y": ys, "x_denominator": man["axes"]["x"]["denominator"], "y_denominator": man["axes"]["y"]["denominator"]},
        "cells": cells,
        "landmarks": [landmark(*lm) for lm in landmarks],
        "executor": {"distinct_rtl_executions": ex.rtl_executed, "rtl_cache_hits": ex.rtl_cache_hits},
    }
    out["summary"] = summarize(cells, order)
    sd.write_json("map.json", out)
    sd.finalize({"schema_version": 1, "kind": "decision_map", "status": "COMPLETED", "map_id": man["map_id"], "tags": ["map"]})
    return {"map_study_id": sd.run_id, "path": rel(sd.path), "summary": out["summary"]}
