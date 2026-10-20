"""Publish bounded browser replay inputs from immutable, verified artifacts.

No held-out definitions, search ledgers, host paths, or private files are copied.
This adds /browser beside the existing /data export; it never rewrites evidence.
"""
from __future__ import annotations

import gzip
import json
import shutil
import io
import zipfile
from pathlib import Path

from rift.contracts.canonical import bytes_digest, digest, file_digest, read_json
from rift.contracts.config import load_config
from rift.contracts.workload import validate_and_compile
from rift.model.compiled import args_for, supports
from rift.model.registry import get_spec, model_digest
from rift.paths import ROOT, BUILD, RUNS, STUDIES
from rift.presentation.adapter import REGISTRY
from rift.store import verify_run


def rtl_record(run_id: str) -> dict:
    verification = verify_run(run_id)
    if not verification["ok"]:
        raise ValueError(f"Recorded run fails integrity verification: {run_id}")
    path = RUNS / run_id
    m = read_json(path / "manifest.json")
    raw = (path / "events.jsonl").read_bytes() if (path / "events.jsonl").exists() else gzip.decompress((path / "events.jsonl.gz").read_bytes())
    return {"config_id": m["config_id"], "run_id": run_id,
            "options": {"timeout": m["timeout_cycles"], "stalls": m["stalls"],
                        "inject": m["cpp_inject"], "sv_inject": m["sv_inject_mask"]},
            "expected": {"events_sha256": bytes_digest(raw), "check": read_json(path / "check.json")},
            "reference_epoch": m["reference_epoch"]}


def replay_record(key: str, title: str, rtl_ids: dict, model_ids: dict, models: dict, kind: str) -> dict:
    rtl = {d: rtl_record(rid) for d, rid in rtl_ids.items()}
    workload = read_json(RUNS / rtl_ids["A"] / "workload.json")
    compiled = validate_and_compile(workload, load_config("lic8x8"))
    if any(read_json(RUNS / rid / "workload.json") != workload for rid in rtl_ids.values()):
        raise ValueError("Paired RTL workloads differ")
    return {"id": key, "title": title, "kind": kind, "workload": workload,
            "workload_digest": compiled.digest, "rtl": rtl, "models": models,
            "expected_models": {d: read_json(RUNS / rid / "check.json") for d, rid in model_ids.items()}}


def collect() -> tuple[list, list, dict]:
    registry = read_json(REGISTRY)
    map_data = read_json(STUDIES / registry["map_study"] / "map.json")
    defaults = {k: v["model_id"] for k, v in map_data["models"].items()}
    curated, grid = [], []
    for case in registry["cases"]:
        c = read_json(RUNS / case["comparison_run_id"] / "comparison.json")
        models = {d: v["model_id"] for d, v in c["models"].items()}
        curated.append(replay_record(case["case_id"], case["short"], c["rtl_run_ids"], c["model_run_ids"], models, "published"))
        if case.get("reduction_id"):
            reduced = read_json(STUDIES / case["reduction_id"] / "reduction.json")["reduced"]
            curated.append(replay_record(case["case_id"] + "-reduced", case["short"] + " · reduced", reduced["final_rtl_run_ids"], reduced["final_model_run_ids"], models, "reduced"))
    for cell in map_data["cells"]:
        grid.append(replay_record(f"map-{cell['i']}-{cell['j']}", f"Map · column {cell['i'] + 1}, row {cell['j'] + 1}",
                                 {d: v["run_id"] for d, v in cell["rtl"].items()},
                                 {d: v["run_id"] for d, v in cell["model"].items()}, defaults, "map"))
    return curated, grid, defaults


