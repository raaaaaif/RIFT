"""Local formal checks with SBY (yosys-slang frontend) and typed outcomes.

Outcomes: PROVED, BOUNDED_NO_COUNTEREXAMPLE, COUNTEREXAMPLE, UNKNOWN, TIMEOUT,
ELABORATION_ERROR, HARNESS_INVALID. The elaborated assert/assume/cover cell
inventory is compared with the frozen expected inventory; a mismatch, an
unexpected blackbox, or an unreachable cover makes the harness invalid.
Formal results concern the RTL harness only, never the Python fast models.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path

from rift.contracts.canonical import digest, file_digest, read_json
from rift.paths import ROOT, STUDIES, rel
from rift.store import RunDir
from rift.toolchain import SOURCES_LOCK, tool_env

LIC2X2_HARNESS = ROOT / "formal/rift_lic2x2_formal.sv"
B3_HARNESS = ROOT / "formal/rift_bfly_conflict_search.sv"
EXPECTED_INVENTORY = ROOT / "formal/expected_inventory.json"

PROPERTIES = [
    ("P1", "grant implies request (per initiator)"),
    ("P2", "at most one accepted initiator per bank per cycle"),
    ("P3", "initiator acceptances equal bank acceptances"),
    ("P4", "each bank acceptance carries an accepted initiator's row"),
    ("P5", "RespLat=1: vld_o[i] at t+1 iff a read of initiator i was accepted at t"),
    ("P6", "response data is routed from the accepted bank"),
    ("P7", "no responses while reset is asserted"),
    ("P8", "LIC work conservation: a requested, granting bank accepts someone"),
    ("P9", "RIFT wrapper monitors never fire under the environment assumptions"),
    ("P10", "a locked bank arbiter only holds requests that are still being made (strengthening invariant)"),
]
COVERS = [("K1", "single transfer"), ("K2", "parallel transfer"), ("K3", "same-bank contention"),
          ("K4", "stalled request later accepted"), ("K5", "simultaneous responses")]
ASSUMPTIONS = [
    "reset asserted in the first cycle only, then deasserted permanently",
    "aligned addresses below 16384 bytes (4096 words)",
    "read-only: wen_i=0, be_i=4'hf",
    "no requests while reset is asserted",
    "an unaccepted request keeps req_i and add_i stable in the next cycle",
    "bank grants gnt_i and bank read data rdata_i are unconstrained (symbolic)",
]


def _sources() -> list[str]:
    lock = read_json(SOURCES_LOCK)
    return [str(ROOT / f) for f in lock["compilation_order"]] + [str(ROOT / "rtl_wrapper/rift_tcdm_top.sv")]


def inventory(top: str, harness: Path, defines: list[str] = (), extra_dirs: list[Path] = ()) -> dict:
    """Elaborate with yosys-slang and count $check cells by flavor plus blackboxes."""
    files = " ".join(_sources() + [str(harness)])
    dflags = " ".join(f"-D {d}" for d in defines)
    incs = " ".join(f"-I {d}" for d in extra_dirs)
    tmp = Path("/tmp") / f"rift_inv_{top}_{int(time.time() * 1e6)}"
    script = (f"read_slang {dflags} {incs} --top {top} {files}; prep -top {top}; "
              f"select -set c t:$check; tee -o {tmp}_dump dump @c; tee -o {tmp}_bb select -count A:blackbox")
    r = subprocess.run(["yosys", "-q", "-m", "slang", "-p", script], capture_output=True, text=True, env=tool_env(), timeout=600)
    if r.returncode != 0:
        return {"ok": False, "error": (r.stdout + r.stderr)[-2000:]}
    dump = Path(f"{tmp}_dump").read_text()
    bb = Path(f"{tmp}_bb").read_text()
    Path(f"{tmp}_dump").unlink(missing_ok=True)
    Path(f"{tmp}_bb").unlink(missing_ok=True)
    flavors = re.findall(r'parameter \\FLAVOR "(\w+)"', dump)
    m = re.search(r"(\d+) objects", bb)
    return {"ok": True, "asserts": flavors.count("assert"), "assumes": flavors.count("assume"), "covers": flavors.count("cover"),
            "other_checks": len(flavors) - sum(flavors.count(k) for k in ("assert", "assume", "cover")),
            "blackboxes": int(m.group(1)) if m else None}


def _sby(workdir: Path, name: str, top: str, harness: Path, mode: str, depth: int, defines=(), engine="smtbmc yices",
         timeout=900, include_files: list[Path] = ()) -> dict:
    files = _sources() + [str(harness)]
    dflags = " ".join(f"-D {d}" for d in defines)
    sby = [
        "[options]", f"mode {mode}", f"depth {depth}", "",
        "[engines]", engine, "",
        "[script]", "plugin -i slang",
        f"read_slang {dflags} -I . --top {top} " + " ".join(Path(f).name for f in files),
        f"prep -top {top}", "",
        "[files]",
    ] + files + [str(p) for p in include_files]
    p = workdir / f"{name}.sby"
    p.write_text("\n".join(sby) + "\n")
    t0 = time.time()
    try:
        r = subprocess.run(["sby", "-f", str(p)], capture_output=True, text=True, env=tool_env(), cwd=str(workdir), timeout=timeout)
        out = r.stdout + r.stderr
        rc = r.returncode
    except subprocess.TimeoutExpired:
        return {"outcome": "TIMEOUT", "elapsed_seconds": timeout}
    elapsed = time.time() - t0
    (workdir / f"{name}.log").write_text(out)
    done = re.search(r"DONE \((\w+), rc=(\d+)\)", out)
    status = done.group(1) if done else None
    reached = re.findall(r"reached cover statement .*? at (\S+)", out)
    unreached = re.findall(r"unreached cover statement .*? at (\S+)", out)
    if status == "ERROR" or ("ERROR" in out and status is None):
        outcome = "ELABORATION_ERROR"
    elif mode == "prove":
        outcome = {"PASS": "PROVED", "FAIL": "COUNTEREXAMPLE"}.get(status, "UNKNOWN")
    elif mode == "bmc":
        outcome = {"PASS": "BOUNDED_NO_COUNTEREXAMPLE", "FAIL": "COUNTEREXAMPLE"}.get(status, "UNKNOWN")
    elif mode == "cover":
        outcome = "COVERS_REACHED" if status == "PASS" else ("COVER_UNREACHED" if unreached or status == "FAIL" else "UNKNOWN")
    else:
        outcome = "UNKNOWN"
    return {"outcome": outcome, "sby_status": status, "rc": rc, "elapsed_seconds": round(elapsed, 2), "depth": depth, "mode": mode,
            "engine": engine, "reached_covers": reached, "unreached_covers": unreached, "log": rel(workdir / f"{name}.log"),
            "workdir": rel(workdir / name)}


def run_lic2x2_formal(depth: int = 16) -> dict:
    """Run inventory, BMC, k-induction, cover and the negative control."""
    sd = RunDir("formal", root=STUDIES)
    wd = sd.path / "work"
    wd.mkdir()
    inv = inventory("rift_lic2x2_formal", LIC2X2_HARNESS)
    inv_neg = inventory("rift_lic2x2_formal", LIC2X2_HARNESS, ["RIFT_FORMAL_NEGATIVE"])
    expected = read_json(EXPECTED_INVENTORY) if EXPECTED_INVENTORY.exists() else None
    tasks = {
        "bmc": _sby(wd, "bmc", "rift_lic2x2_formal", LIC2X2_HARNESS, "bmc", depth),
        "prove": _sby(wd, "prove", "rift_lic2x2_formal", LIC2X2_HARNESS, "prove", depth),
        "prove_stall_le3": _sby(wd, "prove_stall", "rift_lic2x2_formal", LIC2X2_HARNESS, "prove", depth, ["RIFT_FORMAL_STALL_BOUND"]),
        "cover": _sby(wd, "cover", "rift_lic2x2_formal", LIC2X2_HARNESS, "cover", depth),
        "negative_control": _sby(wd, "neg", "rift_lic2x2_formal", LIC2X2_HARNESS, "bmc", depth, ["RIFT_FORMAL_NEGATIVE"]),
    }
    problems = []
    if not inv.get("ok"):
        problems.append("elaboration failed")
    else:
        if inv["blackboxes"]:
            problems.append(f"{inv['blackboxes']} unexpected blackboxes")
        if expected and {k: inv[k] for k in ("asserts", "assumes", "covers")} != expected["lic2x2"]:
            problems.append(f"inventory {inv} differs from frozen expected {expected['lic2x2']}")
        if not inv["asserts"] or not inv["covers"]:
            problems.append("zero asserts or covers (vacuous harness)")
    if inv_neg.get("ok") and inv.get("ok") and inv_neg["asserts"] != inv["asserts"] + 1:
        problems.append("negative-control harness does not add exactly one assertion")
    if tasks["cover"]["outcome"] != "COVERS_REACHED":
        problems.append("not all reachability covers were reached (possible vacuity)")
    if tasks["negative_control"]["outcome"] != "COUNTEREXAMPLE":
        problems.append("negative control did not produce a counterexample: checking path not demonstrated")
    harness_valid = not problems
    result = {
        "schema_version": 1,
        "kind": "formal_local",
        "harness": rel(LIC2X2_HARNESS),
        "harness_digest": file_digest(LIC2X2_HARNESS),
        "top": "rift_lic2x2_formal",
        "configuration": "LIC 2x2, AddrMemWidth=11, RespLat=1, NumPar=1",
        "frontend": "yosys-slang (plugin slang.so) via SBY; VERILATOR undefined; vendor assertions: 0 $check cells elaborated",
        "properties": [{"id": i, "statement": s} for i, s in PROPERTIES],
        "covers": [{"id": i, "statement": s} for i, s in COVERS],
        "assumptions": ASSUMPTIONS,
        "inventory": inv,
        "inventory_negative_control": inv_neg,
        "expected_inventory": expected["lic2x2"] if expected else None,
        "tasks": tasks,
        "harness_valid": harness_valid,
        "harness_problems": problems,
        "claims": {
            "all_properties": (tasks["prove"]["outcome"] if harness_valid else "HARNESS_INVALID"),
            "all_properties_assumptions": "listed assumptions only",
            "all_properties_stall_le3": (tasks["prove_stall_le3"]["outcome"] if harness_valid else "HARNESS_INVALID"),
            "all_properties_stall_le3_assumptions": "listed assumptions plus: every bank stall lasts at most 3 consecutive cycles",
            "bounded": (tasks["bmc"]["outcome"] if harness_valid else "HARNESS_INVALID"),
            "bound_cycles": depth,
        },
        "scope_note": "Transport/response properties of the RTL harness under the listed assumptions. No memory-content, progress, BFLY, or fast-model claim.",
    }
    sd.write_json("formal_result.json", result)
    sd.finalize({"schema_version": 1, "kind": "formal_local", "status": result["claims"]["all_properties"], "observation_role": "FORMAL_PROPERTY_RESULT",
                 "evidence_basis": "EXECUTED_ARTIFACT", "tags": ["formal"]})
    result["study_id"] = sd.run_id
    return result


# ---------------------------------------------------------------------------
# B3: bounded SMT conflict search
# ---------------------------------------------------------------------------
def _parse_vcd_banks(vcd: Path) -> list[int] | None:
    txt = vcd.read_text()
    ids = {}
    for m in re.finditer(r"\$var\s+\w+\s+(\d+)\s+(\S+)\s+(\S+)(?:\s+\[[^\]]*\])?\s+\$end", txt):
        width, ident, name = m.groups()
        if name.startswith("bank_c"):
            ids[ident] = name
    vals = {}
    body = txt.split("$enddefinitions", 1)[-1]
    for m in re.finditer(r"b([01xz]+)\s+(\S+)", body):
        v, ident = m.groups()
        if ident in ids and ids[ident] not in vals:
            vals[ids[ident]] = int(v.replace("x", "0").replace("z", "0"), 2)
    out = []
    for i in range(8):
        for key in (f"bank_c[{i}]", f"bank_c<{i}>", f"bank_c_{i}"):
            if key in vals:
                out.append(vals[key])
                break
    if len(out) == 8:
        return out
    # packed fallback: a single 32-bit vector
    for name, v in vals.items():
        if name == "bank_c":
            return [(v >> (4 * i)) & 0xF for i in range(8)]
    return None


def b3_search_next(excluded: list[list[int]], workdir: Path, depth: int = 4, timeout: int = 300) -> dict:
    """Find one new request vector with an internal-conflict acceptance shortfall."""
    workdir.mkdir(parents=True, exist_ok=True)
    inc = workdir / "rift_b3_exclusions.svh"
    lines = []
    for vec in excluded:
        cond = " && ".join(f"bank_c[{i}] == 4'd{v}" for i, v in enumerate(vec))
        lines.append(f"    assume (!({cond}));")
    inc.write_text("\n".join(lines) + "\n")
    name = f"b3_{len(excluded):03d}"
    res = _sby(workdir, name, "rift_bfly_conflict_search", B3_HARNESS, "cover", depth, timeout=timeout, include_files=[inc])
    vec = None
    traces = sorted((workdir / name).glob("engine_*/trace*.vcd"))
    if res["outcome"] == "COVERS_REACHED" and traces:
        vec = _parse_vcd_banks(traces[0])
    res["vector"] = vec
    # The elaborated SMT model is regenerable from the locked sources; keep logs and traces only.
    shutil.rmtree(workdir / name / "model", ignore_errors=True)
    return res
