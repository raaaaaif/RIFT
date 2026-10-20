"""Semantic workload contract, validator and compiler.

Three program kinds compile into one neutral representation: an ordered list
of logical read operations per initiator, each with a stable operation ID, an
aligned byte address, and a release rule relative to its same-initiator
predecessor ("after_accept" or "after_response") plus a non-negative gap.

* repeat_read and ordered_read_segments are the handoff's Phase 0 kinds and
  imply after_accept with gap 0 (arrival_policy "saturated_after_accept").
* read_sequences is a RIFT schema-v1 extension used by search and reduction.
  It requires arrival_policy "per_operation_release". Cross-initiator edges,
  stores, races and data-dependent addresses are rejected until supported.

The first operation of every initiator is released at the common first
release cycle plus its gap. A response observed at sample t releases a
response-dependent child no earlier than t+1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rift.contracts.canonical import digest
from rift.contracts.config import ArchConfig

MAX_OPS_PER_MASTER = 1024
MAX_TOTAL_OPS = 4096
MAX_GAP = 64
MAX_REPEAT = 1024


class WorkloadError(ValueError):
    pass


@dataclass(frozen=True)
class Operation:
    master: int
    index: int
    byte_address: int
    release: str  # "after_accept" | "after_response"
    gap: int

    @property
    def op_id(self) -> str:
        return f"m{self.master}:op{self.index:04d}"

    @property
    def word(self) -> int:
        return self.byte_address >> 2


@dataclass(frozen=True)
class CompiledWorkload:
    workload: dict
    digest: str
    masters: int
    per_master: tuple  # tuple[tuple[Operation, ...], ...]

    @property
    def total_ops(self) -> int:
        return sum(len(p) for p in self.per_master)

    def operations(self):
        for ops in self.per_master:
            yield from ops

    def to_text(self) -> str:
        lines = ["RIFT_COMPILED_WORKLOAD 1", f"digest {self.digest}", f"masters {self.masters}"]
        for op in self.operations():
            rel = "A" if op.release == "after_accept" else "R"
            lines.append(f"op {op.master} {op.index} {op.byte_address} {rel} {op.gap}")
        lines.append("end")
        return "\n".join(lines) + "\n"


def _int(v: Any, name: str, lo: int, hi: int) -> int:
    if not isinstance(v, int) or isinstance(v, bool):
        raise WorkloadError(f"{name} must be an integer")
    if v < lo or v > hi:
        raise WorkloadError(f"{name}={v} outside [{lo}, {hi}]")
    return v


def _addr(v: Any, name: str, capacity_words: int, word_bytes: int) -> int:
    a = _int(v, name, 0, capacity_words * word_bytes - word_bytes)
    if a % word_bytes:
        raise WorkloadError(f"{name}={a} is not {word_bytes}-byte aligned")
    return a


def validate_and_compile(workload: dict, config: ArchConfig | None = None) -> CompiledWorkload:
    """Validate a workload object and lower it to the neutral representation.

    If a configuration is given, the initiator count and capacity must match it.
    """
    if not isinstance(workload, dict):
        raise WorkloadError("workload must be an object")
    allowed = {"schema_version", "capacity_words", "word_bytes", "masters", "arrival_policy", "program", "label"}
    extra = set(workload) - allowed
    if extra:
        raise WorkloadError(f"unknown workload fields: {sorted(extra)}")
    if workload.get("schema_version") != 1:
        raise WorkloadError("schema_version must be 1")
    capacity = _int(workload.get("capacity_words"), "capacity_words", 1, 1 << 20)
    word_bytes = _int(workload.get("word_bytes"), "word_bytes", 4, 4)
    masters = _int(workload.get("masters"), "masters", 1, 64)
    if config is not None:
        if masters != config.num_in:
            raise WorkloadError(f"workload has {masters} initiators; configuration {config.config_id} has {config.num_in}")
        if capacity != config.capacity_words:
            raise WorkloadError("workload capacity differs from configuration capacity")
    program = workload.get("program")
    if not isinstance(program, dict):
        raise WorkloadError("program must be an object")
    kind = program.get("kind")
    policy = workload.get("arrival_policy")
    per_master: list[list[Operation]] = [[] for _ in range(masters)]

    if kind == "repeat_read":
        if policy != "saturated_after_accept":
            raise WorkloadError("repeat_read requires arrival_policy saturated_after_accept")
        if set(program) - {"kind", "byte_addresses", "reads_per_master"}:
            raise WorkloadError("unknown repeat_read fields")
        addrs = program.get("byte_addresses")
        if not isinstance(addrs, list) or len(addrs) != masters:
            raise WorkloadError("byte_addresses must list exactly one address per initiator")
        n = _int(program.get("reads_per_master"), "reads_per_master", 1, MAX_REPEAT)
        for m, a in enumerate(addrs):
            a = _addr(a, f"byte_addresses[{m}]", capacity, word_bytes)
            per_master[m] = [Operation(m, k, a, "after_accept", 0) for k in range(n)]

    elif kind == "ordered_read_segments":
        if policy != "saturated_after_accept":
            raise WorkloadError("ordered_read_segments requires arrival_policy saturated_after_accept")
        if set(program) - {"kind", "per_master"}:
            raise WorkloadError("unknown ordered_read_segments fields")
        entries = program.get("per_master")
        if not isinstance(entries, list):
            raise WorkloadError("per_master must be a list")
        seen = set()
        for e in entries:
            if not isinstance(e, dict) or set(e) != {"master", "segments"}:
                raise WorkloadError("each per_master entry needs exactly master and segments")
            m = _int(e["master"], "master", 0, masters - 1)
            if m in seen:
                raise WorkloadError(f"initiator {m} listed more than once")
            seen.add(m)
            segs = e["segments"]
            if not isinstance(segs, list) or not segs:
                raise WorkloadError(f"initiator {m} needs at least one segment")
            ops: list[Operation] = []
            for s in segs:
                if not isinstance(s, dict) or set(s) != {"byte_address", "count"}:
                    raise WorkloadError("segment needs exactly byte_address and count")
                a = _addr(s["byte_address"], "segment.byte_address", capacity, word_bytes)
                c = _int(s["count"], "segment.count", 1, MAX_REPEAT)
                for _ in range(c):
                    ops.append(Operation(m, len(ops), a, "after_accept", 0))
            per_master[m] = ops
        if seen != set(range(masters)):
            raise WorkloadError("ordered_read_segments must list each initiator exactly once")

    elif kind == "read_sequences":
        if policy != "per_operation_release":
            raise WorkloadError("read_sequences requires arrival_policy per_operation_release")
        if set(program) - {"kind", "per_master"}:
            raise WorkloadError("unknown read_sequences fields")
        entries = program.get("per_master")
        if not isinstance(entries, list):
            raise WorkloadError("per_master must be a list")
        seen = set()
        for e in entries:
            if not isinstance(e, dict) or set(e) != {"master", "ops"}:
                raise WorkloadError("each per_master entry needs exactly master and ops")
            m = _int(e["master"], "master", 0, masters - 1)
            if m in seen:
                raise WorkloadError(f"initiator {m} listed more than once")
            seen.add(m)
            if not isinstance(e["ops"], list):
                raise WorkloadError("ops must be a list")
            ops = []
            for k, o in enumerate(e["ops"]):
                if not isinstance(o, dict) or set(o) - {"byte_address", "release", "gap"} or "byte_address" not in o:
                    raise WorkloadError("op needs byte_address and optional release/gap")
                a = _addr(o["byte_address"], "op.byte_address", capacity, word_bytes)
                rel = o.get("release", "after_accept")
                if rel not in ("after_accept", "after_response"):
                    raise WorkloadError(f"unsupported release kind {rel!r}")
                gap = _int(o.get("gap", 0), "op.gap", 0, MAX_GAP)
                ops.append(Operation(m, k, a, rel, gap))
            if len(ops) > MAX_OPS_PER_MASTER:
                raise WorkloadError(f"initiator {m} exceeds {MAX_OPS_PER_MASTER} operations")
            per_master[m] = ops
        if seen != set(range(masters)):
            raise WorkloadError("read_sequences must list each initiator exactly once (ops may be empty)")
    else:
        raise WorkloadError(f"unsupported program kind {kind!r}")

    total = sum(len(p) for p in per_master)
    if total == 0:
        raise WorkloadError("workload has no operations")
    if total > MAX_TOTAL_OPS:
        raise WorkloadError(f"workload exceeds {MAX_TOTAL_OPS} operations")
    return CompiledWorkload(workload, digest(workload), masters, tuple(tuple(p) for p in per_master))


def repeat_read(byte_addresses: list[int], reads_per_master: int, label: str | None = None) -> dict:
    w = {
        "schema_version": 1,
        "capacity_words": 4096,
        "word_bytes": 4,
        "masters": len(byte_addresses),
        "arrival_policy": "saturated_after_accept",
        "program": {"kind": "repeat_read", "byte_addresses": list(byte_addresses), "reads_per_master": reads_per_master},
    }
    if label:
        w["label"] = label
    return w


def read_sequences(per_master_ops: list[list[dict]], label: str | None = None) -> dict:
    w = {
        "schema_version": 1,
        "capacity_words": 4096,
        "word_bytes": 4,
        "masters": len(per_master_ops),
        "arrival_policy": "per_operation_release",
        "program": {
            "kind": "read_sequences",
            "per_master": [{"master": m, "ops": ops} for m, ops in enumerate(per_master_ops)],
        },
    }
    if label:
        w["label"] = label
    return w


def to_read_sequences(compiled: CompiledWorkload, label: str | None = None) -> dict:
    """Express any compiled workload in the read_sequences kind (used by reduction)."""
    per = []
    for ops in compiled.per_master:
        seq = []
        for op in ops:
            o: dict = {"byte_address": op.byte_address}
            if op.release != "after_accept":
                o["release"] = op.release
            if op.gap:
                o["gap"] = op.gap
            seq.append(o)
        per.append(seq)
    return read_sequences(per, label)
