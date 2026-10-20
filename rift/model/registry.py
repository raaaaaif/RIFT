"""Fast-model registry with frozen approximation contracts.

A model specification is data: family, parameters, and an approximation
contract stating what it promises (EXACT_TIMING, BOUNDED_ERROR or
RANKING_PRESERVATION), its scope and its declared omissions. The model digest
covers the specification and the source files of the model package, so any
change to model code or parameters yields a new identity.
"""

from __future__ import annotations

import copy
from pathlib import Path

from rift.contracts.canonical import digest, file_digest, read_json
from rift.contracts.config import ArchConfig
from rift.model.engine import ModelRun, simulate
from rift.model.networks import Butterfly, Crossbar, FittedPenalty, SharedLinkCrossbar
from rift.paths import ROOT

MODEL_SOURCES = ["rift/model/engine.py", "rift/model/networks.py", "rift/model/arbiters.py"]
FITTED_DIR = ROOT / "models" / "fitted"
REPAIRED_DIR = ROOT / "models" / "candidates"

MODELS: dict[str, dict] = {
    "lic_exact_v1": {
        "family": "crossbar", "params": {"fair": True, "lock_in": True},
        "applies_to": ["LIC"],
        "contract": {"promise": "EXACT_TIMING", "scope": "LIC configurations, read-only per-initiator release programs, always-grant or declared bank stalls",
                     "declared_omissions": []},
        "provenance": "reviewed model of the pinned xbar/rr_arb_tree (FairArb=1, LockIn=1)",
        "admissible_fast_model": True,
    },
    "bank_only_v1": {
        "family": "crossbar", "params": {"fair": True, "lock_in": True},
        "applies_to": ["BFLY4", "BFLY2", "LIC"],
        "contract": {"promise": "RANKING_PRESERVATION", "scope": "claims bank conflicts dominate; read-only programs",
                     "declared_omissions": ["internal butterfly route contention", "LFSR-derived external priorities"]},
        "provenance": "handoff-specified explicitly lower-fidelity bank-only butterfly model (seeded omission)",
        "admissible_fast_model": True,
    },
    "bfly_topology_rr_v1": {
        "family": "butterfly", "params": {"prio_mode": "rr"},
        "applies_to": ["BFLY4", "BFLY2"],
        "contract": {"promise": "BOUNDED_ERROR", "scope": "butterfly configurations without a radix-2 fix-up stage; read-only programs",
                     "declared_omissions": ["LFSR+PRESENT cipher priorities replaced by per-output round-robin (permitted approximation)"],
                     "permitted_approximation": "arbitration winner choice may differ from RTL; acceptance capacity per stage is modelled"},
        "provenance": "reviewed topology-aware event model (bfly_net wiring, stage contention)",
        "admissible_fast_model": True,
    },
    "bfly_lfsr_transliteration_v1": {
        "family": "butterfly", "params": {"prio_mode": "lfsr"},
        "applies_to": ["BFLY4", "BFLY2"],
        "contract": {"promise": "EXACT_TIMING", "scope": "diagnostic only; transliterates the pinned LFSR/cipher priority path",
                     "declared_omissions": []},
        "provenance": "diagnostic RTL transliteration used to validate the source reading; NOT an admissible fast model (copies RTL state)",
        "admissible_fast_model": False,
    },
    # ---- authored defects (labelled AUTHORED throughout) ----
    "defect_bfly_lfsr_every_cycle_v1": {
        "family": "butterfly", "params": {"prio_mode": "lfsr", "lfsr_every_cycle": True},
        "applies_to": ["BFLY4", "BFLY2"],
        "contract": {"promise": "EXACT_TIMING", "scope": "authored defect: LFSR advances on every clock instead of on accepted bank requests", "declared_omissions": []},
        "provenance": "AUTHORED_DEFECT (wrong arbitration-state advance)", "admissible_fast_model": True,
    },
    "defect_bfly_no_cipher_reg_v1": {
        "family": "butterfly", "params": {"prio_mode": "lfsr", "lfsr_no_cipher_reg": True},
        "applies_to": ["BFLY4", "BFLY2"],
        "contract": {"promise": "EXACT_TIMING", "scope": "authored defect: uses the cipher of the current LFSR state with no output register", "declared_omissions": []},
        "provenance": "AUTHORED_DEFECT (wrong priority update phase)", "admissible_fast_model": True,
    },
    "defect_bfly_bank_mod8_v1": {
        "family": "butterfly", "params": {"prio_mode": "rr", "bank_modulus": 8},
        "applies_to": ["BFLY4"],
        "contract": {"promise": "BOUNDED_ERROR", "scope": "authored defect: bank mapping width uses q mod 8 instead of q mod 16", "declared_omissions": []},
        "provenance": "AUTHORED_DEFECT (wrong mapping width)", "admissible_fast_model": True,
    },
    "defect_lic_unfair_arb_v1": {
        "family": "crossbar", "params": {"fair": False, "lock_in": True},
        "applies_to": ["LIC"],
        "contract": {"promise": "EXACT_TIMING", "scope": "authored defect: priority advances by +1 (FairArb=0) instead of jumping to the next requester", "declared_omissions": []},
        "provenance": "AUTHORED_DEFECT (wrong arbitration-state advance)", "admissible_fast_model": True,
    },
    "defect_bfly_resp_lat2_v1": {
        "family": "butterfly", "params": {"prio_mode": "rr"}, "resp_lat": 2,
        "applies_to": ["BFLY4", "BFLY2"],
        "contract": {"promise": "BOUNDED_ERROR", "scope": "authored defect: response latency off by one (2 instead of 1)", "declared_omissions": []},
        "provenance": "AUTHORED_DEFECT (response-latency off-by-one)", "admissible_fast_model": True,
    },
}


