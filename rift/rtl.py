"""RTL reference runner: Verilator executable + independent event check."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from rift.contracts.canonical import digest, file_digest, read_json
from rift.contracts.config import ArchConfig
from rift.contracts.workload import CompiledWorkload
from rift.evaluate.checker import check_events
from rift.paths import ROOT, rel
from rift.store import RunDir, compress_file, load_events
from rift import toolchain


def reference_identity(config: ArchConfig, build_manifest: dict) -> dict:
    lock = read_json(toolchain.SOURCES_LOCK)
    commits = {r["name"]: r["commit"] for r in lock["repositories"]}
    return {
        "rtl_commit": commits["cluster_interconnect"],
        "dependency_commit": commits["common_cells"],
        "wrapper_digest": file_digest(ROOT / "rtl_wrapper/rift_tcdm_top.sv"),
        "driver_digest": file_digest(ROOT / "oracle/main.cpp"),
        "memory_oracle_digest": digest(toolchain.MEMORY_ORACLE_SPEC),
        "sampling_convention": toolchain.SAMPLING_CONVENTION["id"],
        "config_digest": config.digest,
        "build_key_digest": build_manifest["build_key_digest"],
        "binary_sha256": build_manifest["binary_sha256"],
        "toolchain_lock_digest": file_digest(toolchain.TOOLCHAIN_LOCK),
        "assertion_register_digest": file_digest(toolchain.ASSERTION_REGISTER),
    }


def reference_epoch(identity: dict) -> str:
    """A reference epoch changes whenever anything reference-affecting changes."""
    keys = ("rtl_commit", "dependency_commit", "wrapper_digest", "driver_digest", "memory_oracle_digest", "sampling_convention", "toolchain_lock_digest")
    return "epoch-" + digest({k: identity[k] for k in keys})[7:19]


def run_rtl(
    config: ArchConfig,
    compiled: CompiledWorkload,
    *,
    stalls: tuple = (),
    inject: str | None = None,
    sv_inject: int = 0,
    timeout: int = 4096,
    fst: bool = False,
    compress: bool = False,
    tags: tuple = (),
    extra_manifest: dict | None = None,
) -> dict:
    bm = toolchain.build(config, trace=fst)
    binary = ROOT / bm["binary"]
    rd = RunDir("rtl")
    rd.write_json("workload.json", compiled.workload)
    wl_txt = rd.write_text("compiled_workload.txt", compiled.to_text())
    events_p = rd.file("events.jsonl")
    summary_p = rd.file("runner_summary.json")
    cmd = [str(binary), "--workload", str(wl_txt), "--events", str(events_p), "--summary", str(summary_p),
           "--run-id", rd.run_id, "--timeout", str(timeout)]
    for s in stalls:
        cmd += ["--stall", f"{s[0]}:{s[1]}:{s[2]}"]
    if inject:
        cmd += ["--inject", inject]
    if sv_inject:
        cmd += ["--sv-inject", str(sv_inject)]
    if fst:
        cmd += ["--fst", str(rd.file("trace.fst"))]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    wall = time.perf_counter() - t0
    if proc.stdout:
        rd.write_text("stdout.txt", proc.stdout)
    if proc.stderr:
        rd.write_text("stderr.txt", proc.stderr)

    runner_summary = read_json(summary_p) if summary_p.exists() else None
    if proc.returncode == 3:
        check = {"status": "INVALID_WORKLOAD", "functional_valid": False, "makespan": None, "detail": proc.stderr.strip()}
    elif proc.returncode != 0 or runner_summary is None or not events_p.exists():
        check = {"status": "TOOL_ERROR", "functional_valid": False, "makespan": None, "detail": f"exit {proc.returncode}: {proc.stderr.strip()[:500]}"}
    else:
        events = load_events(events_p)
        check = check_events(compiled, config, events, runner_summary, "rtl", timeout=timeout)
    rd.write_json("check.json", check)
    if compress and events_p.exists():
        compress_file(events_p)

    identity = reference_identity(config, bm)
    manifest = {
        "schema_version": 1,
        "kind": "rtl",
        "runner": "verilator_rtl",
        "observation_role": "RTL_REFERENCE_OBSERVATION",
        "evidence_basis": "EXECUTED_ARTIFACT",
        "status": check["status"],
        "makespan": check.get("makespan"),
        "config_id": config.config_id,
        "config": config.raw,
        "workload_digest": compiled.digest,
        "workload_label": compiled.workload.get("label"),
        "reference": identity,
        "reference_epoch": reference_epoch(identity),
        "reset_cycles": 4,
        "metric_id": "inclusive_cycle_makespan_v1",
        "timeout_cycles": timeout,
        "stalls": [list(s) for s in stalls],
        "cpp_inject": inject,
        "sv_inject_mask": sv_inject,
        "fst_dumped": fst,
        "command": [rel(Path(c)) if c.startswith(str(ROOT)) else c for c in cmd],
        "exit_code": proc.returncode,
        "wall_seconds": round(wall, 6),
        "build": {"cache_hit": bm.get("cache_hit"), "build_key_digest": bm["build_key_digest"], "warnings": bm.get("warning_lines", [])},
        "tags": list(tags),
    }
    if extra_manifest:
        manifest.update(extra_manifest)
    manifest = rd.finalize(manifest)
    return {"run_id": rd.run_id, "path": rd.path, "manifest": manifest, "check": check, "runner_summary": runner_summary}
