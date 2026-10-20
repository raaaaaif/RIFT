"""Cycle engine shared by the fast models.

It implements the written workload contract independently of the C++ driver:
each initiator presents at most one request, holds it until accepted, and
releases its next operation according to the operation's release rule. A
network object decides which offering initiators are accepted each cycle.
The engine emits events in the same schema as the RTL runner so that the
independent checker evaluates both identically.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from rift.contracts.workload import CompiledWorkload

RESET_CYCLES = 4


def memory_word(q: int) -> int:
    """Model-side memory abstraction (functional reads are not timing-relevant)."""
    return ((q * 0x9E3779B1) ^ 0xA5A55A5A) & 0xFFFFFFFF


class Network:
    """Interface: decide acceptances for one cycle, then advance internal state."""

    num_in: int
    num_out: int

    def reset(self) -> None:
        raise NotImplementedError

    def cycle(self, offers: dict[int, int], bank_grant: list[bool]) -> set[int]:
        """offers: initiator -> logical word index q. Returns accepted initiators.

        Each network applies its own (declared) address-to-bank mapping.

        Must also apply the clock edge to internal state (arbiter priorities,
        LFSR) using the same acceptance decision.
        """
        raise NotImplementedError


@dataclass
class ModelRun:
    status: str
    makespan: int | None
    accepted: int
    completed: int
    last_response_cycle: int | None
    elapsed_seconds: float
    events: list = field(default_factory=list)


def simulate(
    net: Network,
    compiled: CompiledWorkload,
    *,
    run_id: str = "model",
    resp_lat: int = 1,
    timeout: int = 4096,
    record_events: bool = True,
    stalls: tuple = (),
) -> ModelRun:
    t0 = time.perf_counter()
    n_in, n_out = net.num_in, net.num_out
    net.reset()
    ev = []
    if record_events:
        for c in range(RESET_CYCLES):
            ev.append({"schema_version": 1, "run_id": run_id, "cycle": c, "sample_phase": "pre_rise",
                       "event_kind": "reset", "master": None, "operation_index": None, "byte_address": None})
    first_release = RESET_CYCLES
    per = compiled.per_master
    nxt = [0] * n_in
    # state: 0 waiting, 1 offering, 2 done
    state = [0 if per[m] else 2 for m in range(n_in)]
    earliest = [first_release + (per[m][0].gap if per[m] else 0) for m in range(n_in)]
    release_known = [True] * n_in
    pending: list[list] = []  # [due_cycle, master, op]
    done = sum(1 for s in state if s == 2)
    accepted = completed = 0
    last_resp = None
    c = first_release
    stall_set = {}
    for b, start, length in stalls:
        for t in range(start, start + length):
            stall_set.setdefault(t, set()).add(b)

    while True:
        offers = {}
        for m in range(n_in):
            if state[m] == 0 and release_known[m] and c >= earliest[m]:
                state[m] = 1
                if record_events:
                    op = per[m][nxt[m]]
                    q = op.byte_address >> 2
                    ev.append({"schema_version": 1, "run_id": run_id, "cycle": c, "sample_phase": "pre_rise",
                               "event_kind": "offer", "master": m, "operation_index": op.index,
                               "byte_address": op.byte_address, "bank": q % n_out, "row": q // n_out})
            if state[m] == 1:
                offers[m] = per[m][nxt[m]].byte_address >> 2
        # responses due this cycle
        responded = []
        if pending:
            keep = []
            for item in pending:
                if item[0] == c:
                    m, op = item[1], item[2]
                    completed += 1
                    last_resp = c
                    responded.append((m, op.index))
                    if record_events:
                        q = op.byte_address >> 2
                        ev.append({"schema_version": 1, "run_id": run_id, "cycle": c, "sample_phase": "pre_rise",
                                   "event_kind": "complete", "master": m, "operation_index": op.index,
                                   "byte_address": op.byte_address, "bank": q % n_out, "row": q // n_out,
                                   "read_data": memory_word(q)})
                else:
                    keep.append(item)
            pending = keep
        stalled = stall_set.get(c, ())
        bank_grant = [b not in stalled for b in range(n_out)]
        granted = net.cycle(offers, bank_grant) if offers else net.cycle({}, bank_grant)
        for m in sorted(granted):
            op = per[m][nxt[m]]
            accepted += 1
            if record_events:
                q = op.byte_address >> 2
                ev.append({"schema_version": 1, "run_id": run_id, "cycle": c, "sample_phase": "pre_rise",
                           "event_kind": "accept", "master": m, "operation_index": op.index,
                           "byte_address": op.byte_address, "bank": q % n_out, "row": q // n_out})
            pending.append([c + resp_lat, m, op])
        # post-edge release updates
        for m, idx in responded:
            # a response-dependent operation waits for its immediate predecessor's response
            if state[m] == 0 and not release_known[m] and idx == nxt[m] - 1:
                release_known[m] = True
                earliest[m] = c + 1 + per[m][nxt[m]].gap
        for m in granted:
            nxt[m] += 1
            if nxt[m] >= len(per[m]):
                state[m] = 2
                done += 1
            else:
                state[m] = 0
                op = per[m][nxt[m]]
                if op.release == "after_accept":
                    release_known[m] = True
                    earliest[m] = c + 1 + op.gap
                else:
                    release_known[m] = False
        active = c - first_release + 1
        c += 1
        if done == n_in and not pending:
            status = "COMPLETED"
            break
        if active >= timeout:
            status = "TIMEOUT"
            break
    if record_events:
        ev.sort(key=lambda e: (e["cycle"], {"reset": 0, "offer": 1, "complete": 2, "accept": 3}.get(e["event_kind"], 4)))
    makespan = (last_resp - first_release + 1) if (status == "COMPLETED" and last_resp is not None) else None
    return ModelRun(status, makespan, accepted, completed, last_resp, time.perf_counter() - t0, ev)
