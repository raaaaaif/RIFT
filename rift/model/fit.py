"""Deterministic parameter fitting for the fitted per-path penalty baseline.

Parameters are fitted only on a declared training basket (seeded random legal
workloads disjoint from every search and held-out seed range) executed on the
RTL reference. Coordinate descent over an integer grid minimizes mean absolute
makespan error. The resulting model file records its training evidence.
"""

from __future__ import annotations

import time

from rift.contracts.canonical import digest, write_json_replace
from rift.contracts.config import load_config
from rift.contracts.workload import validate_and_compile
from rift.model.engine import simulate
from rift.model.networks import FittedPenalty
from rift.model.registry import FITTED_DIR
from rift.rtl import run_rtl
from rift.workloads.generators import random_legal

TRAIN_SEEDS = range(7000, 7040)
GRID = list(range(-400, 1601, 100))


def _mae(cfg, compiled, targets, a, c) -> float:
    err = 0
    for comp, t in zip(compiled, targets):
        r = simulate(FittedPenalty(cfg.num_in, cfg.num_out, a, c), comp, record_events=False)
        err += abs((r.makespan if r.makespan is not None else 10 ** 6) - t)
    return err / len(compiled)


def fit_penalty_model(config_id: str = "bfly4_8x16", model_id: str = "fitted_penalty_bfly4_8x16_v1", sweeps: int = 3) -> dict:
    cfg = load_config(config_id)
    t0 = time.time()
    workloads = [random_legal(s, hot_words=(8 if s % 2 else None)) for s in TRAIN_SEEDS]
    compiled = [validate_and_compile(w, cfg) for w in workloads]
    runs = [run_rtl(cfg, c, compress=True, tags=("training", model_id)) for c in compiled]
    valid = [(c, r) for c, r in zip(compiled, runs) if r["check"]["status"] == "COMPLETED"]
    compiled = [c for c, _ in valid]
    targets = [r["check"]["makespan"] for _, r in valid]
    a = [0] * cfg.num_in
    c = [0] * cfg.num_out
    best = _mae(cfg, compiled, targets, a, c)
    history = [{"sweep": 0, "mae": best}]
    for sweep in range(1, sweeps + 1):
        for vec in (a, c):
            for i in range(len(vec)):
                keep = vec[i]
                for v in GRID:
                    vec[i] = v
                    e = _mae(cfg, compiled, targets, a, c)
                    if e < best - 1e-12:
                        best, keep = e, v
                vec[i] = keep
        history.append({"sweep": sweep, "mae": best})
    spec = {
        "family": "fitted_penalty",
        "params": {"init_milli": a, "bank_milli": c},
        "applies_to": [cfg.topology],
        "contract": {"promise": "BOUNDED_ERROR", "scope": f"training distribution only: random legal programs, {len(compiled)} workloads",
                     "declared_omissions": ["no structural model of internal routes; contention represented by fitted per-path penalties"],
                     "training_mae_cycles": f"{best:.4f}"},
        "provenance": "conventional black-box calibration baseline (bank-only arbitration + fitted per-path penalties)",
        "admissible_fast_model": True,
        "training_evidence": {
            "config_id": config_id,
            "seeds": [TRAIN_SEEDS.start, TRAIN_SEEDS.stop - 1],
            "workload_digests": [x.digest for x in compiled],
            "rtl_run_ids": [r["run_id"] for _, r in valid],
            "excluded_invalid_runs": [r["run_id"] for c_, r in zip(workloads, runs) if r["check"]["status"] != "COMPLETED"],
            "objective": "mean absolute makespan error (cycles)",
            "grid_milli": [GRID[0], GRID[-1], GRID[1] - GRID[0]],
            "history": [{"sweep": h["sweep"], "mae": f"{h['mae']:.4f}"} for h in history],
            "fit_seconds": round(time.time() - t0, 2),
        },
    }
    spec["spec_digest"] = digest({k: v for k, v in spec.items() if k != "spec_digest"}, strict=False)
    write_json_replace(FITTED_DIR / f"{model_id}.json", spec)
    return spec
