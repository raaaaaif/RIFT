"""Source/tool verification and content-addressed Verilator builds."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

from rift.contracts.canonical import digest, file_digest, read_json, write_json_replace
from rift.contracts.config import ArchConfig
from rift.paths import BUILD, LOCKS, OSS_CAD_BIN, ROOT, rel

SOURCES_LOCK = LOCKS / "sources.lock.json"
TOOLCHAIN_LOCK = LOCKS / "toolchain.lock.json"
PREPROCESSING = LOCKS / "preprocessing.json"
ASSERTION_REGISTER = LOCKS / "assertion_exclusions.json"

MEMORY_ORACLE_SPEC = {
    "function": "f(q) = ((q * 0x9E3779B1) XOR 0xA5A55A5A) mod 2^32",
    "capacity_words": 4096,
    "distribution": "bank = q mod NumOut, row = floor(q / NumOut)",
    "bank_read": "synchronous: row captured on req_o&gnt_i at edge t, data exposed for the V_(t+1) sample",
}
SAMPLING_CONVENTION = {
    "id": "pre_rise_v1",
    "acceptance": "A_t = req_i & gnt_o sampled immediately before rising edge t",
    "response": "V_t = vld_o/rdata_o sampled immediately before rising edge t; RespLat=1 means A_t -> V_(t+1)",
    "reset": "4 request-free rising edges with rst_ni=0; first release cycle is the first cycle after reset",
    "makespan": "last_response_cycle - first_release_cycle + 1 (inclusive)",
}


class ToolchainError(RuntimeError):
    pass


def tool_env() -> dict:
    env = dict(os.environ)
    env["PATH"] = f"{OSS_CAD_BIN}:{env.get('PATH', '')}"
    return env


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, env=tool_env(), **kw)


def tool_versions() -> dict:
    out = {}
    probes = {
        "verilator": ["verilator", "--version"],
        "yosys": ["yosys", "-V"],
        "yices-smt2": ["yices-smt2", "--version"],
        "bitwuzla": ["bitwuzla", "--version"],
        "z3": ["z3", "--version"],
        "boolector": ["boolector", "--version"],
    }
    for name, cmd in probes.items():
        exe = OSS_CAD_BIN / cmd[0]
        if not exe.exists():
            out[name] = None
            continue
        try:
            r = _run([str(exe)] + cmd[1:], timeout=30)
            out[name] = (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr) else ""
        except Exception as e:  # pragma: no cover - environment dependent
            out[name] = f"ERROR: {e}"
    try:
        r = subprocess.run(["c++", "--version"], capture_output=True, text=True, timeout=30)
        out["cxx"] = r.stdout.strip().splitlines()[0]
    except Exception:
        out["cxx"] = None
    out["python"] = sys.version.split()[0]
    return out


def lock_digests() -> dict:
    return {
        "sources_lock": file_digest(SOURCES_LOCK),
        "toolchain_lock": file_digest(TOOLCHAIN_LOCK),
        "preprocessing": file_digest(PREPROCESSING),
        "assertion_register": file_digest(ASSERTION_REGISTER),
    }


def verify_sources() -> dict:
    """Check that vendor checkouts sit at the locked commits with no local changes."""
    lock = read_json(SOURCES_LOCK)
    result = {"ok": True, "repositories": []}
    for repo in lock["repositories"]:
        path = ROOT / repo["checkout"]
        entry = {"name": repo["name"], "expected": repo["commit"], "path": repo["checkout"]}
        if not (path / ".git").exists():
            entry.update(status="MISSING")
            result["ok"] = False
        else:
            head = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
            dirty = subprocess.run(["git", "-C", str(path), "status", "--porcelain"], capture_output=True, text=True).stdout.strip()
            entry.update(actual=head, dirty=bool(dirty))
            if head != repo["commit"] or dirty:
                entry["status"] = "MISMATCH"
                result["ok"] = False
            else:
                entry["status"] = "OK"
        result["repositories"].append(entry)
    files = []
    for f in lock["compilation_order"] + lock["rift_sources"]:
        p = ROOT / f
        files.append({"path": f, "sha256": file_digest(p) if p.exists() else None})
        if not p.exists():
            result["ok"] = False
    result["files"] = files
    return result


def fetch_sources() -> dict:
    lock = read_json(SOURCES_LOCK)
    actions = []
    for repo in lock["repositories"]:
        path = ROOT / repo["checkout"]
        if (path / ".git").exists():
            actions.append({"name": repo["name"], "action": "present"})
            continue
        path.mkdir(parents=True, exist_ok=True)
        steps = [
            ["git", "init", "-q", str(path)],
            ["git", "-C", str(path), "remote", "add", "origin", repo["url"]],
            ["git", "-C", str(path), "fetch", "-q", "--depth", "1", "origin", repo["commit"]],
            ["git", "-C", str(path), "checkout", "-q", "--detach", "FETCH_HEAD"],
        ]
        for s in steps:
            r = subprocess.run(s, capture_output=True, text=True)
            if r.returncode:
                raise ToolchainError(f"fetch failed for {repo['name']}: {r.stderr.strip()}")
        actions.append({"name": repo["name"], "action": "fetched", "commit": repo["commit"]})
    return {"actions": actions, "verification": verify_sources()}


def doctor() -> dict:
    lock = read_json(TOOLCHAIN_LOCK)
    versions = tool_versions()
    checks = []

    def check(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    check("python_3_12", sys.version_info[:2] == (3, 12), sys.version.split()[0])
    check("toolchain_installed", OSS_CAD_BIN.exists(), rel(OSS_CAD_BIN))
    for tool, expected in lock["expected_tool_versions"].items():
        actual = versions.get(tool)
        check(f"version:{tool}", actual == expected, {"expected": expected, "actual": actual})
    check("cxx_compiler", versions.get("cxx") is not None, versions.get("cxx"))
    src = verify_sources()
    check("sources_locked_and_clean", src["ok"], [{k: r.get(k) for k in ("name", "status")} for r in src["repositories"]])
    free = shutil.disk_usage(ROOT).free
    check("disk_free_over_1GiB", free > (1 << 30), f"{free / (1 << 30):.2f} GiB free")
    return {
        "ok": all(c["ok"] for c in checks),
        "host": {"platform": platform.platform(), "machine": platform.machine()},
        "tool_versions": versions,
        "checks": checks,
        "lock_digests": lock_digests(),
    }


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
_version_cache: dict | None = None


def _versions_cached() -> dict:
    global _version_cache
    if _version_cache is None:
        _version_cache = tool_versions()
    return _version_cache


def build_key(config: ArchConfig, trace: bool = False) -> dict:
    lock = read_json(SOURCES_LOCK)
    pre = read_json(PREPROCESSING)
    files = [{"path": f, "sha256": file_digest(ROOT / f)} for f in lock["compilation_order"] + lock["rift_sources"]]
    v = _versions_cached()
    key = {
        "config": config.raw,
        "files": files,
        "verilator_flags": pre["verilator_flags"],
        "cxx_flags": pre["cxx_flags"],
        "trace": trace,
        "verilator": v.get("verilator"),
        "cxx": v.get("cxx"),
    }
    return key


def build_dir_for(config: ArchConfig, trace: bool = False) -> tuple[Path, dict, str]:
    key = build_key(config, trace)
    kd = digest(key)
    d = BUILD / f"{config.config_id}{'-trace' if trace else ''}-{kd[7:19]}"
    return d, key, kd


def build(config: ArchConfig, trace: bool = False, force: bool = False) -> dict:
    src = verify_sources()
    if not src["ok"]:
        raise ToolchainError("pinned sources missing, modified or at the wrong commit; run `rift fetch`")
    d, key, kd = build_dir_for(config, trace)
    manifest_path = d / "build_manifest.json"
    binary = d / "obj_dir" / "rift_sim"
    if manifest_path.exists() and binary.exists() and not force:
        m = read_json(manifest_path)
        if m.get("status") == "OK" and m.get("binary_sha256") == file_digest(binary):
            m["cache_hit"] = True
            return m
    lock = read_json(SOURCES_LOCK)
    pre = read_json(PREPROCESSING)
    d.mkdir(parents=True, exist_ok=True)
    defines = [
        f"-DRIFT_NUM_IN={config.num_in}",
        f"-DRIFT_NUM_OUT={config.num_out}",
        f"-DRIFT_ADDR_MEM_WIDTH={config.addr_mem_width}",
        f"-DRIFT_TOPOLOGY={config.topology_code}",
    ]
    if trace:
        defines.append("-DRIFT_TRACE")
    cflags = " ".join(pre["cxx_flags"] + defines)
    cmd = ["verilator"] + pre["verilator_flags"] + [
        "-j", "4",
        f"-GTOPOLOGY={config.topology_code}",
        f"-GNUM_IN={config.num_in}",
        f"-GNUM_OUT={config.num_out}",
        f"-GADDR_MEM_WIDTH={config.addr_mem_width}",
        "-CFLAGS", cflags,
        "--Mdir", str(d / "obj_dir"),
        "-o", "rift_sim",
    ]
    if trace:
        cmd.append("--trace-fst")
        # Diagnostic builds only: the bundled FST writer needs lz4 from the host.
        for prefix in ("/opt/homebrew", "/usr/local", "/usr"):
            if Path(prefix, "include", "lz4.h").exists():
                cmd += ["-CFLAGS", f"-I{prefix}/include", "-LDFLAGS", f"-L{prefix}/lib -llz4"]
                break
    cmd += [str(ROOT / f) for f in lock["compilation_order"]] + [str(ROOT / f) for f in lock["rift_sources"]]
    t0 = time.time()
    r = _run(cmd, cwd=str(ROOT), timeout=1800)
    elapsed = time.time() - t0
    log = (r.stdout or "") + (r.stderr or "")
    (d / "build.log").write_text(log)
    warnings = sorted({ln.split(":")[0] + ":" + ln.split(":")[1] for ln in log.splitlines() if ln.startswith("%Warning")})
    ok = r.returncode == 0 and binary.exists()
    manifest = {
        "schema_version": 1,
        "build_key_digest": kd,
        "config_id": config.config_id,
        "config_digest": config.digest,
        "status": "OK" if ok else "ELABORATION_ERROR",
        "exit_code": r.returncode,
        "command": [c if not c.startswith(str(ROOT)) else rel(Path(c)) for c in cmd],
        "files": key["files"],
        "tool_versions": {"verilator": key["verilator"], "cxx": key["cxx"]},
        "warnings": [w for w in warnings],
        "warning_lines": [ln for ln in log.splitlines() if ln.startswith("%Warning")],
        "elapsed_seconds": round(elapsed, 3),
        "binary": rel(binary),
        "binary_sha256": file_digest(binary) if ok else None,
        "trace_support": trace,
        "cache_hit": False,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    write_json_replace(manifest_path, manifest)
    if not ok:
        raise ToolchainError(f"Verilator build failed for {config.config_id}; see {rel(d / 'build.log')}")
    return manifest
