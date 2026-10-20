"""Fast-model execution as an immutable artifact (its content is a prediction)."""

from __future__ import annotations

import json

from rift.contracts.config import ArchConfig
from rift.contracts.workload import CompiledWorkload
from rift.evaluate.checker import check_events
from rift.model.registry import model_digest, run_model
from rift.store import RunDir, compress_file


def run_model_artifact(spec: dict, config: ArchConfig, compiled: CompiledWorkload, *, compress: bool = False,
                       tags: tuple = (), timeout: int = 4096, extra_manifest: dict | None = None) -> dict:
    rd = RunDir("model")
    rd.write_json("workload.json", compiled.workload)
    try:
        r = run_model(spec, config, compiled, run_id=rd.run_id, timeout=timeout)
        error = None
    except Exception as e:  # a crashed model is MODEL_ERROR, never a performance win
        r, error = None, f"{type(e).__name__}: {e}"
    if r is not None:
        with open(rd.file("events.jsonl"), "x") as f:
            for e in r.events:
                f.write(json.dumps(e, separators=(",", ":")) + "\n")
        summary = {"schema_version": 1, "run_id": rd.run_id, "runner": "fast_model", "model_id": spec["model_id"],
                   "exit_status": r.status, "makespan": r.makespan, "accepted": r.accepted, "completed": r.completed,
                   "last_response_cycle": r.last_response_cycle, "elapsed_seconds": r.elapsed_seconds}
        rd.write_json("model_summary.json", summary)
        check = check_events(compiled, config, r.events, summary, "model", resp_lat=spec.get("resp_lat", 1), timeout=timeout)
        if r.status == "TIMEOUT":
            check["status"] = "TIMEOUT"
            check["functional_valid"] = False
            check["makespan"] = None
    else:
        summary = {"exit_status": "MODEL_ERROR", "error": error}
        rd.write_json("model_summary.json", summary)
        check = {"status": "MODEL_ERROR", "functional_valid": False, "makespan": None, "detail": error}
    rd.write_json("check.json", check)
    if compress and rd.file("events.jsonl").exists():
        compress_file(rd.file("events.jsonl"))
    manifest = {
        "schema_version": 1,
        "kind": "model",
        "runner": "fast_model",
        "observation_role": "MODEL_PREDICTION",
        "evidence_basis": "EXECUTED_ARTIFACT",
        "status": check["status"],
        "makespan": check.get("makespan"),
        "config_id": config.config_id,
        "config_digest": config.digest,
        "workload_digest": compiled.digest,
        "workload_label": compiled.workload.get("label"),
        "model_id": spec["model_id"],
        "model_digest": model_digest(spec),
        "model_spec": spec,
        "approximation_contract": spec.get("contract"),
        "metric_id": "inclusive_cycle_makespan_v1",
        "timeout_cycles": timeout,
        "elapsed_seconds": summary.get("elapsed_seconds"),
        "tags": list(tags),
    }
    if extra_manifest:
        manifest.update(extra_manifest)
    manifest = rd.finalize(manifest)
    return {"run_id": rd.run_id, "path": rd.path, "manifest": manifest, "check": check, "summary": summary}
