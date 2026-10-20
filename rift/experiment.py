"""Paired model/RTL comparison experiments.

The same logical workload object (identical digest) is executed independently
on each admitted configuration by the RTL runner and by the model under audit.
The independent evaluator classifies the pair. Supplied calibration programs
carry zero discovery credit.
"""

from __future__ import annotations

from pathlib import Path

from rift.contracts.canonical import digest, read_json
from rift.contracts.config import load_config
from rift.contracts.workload import WorkloadError, validate_and_compile
from rift.evaluate.compare import classify
from rift.model.registry import get_spec, model_digest
from rift.modelrun import run_model_artifact
from rift.paths import ROOT, STUDIES, rel
from rift.rtl import run_rtl
from rift.store import RunDir


def _load_workload(entry: dict) -> dict:
    if "workload" in entry:
        return entry["workload"]
    return read_json(ROOT / entry["path"])


def compare_workload(workload: dict, designs: list[dict], models: dict[str, str], *, provenance: str, scope: str,
                     discovery_credit: int = 0, timeout: int = 4096, compress: bool = False, tags: tuple = (),
                     extra: dict | None = None, rtl_options: dict | None = None) -> dict:
    """Run one workload on every admitted design with both runners and classify."""
    order = [d["design"] for d in designs]
    cfgs = {d["design"]: load_config(d["config"]) for d in designs}
    try:
        compiled = {d: validate_and_compile(workload, cfgs[d]) for d in order}
    except WorkloadError as e:
        rd = RunDir("comparison")
        verdict = {"verdict": "INVALID_WORKLOAD", "detail": str(e), "admitted_order": order}
        rd.write_json("comparison.json", verdict)
        rd.finalize({"schema_version": 1, "kind": "comparison", "status": "INVALID_WORKLOAD", "tags": list(tags)})
        return {"run_id": rd.run_id, "verdict": verdict}
    wdig = compiled[order[0]].digest
    rtl, mod = {}, {}
    for d in order:
        rtl[d] = run_rtl(cfgs[d], compiled[d], compress=compress, timeout=timeout, tags=tags, **((rtl_options or {}).get(d, {})))
        mod[d] = run_model_artifact(get_spec(models[d]), cfgs[d], compiled[d], compress=compress, timeout=timeout, tags=tags)
    verdict = classify(order, {d: mod[d]["check"] for d in order}, {d: rtl[d]["check"] for d in order})
    verdict.update({
        "workload_digest": wdig,
        "workload_label": workload.get("label"),
        "designs": {d: {"config_id": cfgs[d].config_id, "config_digest": cfgs[d].digest,
                        "descriptive_name": cfgs[d].raw.get("descriptive_name")} for d in order},
        "models": {d: {"model_id": models[d], "model_digest": mod[d]["manifest"]["model_digest"],
                       "contract": mod[d]["manifest"]["approximation_contract"]} for d in order},
        "rtl_run_ids": {d: rtl[d]["run_id"] for d in order},
        "model_run_ids": {d: mod[d]["run_id"] for d in order},
        "reference_epoch": rtl[order[0]]["manifest"]["reference_epoch"],
        "provenance": provenance,
        "scope": scope,
        "discovery_credit": discovery_credit,
        "rtl_wall_seconds": {d: rtl[d]["manifest"]["wall_seconds"] for d in order},
        "model_elapsed_seconds": {d: mod[d]["manifest"].get("elapsed_seconds") for d in order},
    })
    if extra:
        verdict.update(extra)
    epochs = {rtl[d]["manifest"]["reference_epoch"] for d in order}
    if len(epochs) != 1:
        verdict["verdict"] = "HARNESS_INVALID"
        verdict["blocking_reason"] = "reference runs belong to different epochs"
    rd = RunDir("comparison")
    rd.write_json("workload.json", workload)
    rd.write_json("comparison.json", verdict)
    rd.finalize({"schema_version": 1, "kind": "comparison", "status": verdict["verdict"], "workload_digest": wdig,
                 "reference_epoch": verdict["reference_epoch"], "provenance": provenance, "scope": scope,
                 "observation_role": "INDEPENDENT_EVALUATOR_RESULT", "evidence_basis": "EXECUTED_ARTIFACT",
                 "tags": list(tags)})
    verdict["comparison_run_id"] = rd.run_id
    return {"run_id": rd.run_id, "verdict": verdict}


def run_comparison_experiment(path: Path) -> dict:
    exp = read_json(path)
    if exp.get("kind") != "comparison":
        raise ValueError("experiment kind must be 'comparison'")
    designs = exp["admitted_designs"]
    models = exp["models"]
    for d in designs:
        spec = get_spec(models[d["design"]])
        if load_config(d["config"]).topology not in spec["applies_to"]:
            raise ValueError(f"model {spec['model_id']} does not apply to {d['config']}")
    results = []
    for entry in exp["workloads"]:
        w = _load_workload(entry)
        r = compare_workload(w, designs, models, provenance=entry.get("provenance", "SUPPLIED_CALIBRATION"),
                             scope=entry.get("scope", "INSTRUMENT_TEST"), discovery_credit=entry.get("discovery_credit", 0),
                             timeout=exp.get("timeout_cycles", 4096), tags=tuple(exp.get("tags", [])) + (exp["experiment_id"],),
                             extra={"workload_id": entry.get("id")})
        results.append(r["verdict"])
    sd = RunDir("compare", root=STUDIES)
    report = {
        "schema_version": 1,
        "experiment_id": exp["experiment_id"],
        "experiment_digest": digest(exp),
        "experiment_path": rel(path),
        "admitted_designs": designs,
        "models": {d: {"model_id": m, "model_digest": model_digest(get_spec(m))} for d, m in models.items()},
        "comparisons": results,
        "verdict_counts": _counts([r["verdict"] for r in results]),
    }
    sd.write_json("experiment.json", exp)
    sd.write_json("report.json", report)
    m = sd.finalize({"schema_version": 1, "kind": "compare_study", "status": "COMPLETED", "experiment_id": exp["experiment_id"],
                     "tags": list(exp.get("tags", []))})
    return {"study_id": sd.run_id, "path": rel(sd.path), "report": report}


def _counts(xs):
    out = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    return out