def source_digest() -> str:
    return digest({p: file_digest(ROOT / p) for p in MODEL_SOURCES})


def get_spec(model_id: str) -> dict:
    if model_id in MODELS:
        spec = copy.deepcopy(MODELS[model_id])
    else:
        for d in (FITTED_DIR, REPAIRED_DIR):
            p = d / f"{model_id}.json"
            if p.exists():
                spec = read_json(p)
                break
        else:
            raise KeyError(f"unknown model {model_id}")
    spec["model_id"] = model_id
    return spec


def model_digest(spec: dict) -> str:
    body = {k: v for k, v in spec.items() if k not in ("model_digest",)}
    return digest({"spec": body, "sources": source_digest()}, strict=False)


def build_network(spec: dict, config: ArchConfig):
    fam, p = spec["family"], spec.get("params", {})
    if config.topology not in spec.get("applies_to", []):
        raise ValueError(f"model {spec['model_id']} does not apply to topology {config.topology}")
    ni, no = config.num_in, config.num_out
    if fam == "crossbar":
        return Crossbar(ni, no, p.get("fair", True), p.get("lock_in", True), p.get("bank_modulus"))
    if fam == "butterfly":
        radix = {"BFLY4": 4, "BFLY2": 2}[config.topology]
        return Butterfly(ni, no, radix, p.get("prio_mode", "rr"), p.get("lfsr_every_cycle", False),
                         p.get("lfsr_no_cipher_reg", False), p.get("bank_modulus"))
    if fam == "fitted_penalty":
        return FittedPenalty(ni, no, p["init_milli"], p["bank_milli"])
    if fam == "shared_link":
        return SharedLinkCrossbar(ni, no, p["links"], True, False)
    raise ValueError(f"unknown model family {fam}")


def run_model(spec: dict, config: ArchConfig, compiled, *, run_id="model", record_events=True, timeout=4096) -> ModelRun:
    net = build_network(spec, config)
    return simulate(net, compiled, run_id=run_id, resp_lat=spec.get("resp_lat", 1), timeout=timeout, record_events=record_events)
