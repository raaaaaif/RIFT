"""Independent event checker.

Recomputes functional validity and cost from raw boundary events using only
the workload contract, the configuration's address mapping and its own copy of
the memory function. It deliberately imports nothing from the RTL runner or
the fast models; their summaries are compared against the recomputation and a
disagreement invalidates the run.
"""

from __future__ import annotations

from collections import defaultdict

from rift.contracts.config import ArchConfig
from rift.contracts.workload import CompiledWorkload

EVENT_KINDS = {"offer", "accept", "complete", "reset", "monitor_failure"}
REQUIRED = ("schema_version", "run_id", "cycle", "sample_phase", "event_kind", "master", "operation_index", "byte_address")
MAX_LISTED = 40


def expected_word(q: int) -> int:
    return ((q * 0x9E3779B1) ^ 0xA5A55A5A) & 0xFFFFFFFF


def check_events(
    compiled: CompiledWorkload,
    config: ArchConfig,
    events: list[dict],
    runner_summary: dict | None,
    runner_kind: str,  # "rtl" or "model"
    reset_cycles: int = 4,
    resp_lat: int = 1,
    timeout: int = 4096,
) -> dict:
    violations: list[dict] = []
    counts: dict[str, int] = defaultdict(int)

    def bad(code: str, detail: str, **kw):
        counts[code] += 1
        if len(violations) < MAX_LISTED:
            violations.append({"code": code, "detail": detail, **kw})

    if not events:
        return _result("TOOL_ERROR", compiled, None, None, {}, [{"code": "NO_EVENTS", "detail": "no events recorded"}], {"NO_EVENTS": 1}, runner_summary, None)

    run_ids = {e.get("run_id") for e in events}
    if len(run_ids) != 1:
        bad("MIXED_RUN_IDS", f"{len(run_ids)} run identities in one event stream")

    ops = {(op.master, op.index): op for op in compiled.operations()}
    seen: dict[str, dict] = {"offer": {}, "accept": {}, "complete": {}}
    resets = []
    monitor_failures = []
    last_cycle = -1
    bank_cycle_accepts: dict[tuple[int, int], int] = defaultdict(int)

    for i, e in enumerate(events):
        missing = [k for k in REQUIRED if k not in e]
        if missing or e.get("schema_version") != 1 or e.get("event_kind") not in EVENT_KINDS:
            bad("MALFORMED_EVENT", f"event {i} malformed", index=i)
            continue
        c = e["cycle"]
        if not isinstance(c, int) or c < last_cycle:
            bad("NON_MONOTONIC_CYCLE", f"event {i} cycle {c} after {last_cycle}", index=i)
            continue
        last_cycle = c
        kind = e["event_kind"]
        if kind == "reset":
            resets.append(c)
            continue
        if kind == "monitor_failure":
            monitor_failures.append(e)
            bad("MONITOR_FAILURE", f"{e.get('monitor_id')} at cycle {c}: {e.get('detail')}", cycle=c)
            continue
        key = (e["master"], e["operation_index"])
        op = ops.get(key)
        if op is None:
            bad("UNKNOWN_OPERATION", f"event for nonexistent operation {key}", cycle=c)
            continue
        if key in seen[kind]:
            bad("DUPLICATE_EVENT", f"second {kind} for {op.op_id}", cycle=c, op_id=op.op_id)
            continue
        seen[kind][key] = e
        if e["byte_address"] != op.byte_address:
            bad("ADDRESS_MISMATCH", f"{op.op_id} event address {e['byte_address']} != {op.byte_address}", cycle=c, op_id=op.op_id)
        q = op.byte_address >> 2
        if e.get("bank") is not None and e["bank"] != q % config.num_out:
            bad("BANK_MAPPING", f"{op.op_id} bank {e['bank']} != {q % config.num_out}", cycle=c, op_id=op.op_id)
        if e.get("row") is not None and e["row"] != q // config.num_out:
            bad("ROW_MAPPING", f"{op.op_id} row {e['row']} != {q // config.num_out}", cycle=c, op_id=op.op_id)
        if kind == "accept":
            bank_cycle_accepts[(c, q % config.num_out)] += 1
        if kind == "complete":
            if e.get("read_data") != expected_word(q):
                bad("DATA_MISMATCH", f"{op.op_id} read_data {e.get('read_data')} != f({q})={expected_word(q)}", cycle=c, op_id=op.op_id)

    # Reset contract
    if resets != list(range(reset_cycles)):
        bad("RESET_SEQUENCE", f"reset events {resets[:8]} differ from cycles 0..{reset_cycles - 1}")
    first_release = reset_cycles

    for (c, b), n in bank_cycle_accepts.items():
        if n > 1:
            bad("BANK_DOUBLE_ACCEPT", f"bank {b} accepted {n} operations in cycle {c}", cycle=c)

    # Per-operation lifecycle and release-rule conformance
    incomplete = 0
    acc_cycles = []
    for m, mops in enumerate(compiled.per_master):
        prev = None
        for op in mops:
            key = (m, op.index)
            o, a, r = seen["offer"].get(key), seen["accept"].get(key), seen["complete"].get(key)
            if o is None or a is None or r is None:
                incomplete += 1
                if incomplete <= 3:
                    bad("INCOMPLETE_OPERATION", f"{op.op_id} offer={o is not None} accept={a is not None} complete={r is not None}", op_id=op.op_id)
                prev = None
                continue
            oc, ac, rc = o["cycle"], a["cycle"], r["cycle"]
            acc_cycles.append(ac)
            if ac < oc:
                bad("ACCEPT_BEFORE_OFFER", f"{op.op_id} accepted {ac} before offer {oc}", op_id=op.op_id)
            if rc != ac + resp_lat:
                bad("RESPONSE_LATENCY", f"{op.op_id} response at {rc}, acceptance {ac}, RespLat={resp_lat}", op_id=op.op_id)
            if op.index == 0:
                expected_offer = first_release + op.gap
            elif prev is not None:
                base = prev[1] if op.release == "after_accept" else prev[2]
                expected_offer = base + 1 + op.gap
            else:
                expected_offer = None
            if expected_offer is not None and oc != expected_offer:
                bad("RELEASE_RULE", f"{op.op_id} offered at {oc}; contract releases it at {expected_offer}", op_id=op.op_id)
            prev = (oc, ac, rc)
        if incomplete > 3:
            counts["INCOMPLETE_OPERATION"] = incomplete

    completes = [e["cycle"] for e in seen["complete"].values()]
    last_resp = max(completes) if completes else None
    makespan = (last_resp - first_release + 1) if last_resp is not None else None

    status = "COMPLETED"
    timed_out = (runner_summary or {}).get("exit_status") == "TIMEOUT" or (makespan is not None and makespan > timeout)
    protocol_codes = set(counts) - {"DATA_MISMATCH"}
    if timed_out:
        status = "TIMEOUT"
    elif protocol_codes:
        status = "HARNESS_INVALID" if runner_kind == "rtl" else "MODEL_ERROR"
    elif counts.get("DATA_MISMATCH"):
        status = "FUNCTIONAL_MISMATCH" if runner_kind == "rtl" else "MODEL_ERROR"

    agreement = None
    if runner_summary is not None:
        agreement = {
            "makespan": runner_summary.get("makespan") == (makespan if status == "COMPLETED" else None)
            or (status != "COMPLETED"),
            "accepted": runner_summary.get("accepted") == len(seen["accept"]),
            "completed": runner_summary.get("completed") == len(seen["complete"]),
            "runner_exit_status": runner_summary.get("exit_status"),
        }
        if status == "COMPLETED" and not all(agreement[k] for k in ("makespan", "accepted", "completed")):
            bad("SUMMARY_DISAGREES", f"runner summary {runner_summary.get('makespan')}/{runner_summary.get('accepted')}/{runner_summary.get('completed')} vs events")
            status = "HARNESS_INVALID" if runner_kind == "rtl" else "MODEL_ERROR"
        if status == "COMPLETED" and runner_summary.get("exit_status") not in ("COMPLETED",):
            bad("RUNNER_STATUS", f"runner reported {runner_summary.get('exit_status')} but events are clean")
            status = "HARNESS_INVALID" if runner_kind == "rtl" else "MODEL_ERROR"

    extra = {
        "first_release_cycle": first_release,
        "last_response_cycle": last_resp,
        "accepted": len(seen["accept"]),
        "completed": len(seen["complete"]),
        "offered": len(seen["offer"]),
        "acceptance_cycles_distinct": len(set(acc_cycles)),
        "acceptance_window": (max(acc_cycles) - first_release + 1) if acc_cycles else None,
        "monitor_failures": len(monitor_failures),
    }
    return _result(status, compiled, makespan if status == "COMPLETED" else None, makespan, extra, violations, dict(counts), runner_summary, agreement)


def _result(status, compiled, makespan, raw_makespan, extra, violations, counts, runner_summary, agreement):
    return {
        "schema_version": 1,
        "checker": "rift.evaluate.checker/v1",
        "status": status,
        "functional_valid": status == "COMPLETED",
        "workload_digest": compiled.digest,
        "expected_operations": compiled.total_ops,
        "makespan": makespan,
        "makespan_from_events_unvalidated": raw_makespan,
        "metric_id": "inclusive_cycle_makespan_v1",
        **extra,
        "violation_counts": counts,
        "violations": violations,
        "summary_agreement": agreement,
    }
