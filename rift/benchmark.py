"""Model-versus-Verilator runtime on the same hardware and workload basket.

Both sides execute warm (already built / already imported), emit the full
boundary event stream and a summary, and the harness parses both. FST dumping
is disabled (production binaries are built without trace support). Two modes:

* per_invocation: the RTL binary is spawned once per workload (how the search
  loop calls it); the model is called once per workload in-process.
* batched: one RTL process executes every workload from a fresh model instance;
  the model executes every workload in one loop.

Model events are additionally serialized to JSONL and parsed back so that
I/O is charged on both sides. Cold Verilator compilation is reported separately
from the build manifests.
"""

from __future__ import annotations

import json
import platform
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

from rift import toolchain
from rift.contracts.config import load_config
from rift.contracts.workload import validate_and_compile
from rift.model.registry import get_spec, model_digest, run_model
from rift.paths import ROOT
from rift.store import load_events
from rift.workloads.generators import random_legal

TARGET_SPEEDUP = 5.0


def basket(n_random: int = 37, seed0: int = 9000) -> list[dict]:
    ws = [json.load(open(ROOT / f"experiments/workloads/{x}.json")) for x in "LBM"]
    ws += [random_legal(seed0 + i, hot_words=(8 if i % 2 else None)) for i in range(n_random)]
    return ws


def _rtl_per_invocation(binary: Path, files: list[Path], tmp: Path) -> float:
    t0 = time.perf_counter()
    for i, wf in enumerate(files):
        ev, sm = tmp / f"e{i}.jsonl", tmp / f"s{i}.json"
        subprocess.run([str(binary), "--workload", str(wf), "--events", str(ev), "--summary", str(sm)], check=True,
                       capture_output=True)
        json.load(open(sm))
        load_events(ev)
    return time.perf_counter() - t0


def _rtl_batched(binary: Path, files: list[Path], tmp: Path, events: bool = True) -> float:
    lst = tmp / "batch.txt"
    lst.write_text("".join(f"{wf} {tmp / f'bs{i}.json'} {tmp / f'be{i}.jsonl' if events else '-'}\n" for i, wf in enumerate(files)))
    t0 = time.perf_counter()
    subprocess.run([str(binary), "--batch", str(lst)], check=True, capture_output=True)
    for i in range(len(files)):
        json.load(open(tmp / f"bs{i}.json"))
        if events:
            load_events(tmp / f"be{i}.jsonl")
    return time.perf_counter() - t0


def _model_cost_only(spec, cfg, compiled_list) -> float:
    t0 = time.perf_counter()
    for c in compiled_list:
        run_model(spec, cfg, c, record_events=False)
    return time.perf_counter() - t0


def _model(spec, cfg, compiled_list, tmp: Path, io: bool) -> float:
    t0 = time.perf_counter()
    for i, c in enumerate(compiled_list):
        r = run_model(spec, cfg, c, run_id=f"bench-{i}")
        summary = {"makespan": r.makespan, "accepted": r.accepted, "completed": r.completed, "exit_status": r.status}
        if io:
            p = tmp / f"m{i}.jsonl"
            with open(p, "w") as f:
                for e in r.events:
                    f.write(json.dumps(e, separators=(",", ":")) + "\n")
            (tmp / f"ms{i}.json").write_text(json.dumps(summary))
            load_events(p)
            json.load(open(tmp / f"ms{i}.json"))
    return time.perf_counter() - t0


def _compiled(spec, cfg, compiled_list, tmp: Path, events: bool) -> float:
    from rift.model import compiled as cm
    exe = cm.build()
    lines = []
    for i, c in enumerate(compiled_list):
        lines.append(f"{tmp / f'w{i}.txt'} {tmp / f'cs{i}.json'} {tmp / f'ce{i}.jsonl' if events else '-'}")
    (tmp / "cbatch.txt").write_text("\n".join(lines) + "\n")
    t0 = time.perf_counter()
    subprocess.run([str(exe)] + cm.args_for(spec, cfg) + ["--batch", str(tmp / "cbatch.txt")], check=True, capture_output=True)
    for i in range(len(compiled_list)):
        json.load(open(tmp / f"cs{i}.json"))
        if events:
            load_events(tmp / f"ce{i}.jsonl")
    return time.perf_counter() - t0


