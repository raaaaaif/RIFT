"""Gate 0A: LIC 2x2 transport and instrumentation validation.

Each check executes the real Verilator harness and evaluates the recorded run
with the independent checker. A gate passes only if every check passes; a pass
establishes harness/tool semantics only, not any topology or model claim.
"""

from __future__ import annotations

from rift.contracts.config import load_config
from rift.contracts.workload import read_sequences, repeat_read, validate_and_compile, WorkloadError
from rift.evaluate.checker import check_events, expected_word
from rift.rtl import run_rtl
from rift.store import load_events

SV_MONITORS = ["SV0_GNT_IMPLIES_REQ", "SV1_BANK_SINGLE_ACCEPT", "SV2_ACCEPT_CONSERVATION", "SV3_PAYLOAD_ROUTING",
               "SV4_RESP_CORRESPONDENCE", "SV5_LIC_WORK_CONSERVING", "SV6_NO_SPURIOUS_BANK_REQ"]


def _seq(per):
    return read_sequences([[{"byte_address": a} if isinstance(a, int) else a for a in ops] for ops in per])


def _events_by(run, kind):
    ev = load_events(run["path"] / ("events.jsonl" if (run["path"] / "events.jsonl").exists() else "events.jsonl.gz"))
    return [e for e in ev if e["event_kind"] == kind]


def _mon(run, mid):
    for m in run["runner_summary"]["monitors"]:
        if m["id"] == mid:
            return m
    return None


