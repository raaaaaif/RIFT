"""RIFT command-line interface.

Every command prints one JSON document on stdout with a "status" field and
the paths of artifacts it wrote. Exit codes: 0 command completed (the
scientific outcome is in the JSON), 1 command failed, 2 usage error.
An invoked tool is never reported as engineering success by itself.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback

from rift.paths import STUDIES, rel


def _emit(obj: dict) -> None:
    json.dump(obj, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


def cmd_doctor(args) -> int:
    from rift import toolchain
    r = toolchain.doctor()
    _emit({"status": "OK" if r["ok"] else "DEGRADED", **r})
    return 0


def cmd_fetch(args) -> int:
    from rift import toolchain
    _emit({"status": "OK", **toolchain.fetch_sources()})
    return 0


def cmd_build(args) -> int:
    from rift import toolchain
    from rift.contracts.config import load_config
    m = toolchain.build(load_config(args.config), trace=args.trace, force=args.force)
    _emit({"status": m["status"], "build": m})
    return 0


def cmd_gate0a(args) -> int:
    from rift.gates import gate0a
    from rift.store import RunDir
    report = gate0a(args.config)
    sd = RunDir("gate0a", root=STUDIES)
    sd.write_json("gate0a_report.json", report)
    m = sd.finalize({"schema_version": 1, "kind": "gate0a", "status": "PASSED" if report["passed"] else "FAILED",
                     "reference_epoch": report["reference_epoch"], "tags": ["gate0a"]})
    _emit({"status": m["status"], "study_id": sd.run_id, "path": rel(sd.path),
           "checks": [{"check": c["check"], "passed": c["passed"]} for c in report["checks"]]})
    return 0


def cmd_replay(args) -> int:
    """Execute one workload on one configuration with the RTL runner or a model."""
    from rift.contracts.canonical import read_json
    from rift.contracts.config import load_config
    from rift.contracts.workload import validate_and_compile
    from rift.paths import ROOT
    exp = read_json(args.experiment)
    cfg = load_config(exp["config"])
    w = exp["workload"] if "workload" in exp else read_json(ROOT / exp["workload_path"])
    compiled = validate_and_compile(w, cfg)
    stalls = tuple(tuple(s) for s in exp.get("stalls", []))
    if exp.get("runner", "rtl") == "rtl":
        from rift.rtl import run_rtl
        r = run_rtl(cfg, compiled, stalls=stalls, timeout=exp.get("timeout_cycles", 4096), fst=exp.get("fst", False),
                    tags=tuple(exp.get("tags", [])))
    else:
        from rift.model.registry import get_spec
        from rift.modelrun import run_model_artifact
        r = run_model_artifact(get_spec(exp["model"]), cfg, compiled, timeout=exp.get("timeout_cycles", 4096), tags=tuple(exp.get("tags", [])))
    _emit({"status": r["check"]["status"], "run_id": r["run_id"], "path": rel(r["path"]), "makespan": r["check"].get("makespan"),
           "check": {k: r["check"].get(k) for k in ("status", "accepted", "completed", "violation_counts", "acceptance_window")}})
    return 0


def cmd_compare(args) -> int:
    from pathlib import Path
    from rift.experiment import run_comparison_experiment
    r = run_comparison_experiment(Path(args.experiment))
    rep = r["report"]
    _emit({"status": "COMPLETED", "study_id": r["study_id"], "path": r["path"], "verdict_counts": rep["verdict_counts"],
           "comparisons": [{k: c.get(k) for k in ("workload_id", "verdict", "model_costs", "rtl_costs", "dM", "dR", "model_choice", "rtl_best", "selection", "comparison_run_id")}
                           for c in rep["comparisons"]]})
    return 0


def cmd_benchmark(args) -> int:
    from rift.benchmark import run_benchmark
    from rift.store import RunDir
    r = run_benchmark(repetitions=args.repetitions, n_random=args.random)
    sd = RunDir("benchmark", root=STUDIES)
    sd.write_json("benchmark.json", r)
    m = sd.finalize({"schema_version": 1, "kind": "runtime_benchmark", "status": ("USEFUL_LOOP_TARGET_MET" if r["useful_loop_target_met"] else "TARGET_UNMET"),
                     "tags": ["runtime"]})
    _emit({"status": m["status"], "study_id": sd.run_id, "path": rel(sd.path),
           "primary_v1_target_met": r["primary_v1_target_met"], "useful_loop_target_met": r["useful_loop_target_met"],
           "results": [{k: x.get(k) for k in ("config_id", "model_id", "speedup_batched", "speedup_summary_only_vs_cost_only",
                                              "compiled_speedup_summary_only", "compiled_speedup_with_io", "useful_loop_target_met")} for x in r["results"]]})
    return 0


def cmd_search(args) -> int:
    from pathlib import Path
    from rift.search.study import run_screen
    r = run_screen(Path(args.study), arms=args.arms, cases=args.cases)
    s = r["summary"]
    _emit({"status": "COMPLETED", "screen_run_id": r["screen_run_id"], "path": r["path"],
           "cases": {cid: {a: {k: v.get(k) for k in ("status", "credited_counterexamples", "first_credited_discovery_at_rtl_execution", "max_regret")}
                           for a, v in c["arms"].items()} for cid, c in s["cases"].items()}})
    return 0


def cmd_reduce(args) -> int:
    from rift.contracts.canonical import read_json
    from rift.reduce.reducer import reduce_witness
    w = read_json(args.witness)
    r = reduce_witness(w["workload"], w["designs"], w["models"], rtl_budget=w.get("rtl_budget", 32),
                       case_id=w.get("case_id", "unspecified"), provenance=w.get("provenance", "AUTHORED_DEFECT"))
    _emit({"status": r["status"], "study_id": r.get("study_id"), "reduction_ratio_operations": r.get("reduction_ratio_operations"),
           "rtl_executions_used": r.get("rtl_executions_used"), "minimality": r.get("minimality"),
           "reduced_verdict": (r.get("reduced") or {}).get("verdict")})
    return 0


def cmd_repair(args) -> int:
    from pathlib import Path
    from rift.repair.repair import run_repair
    r = run_repair(Path(args.case))
    _emit({"status": "SUBMITTED", "repair_id": r["repair_id"], "submission": r["submission_path"],
           "candidate_model_id": r["submission"]["candidate_model_id"], "semantic_change": r["submission"]["patch"]["semantic_change"],
           "development_result": r["submission"]["development_result"]})
    return 0


def cmd_verify(args) -> int:
    from pathlib import Path
    from rift.evaluate.verify import verify_submission
    r = verify_submission(Path(args.submission), Path(args.basket) if args.basket else None)
    _emit({"status": r["status"], "verification_id": r["verification_id"], "failed_rules": r["failed_rules"],
           "rules": {k: {"passed": v["passed"], "detail": v["detail"]} for k, v in r["rules"].items()},
           "families": r["families"], "retained_model": r["retained_model"]})
    return 0


def cmd_formal(args) -> int:
    from rift.formal import run_lic2x2_formal
    r = run_lic2x2_formal(depth=args.depth)
    _emit({"status": r["claims"]["all_properties"], "study_id": r["study_id"], "harness_valid": r["harness_valid"],
           "harness_problems": r["harness_problems"], "inventory": r["inventory"], "claims": r["claims"],
           "tasks": {k: v["outcome"] for k, v in r["tasks"].items()}})
    return 0


def cmd_export(args) -> int:
    from rift.export import export
    r = export(args.run, args.name, args.include_all_runs)
    _emit({"status": "EXPORTED", **r})
    return 0


def cmd_pipeline(args) -> int:
    from rift.pipeline import run_pipeline
    r = run_pipeline(log=lambda m: print(m, file=sys.stderr, flush=True), benchmark_reps=args.benchmark_reps,
                     export=not args.no_export, build_ui=not args.no_ui, resume=args.resume)
    _emit({"status": "COMPLETED", **r})
    return 0


def cmd_map(args) -> int:
    from rift.map import run_decision_map
    from rift.pipeline import apply_map, map_inputs
    from rift.contracts.canonical import read_json, write_json_replace
    from rift.paths import EXPERIMENTS
    path = EXPERIMENTS / "cases" / "registry.json"
    reg = read_json(path)
    repaired, landmarks = map_inputs(reg)
    r = run_decision_map(args.repaired or repaired, landmarks, log=lambda m: print(m, file=sys.stderr, flush=True))
    apply_map(reg, r["map_study_id"])
    write_json_replace(path, reg)
    _emit({"status": "COMPLETED", **r})
    return 0


def cmd_publish(args) -> int:
    from rift.publish import publish_static
    _emit({"status": "PUBLISHED", **publish_static()})
    return 0


def cmd_serve(args) -> int:
    from rift.server import serve
    serve(args.host, args.port, allow_run=args.allow_run)
    return 0


def cmd_browser_verify(args) -> int:
    from pathlib import Path
    import tempfile
    from rift.browser_verify import verify_receipt
    from rift.contracts.canonical import write_json
    from rift.paths import BUILD, rel
    result = verify_receipt(Path(args.receipt))
    if args.out:
        report = Path(args.out)
        write_json(report, result)
    else:
        directory = BUILD / "browser-verification"
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", prefix="verification-", dir=directory, delete=False) as f:
            json.dump(result, f, indent=2)
            report = Path(f.name)
    _emit({"status": "VERIFIED" if result["ok"] else "MISMATCH", "report": rel(report), **result})
    return 0 if result["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m rift", description="RIFT performance-model audit instrument")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("browser-verify", help="reproduce a browser receipt with native RTL and the Python checker")
    s.add_argument("--receipt", required=True)
    s.add_argument("--out", help="new report path (never overwrites a file)")
    s.set_defaults(func=cmd_browser_verify)
    s = sub.add_parser("doctor", help="verify toolchain, versions and source locks")
    s.set_defaults(func=cmd_doctor)
    s = sub.add_parser("fetch", help="fetch pinned upstream sources into vendor/")
    s.set_defaults(func=cmd_fetch)
    s = sub.add_parser("build", help="build the Verilator harness for a configuration")
    s.add_argument("--config", required=True)
    s.add_argument("--trace", action="store_true", help="diagnostic build with FST support")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_build)
    s = sub.add_parser("gate0a", help="run the LIC2x2 harness validation gate")
    s.add_argument("--config", default="lic2x2")
    s.set_defaults(func=cmd_gate0a)
    s = sub.add_parser("replay", help="execute one workload on one configuration (RTL or model)")
    s.add_argument("--experiment", required=True)
    s.set_defaults(func=cmd_replay)
    s = sub.add_parser("compare", help="run a paired model/RTL comparison experiment")
    s.add_argument("--experiment", required=True)
    s.set_defaults(func=cmd_compare)
    s = sub.add_parser("benchmark", help="measure warm model vs Verilator runtime (5x useful-loop target)")
    s.add_argument("--repetitions", type=int, default=5)
    s.add_argument("--random", type=int, default=397, help="random workloads added to L/B/M")
    s.set_defaults(func=cmd_benchmark)
    s = sub.add_parser("search", help="run the budgeted discovery screen")
    s.add_argument("--study", required=True)
    s.add_argument("--arms", nargs="*")
    s.add_argument("--cases", nargs="*")
    s.set_defaults(func=cmd_search)
    s = sub.add_parser("reduce", help="history-preserving witness reduction")
    s.add_argument("--witness", required=True)
    s.set_defaults(func=cmd_reduce)
    s = sub.add_parser("repair", help="structural model repair (submits a candidate)")
    s.add_argument("--case", required=True)
    s.set_defaults(func=cmd_repair)
    s = sub.add_parser("verify", help="independent repair verification on the sealed held-out basket")
    s.add_argument("--submission", required=True)
    s.add_argument("--basket", help="sealed held-out basket (default experiments/heldout/heldout_v1.json)")
    s.set_defaults(func=cmd_verify)
    s = sub.add_parser("formal", help="local SBY properties on LIC 2x2")
    s.add_argument("--depth", type=int, default=16)
    s.set_defaults(func=cmd_formal)
    s = sub.add_parser("export", help="export a digest-verified evidence bundle")
    s.add_argument("--run", required=True)
    s.add_argument("--name")
    s.add_argument("--include-all-runs", action="store_true")
    s.set_defaults(func=cmd_export)
    s = sub.add_parser("pipeline", help="run every stage end to end and publish the site")
    s.add_argument("--benchmark-reps", type=int, default=3)
    s.add_argument("--no-export", action="store_true")
    s.add_argument("--no-ui", action="store_true")
    s.add_argument("--resume", action="store_true", help="reuse stages finished by an interrupted run in the same reference epoch")
    s.set_defaults(func=cmd_pipeline)
    s = sub.add_parser("map", help="run the frozen decision map (experiments/maps/decision_map_v1.json)")
    s.add_argument("--repaired", help="repaired butterfly model id (default: the registry's C1 repair candidate)")
    s.set_defaults(func=cmd_map)
    s = sub.add_parser("publish", help="write static site data (ui/public/data) from the case registry")
    s.set_defaults(func=cmd_publish)
    s = sub.add_parser("serve", help="serve the evidence viewer and read API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8770)
    s.add_argument("--allow-run", action="store_true", help="enable budgeted replay execution through the controller")
    s.set_defaults(func=cmd_serve)
    return p


def main(argv=None) -> int:
    p = build_parser()
    args = p.parse_args(argv)
    try:
        return args.func(args)
    except SystemExit:
        raise
    except Exception as e:  # report failures as machine-readable status
        _emit({"status": "ERROR", "error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()})
        return 1