def run_benchmark(pairs: list[tuple[str, str]] | None = None, repetitions: int = 5, n_random: int = 37) -> dict:
    pairs = pairs or [("lic8x8", "lic_exact_v1"), ("bfly4_8x16", "bank_only_v1"), ("bfly4_8x16", "bfly_topology_rr_v1")]
    ws = basket(n_random)
    out = {"schema_version": 1, "kind": "runtime_benchmark", "target_speedup": TARGET_SPEEDUP,
           "host": {"platform": platform.platform(), "machine": platform.machine(), "python": platform.python_version()},
           "basket": {"size": len(ws), "composition": f"L, B, M + {n_random} random_legal (seeds 9000-{9000 + n_random - 1}, alternating hot-set 8 words)"},
           "repetitions": repetitions, "fst_dumping": False, "results": []}
    for cfg_id, model_id in pairs:
        cfg = load_config(cfg_id)
        bm = toolchain.build(cfg)
        binary = ROOT / bm["binary"]
        compiled = [validate_and_compile(w, cfg) for w in ws]
        spec = get_spec(model_id)
        total_ops = sum(c.total_ops for c in compiled)
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            files = []
            for i, c in enumerate(compiled):
                p = tmp / f"w{i}.txt"
                p.write_text(c.to_text())
                files.append(p)
            # warm-up
            _rtl_batched(binary, files[:3], tmp)
            _model(spec, cfg, compiled[:3], tmp, True)
            meas = {"rtl_per_invocation": [], "rtl_batched": [], "rtl_batched_summary_only": [],
                    "model_in_memory": [], "model_with_io": [], "model_cost_only": [],
                    "compiled_model_summary_only": [], "compiled_model_with_io": []}
            from rift.model import compiled as cm
            for _ in range(repetitions):
                meas["rtl_per_invocation"].append(_rtl_per_invocation(binary, files, tmp))
                meas["rtl_batched"].append(_rtl_batched(binary, files, tmp))
                meas["rtl_batched_summary_only"].append(_rtl_batched(binary, files, tmp, events=False))
                meas["model_in_memory"].append(_model(spec, cfg, compiled, tmp, False))
                meas["model_with_io"].append(_model(spec, cfg, compiled, tmp, True))
                meas["model_cost_only"].append(_model_cost_only(spec, cfg, compiled))
                if cm.supports(spec):
                    meas["compiled_model_summary_only"].append(_compiled(spec, cfg, compiled, tmp, False))
                    meas["compiled_model_with_io"].append(_compiled(spec, cfg, compiled, tmp, True))
            # kernel-only time: the runners' own in-process simulation seconds, summed over the basket
            with tempfile.TemporaryDirectory() as kd:
                kt = Path(kd)
                for i, c in enumerate(compiled):
                    (kt / f"w{i}.txt").write_text(c.to_text())
                kfiles = [kt / f"w{i}.txt" for i in range(len(compiled))]
                _rtl_batched(binary, kfiles, kt, events=False)
                rtl_kernel = sum(json.load(open(kt / f"bs{i}.json"))["elapsed_seconds"] for i in range(len(compiled)))
                comp_kernel = None
                if cm.supports(spec):
                    _compiled(spec, cfg, compiled, kt, False)
                    comp_kernel = sum(json.load(open(kt / f"cs{i}.json"))["elapsed_seconds"] for i in range(len(compiled)))
        med = {k: statistics.median(v) for k, v in meas.items() if v}
        res = {
            "config_id": cfg_id, "model_id": model_id, "model_digest": model_digest(spec),
            "binary_sha256": bm["binary_sha256"], "cold_build_seconds": bm["elapsed_seconds"] if not bm.get("cache_hit") else None,
            "total_operations": total_ops,
            "median_seconds": med,
            "all_seconds": meas,
            "speedup_per_invocation": med["rtl_per_invocation"] / med["model_with_io"],
            "speedup_batched": med["rtl_batched"] / med["model_with_io"],
            "speedup_batched_vs_model_in_memory": med["rtl_batched"] / med["model_in_memory"],
            "speedup_summary_only_vs_cost_only": med["rtl_batched_summary_only"] / med["model_cost_only"],
        }
        res["kernel_seconds"] = {"rtl": rtl_kernel, "compiled_model": comp_kernel}
        if comp_kernel:
            res["kernel_speedup"] = rtl_kernel / comp_kernel
        if "compiled_model_summary_only" in med:
            res["compiled_speedup_summary_only"] = med["rtl_batched_summary_only"] / med["compiled_model_summary_only"]
            res["compiled_speedup_with_io"] = med["rtl_batched"] / med["compiled_model_with_io"]
        res["primary_comparison"] = "v1 (declared before measuring): batched RTL vs Python model, both emitting and parsing full event streams"
        res["target_met"] = res["speedup_batched"] >= TARGET_SPEEDUP
        res["useful_loop_comparison"] = "v2: batched, summary-only on both sides (what the search loop consumes), compiled model vs Verilator"
        res["useful_loop_target_met"] = res.get("compiled_speedup_summary_only", 0) >= TARGET_SPEEDUP
        out["results"].append(res)
    out["primary_v1_target_met"] = all(r["target_met"] for r in out["results"])
    out["useful_loop_target_met"] = all(r["useful_loop_target_met"] for r in out["results"])
    return out