def gate0a(config_id: str = "lic2x2") -> dict:
    cfg = load_config(config_id)
    checks = []

    def record(name, runs, expectation, observed, passed):
        checks.append({
            "check": name,
            "run_ids": [r["run_id"] for r in runs],
            "expectation": expectation,
            "observed": observed,
            "passed": bool(passed),
        })

    def run(per, **kw):
        c = validate_and_compile(_seq(per), cfg)
        return run_rtl(cfg, c, tags=("gate0a",), **kw)

    # 1. Single read: sampling convention and data
    r = run([[12], []])
    acc = _events_by(r, "accept")
    cmp_ = _events_by(r, "complete")
    ok = (r["check"]["status"] == "COMPLETED" and len(acc) == 1 and acc[0]["cycle"] == 4
          and len(cmp_) == 1 and cmp_[0]["cycle"] == 5 and cmp_[0]["read_data"] == expected_word(3)
          and r["check"]["makespan"] == 2)
    record("single_read_sampling", [r],
           "offer and accept at first release cycle 4 (A_4); response at V_5 with f(3); inclusive makespan 2",
           {"accept_cycle": acc[0]["cycle"] if acc else None, "complete_cycle": cmp_[0]["cycle"] if cmp_ else None,
            "read_data": cmp_[0].get("read_data") if cmp_ else None, "makespan": r["check"]["makespan"]}, ok)

    # 2. Reset without spurious activity
    c0 = _mon(r, "C0_RESET_QUIET")
    record("reset_quiet", [r], "4 reset cycles evaluated with no grant/response",
           {"evaluations": c0["evaluations"], "failures": c0["failures"]}, c0["evaluations"] == 4 and c0["failures"] == 0)

    # 3. Two independent banks accepted in the same cycle
    r = run([[0], [4]])
    acc = _events_by(r, "accept")
    ok = r["check"]["status"] == "COMPLETED" and sorted(e["cycle"] for e in acc) == [4, 4]
    record("two_independent_banks", [r], "both initiators accepted in cycle 4", [(e["master"], e["cycle"]) for e in acc], ok)

    # 4. Same-bank contention without duplicate acceptance
    r = run([[0], [8]])
    acc = _events_by(r, "accept")
    cycles = sorted(e["cycle"] for e in acc)
    ok = r["check"]["status"] == "COMPLETED" and cycles == [4, 5] and r["check"]["violation_counts"] == {}
    record("same_bank_contention", [r], "bank 0 accepts one initiator per cycle: cycles 4 and 5", cycles, ok)

    # 5. Stalled bank: held request stays stable, completes after release
    r = run([[0], []], stalls=((0, 4, 3),))
    acc = _events_by(r, "accept")
    c1 = _mon(r, "C1_REQUEST_STABILITY")
    ok = (r["check"]["status"] == "COMPLETED" and acc and acc[0]["cycle"] == 7 and c1["failures"] == 0
          and c1["evaluations"] > 0)
    record("bank_stall_request_stability", [r], "bank 0 stalled cycles 4-6; request held stable and accepted at 7",
           {"accept_cycle": acc[0]["cycle"] if acc else None, "stability_failures": c1["failures"]}, ok)

    # 6. Boundary mapping + consecutive different-row reads on one bank
    r = run([[0, 8, 16, 24, 16376], [16380, 4, 12]])
    cmp_ = _events_by(r, "complete")
    data_ok = all(e["read_data"] == expected_word(e["byte_address"] >> 2) for e in cmp_)
    last = [e for e in cmp_ if e["byte_address"] == 16380]
    ok = (r["check"]["status"] == "COMPLETED" and data_ok and last and last[0]["bank"] == 1 and last[0]["row"] == 2047)
    record("address_mapping_and_registered_reads", [r],
           "rows 0..3 of bank 0 read back-to-back plus last words 4094/4095; all data equal f(q); word 4095 -> bank 1 row 2047",
           {"completes": len(cmp_), "data_ok": data_ok, "last_word_bank_row": (last[0]["bank"], last[0]["row"]) if last else None}, ok)

    # 7. Response ownership: simultaneous responses carry each initiator's own data
    r = run([[0, 4, 0], [4, 0, 4]])
    cmp_ = _events_by(r, "complete")
    own = all(e["read_data"] == expected_word(e["byte_address"] >> 2) for e in cmp_)
    ok = r["check"]["status"] == "COMPLETED" and own and len(cmp_) == 6
    record("response_ownership", [r], "every response matches its own operation's logical word", {"completes": len(cmp_), "own_data": own}, ok)

    # 8. Complete drain
    d = _mon(r, "C4_DRAIN_QUIET")
    record("complete_drain", [r], "3 post-completion cycles with no grant or response; all operations accepted/completed once",
           {"drain_evaluations": d["evaluations"], "drain_failures": d["failures"], "accepted": r["check"]["accepted"], "completed": r["check"]["completed"]},
           d["evaluations"] == 3 and d["failures"] == 0 and r["check"]["accepted"] == 6 == r["check"]["completed"])

    # 9. Monitor inventory is nonzero and stable
    ids = [m["id"] for m in r["runner_summary"]["monitors"]]
    record("monitor_inventory", [r], "7 SV wrapper monitors + 7 C++ monitors evaluated for LIC", ids, len(ids) == 14 and all(m["evaluations"] > 0 for m in r["runner_summary"]["monitors"]))

    # 10. Each SV monitor detects an injected fault in its own view
    rich = [[0, 8, 4], [4, 12, 0, 16380]]
    for k, mid in enumerate(SV_MONITORS):
        rr = run(rich, sv_inject=1 << k)
        m = _mon(rr, mid)
        record(f"injected_fault_detected:{mid}", [rr], f"monitor {mid} fires and the run is rejected (HARNESS_INVALID)",
               {"failures": m["failures"] if m else None, "status": rr["check"]["status"]},
               m is not None and m["failures"] > 0 and rr["check"]["status"] == "HARNESS_INVALID")

    # 11. Driver-side injected faults
    rr = run([[0], [8, 8]], inject="unstable_request")
    m = _mon(rr, "C1_REQUEST_STABILITY")
    record("injected_fault_detected:C1_REQUEST_STABILITY", [rr], "changing a held request is detected and rejected",
           {"failures": m["failures"], "status": rr["check"]["status"]}, m["failures"] > 0 and rr["check"]["status"] == "HARNESS_INVALID")
    rr = run(rich, inject="oracle_offset")
    m = _mon(rr, "C3_RESPONSE_DATA")
    record("injected_fault_detected:C3_RESPONSE_DATA", [rr], "a wrong scoreboard expectation is detected by the driver monitor",
           {"failures": m["failures"], "runner_status": rr["runner_summary"]["exit_status"], "independent_checker_status": rr["check"]["status"]},
           m["failures"] > 0 and rr["runner_summary"]["exit_status"] == "FUNCTIONAL_MISMATCH" and rr["check"]["status"] != "COMPLETED")

    # 12. Timeout path is an incomplete run, never a cost
    rr = run([[0], []], stalls=((0, 4, 1000),), timeout=32)
    record("timeout_classification", [rr], "a never-granting bank yields TIMEOUT with no makespan",
           {"status": rr["check"]["status"], "makespan": rr["check"].get("makespan")}, rr["check"]["status"] == "TIMEOUT" and rr["check"].get("makespan") is None)

    # 13. Invalid workloads are rejected before execution
    rejected = []
    for bad in (repeat_read([2, 4], 1), repeat_read([16384, 0], 1), repeat_read([0, 4, 8], 1), repeat_read([0, 4], 0)):
        try:
            validate_and_compile(bad, cfg)
            rejected.append(False)
        except WorkloadError:
            rejected.append(True)
    record("invalid_workload_rejected", [], "unaligned, out-of-range, wrong initiator count and zero-count workloads rejected", rejected, all(rejected))

    # 14. Independent checker rejects a tampered event stream (broken-harness control)
    good = run([[0, 8], [4]])
    ev = load_events(good["path"] / "events.jsonl")
    c = validate_and_compile(_seq([[0, 8], [4]]), cfg)
    tampered_drop = [e for e in ev if not (e["event_kind"] == "complete" and e["master"] == 1)]
    tampered_shift = [dict(e, cycle=e["cycle"] + 1) if (e["event_kind"] == "complete" and e["master"] == 0 and e["operation_index"] == 1) else e for e in ev]
    tampered_data = [dict(e, read_data=(e.get("read_data", 0) ^ 1)) if e["event_kind"] == "complete" and e["master"] == 0 else e for e in ev]
    s1 = check_events(c, cfg, tampered_drop, good["runner_summary"], "rtl")["status"]
    s2 = check_events(c, cfg, tampered_shift, good["runner_summary"], "rtl")["status"]
    s3 = check_events(c, cfg, tampered_data, None, "rtl")["status"]
    record("checker_rejects_tampered_events", [good], "dropped response -> HARNESS_INVALID; shifted response -> HARNESS_INVALID; corrupted data -> FUNCTIONAL_MISMATCH",
           [s1, s2, s3], s1 == "HARNESS_INVALID" and s2 == "HARNESS_INVALID" and s3 == "FUNCTIONAL_MISMATCH")

    return {
        "schema_version": 1,
        "gate": "0A",
        "config_id": config_id,
        "scope": "Harness and tool semantics only (transport, sampling, mapping, ownership, drain, monitor activity). No topology, model or AI claim.",
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "reference_epoch": good["manifest"]["reference_epoch"],
        "reference": good["manifest"]["reference"],
    }
