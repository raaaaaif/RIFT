"""Build the browser simulators without changing the native reference epoch.

Run with python3.12 -m rift.browser_build. Native builds are read through the
existing content-addressed builder. Only a private copy of Verilator's runtime
is adapted: its context defaults to one thread. The original driver is compiled
verbatim, with the same defines and generated RTL as its native counterpart.
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
from pathlib import Path

from rift import toolchain
from rift.contracts.canonical import digest, file_digest, read_json
from rift.contracts.config import load_config
from rift.paths import ROOT, BUILD, TOOLS
from rift.rtl import reference_epoch, reference_identity

SDK = TOOLS / "emsdk"
FLAGS = ["-std=c++17", "-O2", "-fexceptions", "-sMODULARIZE=1", "-sEXPORT_ES6=1",
         "-sENVIRONMENT=worker,node", "-sINVOKE_RUN=0", "-sEXIT_RUNTIME=0",
         "-sALLOW_MEMORY_GROWTH=1", "-sMAXIMUM_MEMORY=268435456", "-sFORCE_FILESYSTEM=1",
         "-sEXPORTED_FUNCTIONS=['_main']", "-sEXPORTED_RUNTIME_METHODS=['callMain','FS']"]


def build() -> dict:
    emcc = SDK / "install/emscripten/em++"
    if not emcc.exists():
        raise RuntimeError("Install the pinned browser SDK first; see docs/browser-execution.md")
    env = {**os.environ, "EM_CONFIG": str(SDK / ".emscripten")}
    version = subprocess.check_output([str(emcc), "--version"], env=env, text=True).splitlines()[0]
    if "6.0.13" not in version:
        raise RuntimeError(f"Unexpected browser compiler: {version}")
    target = BUILD / "browser"
    target.mkdir(exist_ok=True)
    runtime_src = toolchain.OSS_CAD_BIN.parent / "share/verilator/include"
    runtime = target / "verilator-runtime"
    shutil.copytree(runtime_src, runtime, dirs_exist_ok=True)
    header = runtime / "verilated.h"
    old = "unsigned m_threads = VlOs::getProcessDefaultParallelism();"
    content = header.read_text()
    if content.count(old) != 1:
        raise RuntimeError("Pinned Verilator runtime no longer matches the reviewed adaptation")
    header.write_text(content.replace(old, "unsigned m_threads = 1;  // RIFT browser: one ordinary Worker"))
    adaptations = [{"path": "verilated.h", "original_sha256": file_digest(runtime_src / "verilated.h"),
                    "adapted_sha256": file_digest(header), "change": "default context thread count = 1"}]
    # Emscripten's libc defines CPU_ZERO but has no native CPU-affinity API.
    # Select the upstream non-affinity branch, without adding permissive stubs.
    for name in ("verilatedos_c.h", "verilated_threads.cpp"):
        condition = "defined(__linux) || defined(CPU_ZERO)" + (" || defined(VL_CPPCHECK)" if name.endswith(".cpp") else "")
        guard = "#if " + condition
        p = runtime / name
        content = p.read_text()
        if content.count(guard) != 1:
            raise RuntimeError(f"Unexpected affinity guard in {name}")
        p.write_text(content.replace(guard, f"#if !defined(__EMSCRIPTEN__) && ({condition})"))
        adaptations.append({"path": name, "original_sha256": file_digest(runtime_src / name),
                            "adapted_sha256": file_digest(p), "change": "use upstream non-affinity branch on Emscripten"})
    lock = {"schema_version": 1, "emscripten_version": version,
            "release": "6.0.13", "release_hash": "eb132757325583b787fe9414b09afea9442b72ad",
            "darwin_arm64_archive_sha256": "3d8ced05935fbef5b3edda4252dce260004860bf8d579617f13d417338aa4cac",
            "flags": FLAGS, "runtime_adaptations": adaptations,
            "native_toolchain_lock_sha256": file_digest(toolchain.TOOLCHAIN_LOCK),
            "builder_sha256": file_digest(Path(__file__)),
            "fastmodel_source_sha256": file_digest(ROOT / "oracle/fastmodel.cpp")}
    modules = {}
    epoch = None
    for name in ("lic8x8", "bfly4_8x16", "fastmodel"):
        out = target / name
        out.mkdir(exist_ok=True)
        if name == "fastmodel":
            sources = [ROOT / "oracle/fastmodel.cpp"]
            extra = []
            identity = {"source_sha256": lock["fastmodel_source_sha256"]}
        else:
            cfg = load_config(name)
            bm = toolchain.build(cfg)
            identity = reference_identity(cfg, bm)
            epoch = reference_epoch(identity)
            obj = (ROOT / bm["binary"]).parent
            sources = [p for p in sorted(obj.glob("V*.cpp")) if not p.name.endswith("__ALL.cpp")]
            sources += [runtime / "verilated.cpp", runtime / "verilated_threads.cpp", ROOT / "oracle/main.cpp"]
            extra = [f"-I{runtime.relative_to(ROOT)}", f"-I{(runtime / 'vltstd').relative_to(ROOT)}", f"-I{obj.relative_to(ROOT)}",
                     f"-DRIFT_NUM_IN={cfg.num_in}", f"-DRIFT_NUM_OUT={cfg.num_out}",
                     f"-DRIFT_ADDR_MEM_WIDTH={cfg.addr_mem_width}", f"-DRIFT_TOPOLOGY={cfg.topology_code}"]
        key = digest({"lock": lock, "identity": identity,
                      "sources": {p.name: file_digest(p) for p in sources}})
        stamp = out / "key.txt"
        js = out / "engine.mjs"
        wasm = out / "engine.wasm"
        if not (stamp.exists() and stamp.read_text() == key and js.exists() and wasm.exists()):
            command = [str(emcc), *FLAGS, *extra, *[str(p.relative_to(ROOT)) for p in sources], "-o", str(js.relative_to(ROOT))]
            print(f"Compiling {name}…", flush=True)
            result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
            (out / "build.log").write_text(result.stdout + result.stderr)
            if result.returncode:
                raise RuntimeError(f"{name} build failed: {result.stderr[-5000:]}")
            stamp.write_text(key)
        modules[name] = {"build_key": key, "native_reference": identity,
                         "js_sha256": file_digest(js), "wasm_sha256": file_digest(wasm),
                         "wasm_bytes": wasm.stat().st_size,
                         "gzip_bytes": len(gzip.compress(wasm.read_bytes(), mtime=0)) + len(gzip.compress(js.read_bytes(), mtime=0))}
        print(f"{name}: {modules[name]['wasm_bytes']:,} bytes WASM; {modules[name]['gzip_bytes']:,} bytes compressed runtime", flush=True)
    manifest = {"schema_version": 1, "reference_epoch": epoch, "toolchain": lock, "modules": modules}
    manifest["build_id"] = digest(manifest)
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (ROOT / "locks/browser-toolchain.lock.json").write_text(json.dumps(lock, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
