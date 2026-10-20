"""Measured internal butterfly activity from a diagnostic trace of the reference RTL.

A diagnostic run executes the same workload on a trace-enabled build of the
unchanged sources (same reference epoch). Its boundary events must equal the
reference run's events; otherwise the diagnostic is rejected. Internal signals
are read from the FST trace (converted with the bundled fst2vcd):

  bfly_net.router_req_in / router_gnt_out   [level][router][input port]
  bfly_net.router_req_out / router_gnt_in   [level][router][output port]
  lfsr_i.out_q                              external arbitration priority

Every value is sampled at the pre-rise phase (state just before rising edge c),
matching the boundary sampling convention. The input-port mapping is validated
by checking router_req_in at level 0 against the boundary offers of each cycle.
Internal signals are supplementary diagnostics, never substitutes for the
boundary observations used by the evaluator.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from rift.contracts.config import ArchConfig, load_config
from rift.contracts.workload import validate_and_compile
from rift.model.networks import Butterfly
from rift.paths import RUNS
from rift.rtl import run_rtl
from rift.store import load_events
from rift.toolchain import tool_env

SIGNALS = ("router_req_in", "router_req_out", "router_gnt_in", "router_gnt_out")


def parse_vcd(text: str) -> tuple[dict, list[tuple[int, dict]]]:
    """Return {name: (id, width)} for wanted signals and per-rising-edge snapshots."""
    ids: dict[str, str] = {}
    widths: dict[str, int] = {}
    scope: list[str] = []
    header, _, body = text.partition("$enddefinitions")
    for line in header.splitlines():
        line = line.strip()
        if line.startswith("$scope"):
            scope.append(line.split()[2])
        elif line.startswith("$upscope"):
            scope.pop()
        elif line.startswith("$var"):
            parts = line.split()
            width, ident, name = int(parts[2]), parts[3], parts[4]
            path = ".".join(scope + [name])
            if path == "TOP.clk_i":
                ids["clk"], widths["clk"] = ident, 1
            elif "i_bfly_net" in scope and name in SIGNALS and scope[-1] == "i_bfly_net":
                ids[name], widths[name] = ident, width
            elif "lfsr_i" in scope and name == "out_q":
                ids["lfsr_out_q"], widths["lfsr_out_q"] = ident, width
    by_id = {v: k for k, v in ids.items()}
    state = {k: 0 for k in ids}
    snaps: list[tuple[int, dict]] = []
    edge = 0
    block: list[tuple[str, int]] = []

    def flush():
        nonlocal edge, block
        clk_rises = any(n == "clk" and v == 1 for n, v in block) and state.get("clk") == 0
        if clk_rises:
            snaps.append((edge, dict(state)))
            edge += 1
        for n, v in block:
            state[n] = v
        block = []

    toks = body.split()
    i = 0
    while i < len(toks):
        tok = toks[i]
        if tok.startswith("$"):
            i += 1
        elif tok.startswith("#"):
            flush()
            i += 1
        elif tok[0] in "bBrR":
            ident = toks[i + 1] if i + 1 < len(toks) else ""
            if ident in by_id and tok[0] in "bB":
                block.append((by_id[ident], int(re.sub("[xzXZ]", "0", tok[1:]), 2)))
            i += 2
        else:
            ident = tok[1:]
            if ident in by_id:
                block.append((by_id[ident], 1 if tok[0] == "1" else 0))
            i += 1
    flush()
    return {k: (ids[k], widths[k]) for k in ids}, snaps


def _bit(v: int, level: int, router: int, port: int, routers: int, radix: int) -> int:
    return (v >> ((level * routers + router) * radix + port)) & 1


def run_diagnostic(config: ArchConfig, workload: dict, reference_run_id: str, tags: tuple = ()) -> dict:
    comp = validate_and_compile(workload, config)
    r = run_rtl(config, comp, fst=True, tags=("diagnostic",) + tags,
                extra_manifest={"diagnostic_of": reference_run_id, "observation_role": "RTL_REFERENCE_OBSERVATION",
                                "diagnostic_note": "trace-enabled build of the unchanged reference sources; internal signals are supplementary"})
    return {"run_id": r["run_id"], "status": r["check"]["status"]}


def diagnostic_view(case_id: str, diag_run_id: str, reference_run_id: str, config_id: str) -> dict:
    cfg = load_config(config_id)
    radix = {"BFLY4": 4, "BFLY2": 2}[cfg.topology]
    net = Butterfly(cfg.num_in, cfg.num_out, radix)
    levels, routers = net.levels, net.routers
    d = RUNS / diag_run_id
    vcd = subprocess.run(["fst2vcd", str(d / "trace.fst")], capture_output=True, text=True, env=tool_env(), check=True).stdout
    sig, snaps = parse_vcd(vcd)
    diag_events = load_events(d / ("events.jsonl" if (d / "events.jsonl").exists() else "events.jsonl.gz"))
    ref_dir = RUNS / reference_run_id
    ref_events = load_events(ref_dir / ("events.jsonl" if (ref_dir / "events.jsonl").exists() else "events.jsonl.gz"))
    strip = lambda evs: [(e["cycle"], e["event_kind"], e.get("master"), e.get("operation_index")) for e in evs]
    equivalent = strip(diag_events) == strip(ref_events)

    offers: dict[int, dict] = {}
    for e in diag_events:
        if e["event_kind"] in ("offer", "accept"):
            offers.setdefault((e["master"], e["operation_index"]), {})[e["event_kind"]] = e
    pending: dict[int, dict[int, int]] = {}  # cycle -> master -> bank
    for (m, _), ev in offers.items():
        if "offer" in ev and "accept" in ev:
            for c in range(ev["offer"]["cycle"], ev["accept"]["cycle"] + 1):
                pending.setdefault(c, {})[m] = ev["offer"]["bank"]
    port_of = {m: net.inmap[m] for m in range(cfg.num_in)}
    master_at = {v: k for k, v in port_of.items()}
    last = max((e["cycle"] for e in diag_events if e["event_kind"] == "complete"), default=4)
    window = (4, last)
    mapping_mismatch = 0
    outputs: dict[tuple, dict] = {}
    for c, st in snaps:
        if c < window[0] or c > window[1]:
            continue
        rin, rout, gin, gout = (st.get(n, 0) for n in SIGNALS)
        offering = pending.get(c, {})
        for m, (r, p) in port_of.items():
            if _bit(rin, 0, r, p, routers, radix) != (1 if m in offering else 0):
                mapping_mismatch += 1
        for r in range(routers):
            for s in range(radix):
                key = (0, r, s)
                o = outputs.setdefault(key, {"level": 0, "router": r, "output": s, "cycles": []})
                reqs = [m for m, b in offering.items() if port_of[m][0] == r and net._port(b, 0) == s]
                winner = None
                for m in reqs:
                    if _bit(gout, 0, r, port_of[m][1], routers, radix):
                        winner = m
                fwd = bool(_bit(rout, 0, r, s, routers, radix))
                if reqs or fwd:
                    o["cycles"].append({"c": c, "requesters": sorted(reqs), "forwarded": fwd,
                                        "granted": bool(_bit(gin, 0, r, s, routers, radix)), "winner": winner})
    out_list = []
    for (l, r, s), o in sorted(outputs.items()):
        cyc = o["cycles"]
        banks = [b for b in range(cfg.num_out) if net._port(b, 0) == s]
        out_list.append({**o, "label": f"router {r} · output {s}", "banks": banks,
                         "inputs": sorted(m for m, (rr, _) in port_of.items() if rr == r),
                         "requests_passed": sum(1 for x in cyc if x["granted"]),
                         "conflict_cycles": sum(1 for x in cyc if len(x["requesters"]) >= 2),
                         "max_requesters": max((len(x["requesters"]) for x in cyc), default=0)})
    lfsr = [{"c": c, "prio": st.get("lfsr_out_q", 0)} for c, st in snaps if window[0] <= c <= window[1]]
    return {
        "schema_version": 1,
        "case_id": case_id,
        "diagnostic_run_id": diag_run_id,
        "reference_run_id": reference_run_id,
        "config_id": config_id,
        "topology": cfg.topology,
        "evidence_basis": "EXECUTED_ARTIFACT",
        "observation_role": "RTL_REFERENCE_OBSERVATION",
        "supplementary": True,
        "boundary_events_identical_to_reference": equivalent,
        "mapping_check": {"signal": "router_req_in[0][router][port] vs boundary offers", "mismatches": mapping_mismatch,
                          "cycles_checked": window[1] - window[0] + 1},
        "signals": {n: f"tcdm_interconnect.gen_bfly.gen_bfly2_net[0].i_bfly_net.{n}" for n in SIGNALS} | {"priority": "lfsr_i.out_q"},
        "bit_layout": "flattened [level][router][port], bit = (level*routers + router)*radix + port",
        "window": list(window),
        "initiators": [{"master": m, "router": r, "port": p} for m, (r, p) in sorted(port_of.items())],
        "first_stage_outputs": out_list,
        "priority": lfsr,
        "valid": equivalent and mapping_mismatch == 0,
    }