def publish() -> dict:
    build = read_json(BUILD / "browser/manifest.json")
    curated, grid, defaults = collect()
    model_ids = set(defaults.values()) | {m for c in curated for m in c["models"].values()}
    models = {}
    for mid in sorted(model_ids):
        spec = get_spec(mid)
        if not supports(spec):
            raise ValueError(f"No compiled implementation for {mid}")
        config_id = "lic8x8" if mid == defaults["A"] else "bfly4_8x16"
        models[mid] = {"model_id": mid, "model_digest": model_digest(spec), "config_id": config_id,
                       "args": args_for(spec, load_config(config_id)), "resp_lat": spec.get("resp_lat", 1)}
    output = ROOT / "ui/public/browser"
    output.mkdir(exist_ok=True)
    generation = output / build["build_id"][7:23]
    generation.mkdir(exist_ok=True)
    manifest = {"schema_version": 1, "build_id": build["build_id"], "reference_epoch": build["reference_epoch"],
                "toolchain": build["toolchain"], "modules": {}, "models": models, "default_models": defaults,
                "contract": {"workload": "rift.contracts.workload/v1", "checker": "rift.evaluate.checker/v1",
                             "verdict": "rift.evaluate.compare/v1", "discovery_credit": 0}}
    for name, m in build["modules"].items():
        for ext in ("mjs", "wasm"):
            source = BUILD / "browser" / name / f"engine.{ext}"
            expected = m["js_sha256" if ext == "mjs" else "wasm_sha256"]
            if file_digest(source) != expected:
                raise ValueError(f"Build artifact changed: {source}")
            shutil.copy2(source, generation / f"{name}.{ext}")
        manifest["modules"][name] = {**m, "js_url": f"/browser/{generation.name}/{name}.mjs",
                                     "wasm_url": f"/browser/{generation.name}/{name}.wasm"}
    for name, records in (("curated", curated), ("map", grid)):
        payload = json.dumps({"schema_version": 1, "build_id": build["build_id"], "records": records}, separators=(",", ":"), ensure_ascii=False).encode()
        sha = bytes_digest(payload)
        filename = f"{name}.{sha[7:23]}.json"
        (generation / filename).write_bytes(payload)
        manifest[name] = {"url": f"/browser/{generation.name}/{filename}", "sha256": sha, "count": len(records)}
    manifest["browser_contract_sources"] = {str(p.relative_to(ROOT)): file_digest(p) for p in sorted((ROOT / "ui/src/browser").glob("*.ts"))}
    manifest["browser_contract_sources"]["ui/src/replay.ts"] = file_digest(ROOT / "ui/src/replay.ts")
    # Distribute the adapted runtime sources and original third-party notices.
    # Fixed timestamps keep this optional download reproducible across builds.
    source_files = {"verilator/include/" + str(p.relative_to(BUILD / "browser/verilator-runtime")): p for p in (BUILD / "browser/verilator-runtime").rglob("*") if p.is_file()}
    source_files.update({
        "licenses/Verilator-LICENSE.txt": ROOT / "licenses/Verilator-LICENSE.txt",
        "licenses/Verilator-Artistic-2.0.txt": ROOT / "licenses/Verilator-Artistic-2.0.txt",
        "licenses/cluster_interconnect-LICENSE.txt": ROOT / "vendor/cluster_interconnect/LICENSE",
        "licenses/common_cells-LICENSE.txt": ROOT / "vendor/common_cells/LICENSE",
        "licenses/Emscripten-LICENSE.txt": ROOT / ".tools/emsdk/install/emscripten/LICENSE",
        "licenses/React-LICENSE.txt": ROOT / "ui/node_modules/react/LICENSE",
        "licenses/ReactDOM-LICENSE.txt": ROOT / "ui/node_modules/react-dom/LICENSE",
    })
    for part in ("compiler-rt/LICENSE.TXT", "libunwind/LICENSE.TXT", "libcxxabi/LICENSE.TXT", "libcxx/LICENSE.TXT", "libc/musl/COPYRIGHT"):
        source_files["licenses/" + part.replace("/", "-")] = ROOT / ".tools/emsdk/install/emscripten/system/lib" / part
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, p in sorted(source_files.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)); info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, p.read_bytes())
        z.writestr(zipfile.ZipInfo("RIFT-RUNTIME-CHANGES.json", (1980, 1, 1, 0, 0, 0)), json.dumps(build["toolchain"]["runtime_adaptations"], indent=2))
    source_bytes = bundle.getvalue(); source_sha = bytes_digest(source_bytes)
    source_name = f"runtime-source.{source_sha[7:23]}.zip"
    (generation / source_name).write_bytes(source_bytes)
    manifest["runtime_source"] = {"url": f"/browser/{generation.name}/{source_name}", "sha256": source_sha}
    manifest["manifest_digest"] = digest(manifest, strict=False)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Browser replay data: {len(curated)} curated + {len(grid)} map workloads; {build['build_id']}")
    return manifest


if __name__ == "__main__":
    publish()
