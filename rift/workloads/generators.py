"""Legal workload generators and semantic mutation operators.

Every generator is a pure function of its parameters and an explicit seed,
returns a schema-v1 workload object, and never emits anything the validator
would reject. Semantic operators act on the logical program (addresses,
release rules, gaps, burst structure); they never see RTL outcomes.
"""

from __future__ import annotations

import random

from rift.contracts.workload import read_sequences

WORDS = 4096
MASTERS = 8


def _op(word: int, release: str = "after_accept", gap: int = 0) -> dict:
    o = {"byte_address": (word % WORDS) * 4}
    if release != "after_accept":
        o["release"] = release
    if gap:
        o["gap"] = gap
    return o


def random_legal(seed: int, masters: int = MASTERS, max_ops: int = 24, p_response: float = 0.3, max_gap: int = 3,
                 hot_words: int | None = None) -> dict:
    """Uniform legal random programs (baseline B2)."""
    rng = random.Random(seed)
    per = []
    pool = None if hot_words is None else rng.sample(range(WORDS), hot_words)
    for _ in range(masters):
        n = rng.randint(1, max_ops)
        ops = []
        for _ in range(n):
            w = rng.choice(pool) if pool else rng.randrange(WORDS)
            rel = "after_response" if rng.random() < p_response else "after_accept"
            gap = rng.randint(0, max_gap) if rng.random() < 0.3 else 0
            ops.append(_op(w, rel, gap))
        per.append(ops)
    return read_sequences(per, label=f"random_legal seed={seed}")


def fixed_word_streams(words: list[int], count: int, label: str | None = None) -> dict:
    """Each initiator repeatedly reads one word (repeat_read semantics as read_sequences)."""
    return read_sequences([[_op(w) for _ in range(count)] for w in words], label=label)


def segments(per_master_segments: list[list[tuple[int, int]]], label: str | None = None) -> dict:
    """[(word, count), ...] per initiator, saturated after accept."""
    per = []
    for segs in per_master_segments:
        ops = []
        for w, c in segs:
            ops.extend(_op(w) for _ in range(c))
        per.append(ops)
    return read_sequences(per, label=label)


# ---------------------------------------------------------------------------
# Public, source-informed semantic sweeps (baseline B1). These families are
# parameterised by bank structure knowledge that every arm is given.
# ---------------------------------------------------------------------------
def sweep_family(index: int, count: int = 16) -> dict:
    """Deterministic enumeration of stride/permutation/burst families."""
    families = []
    for stride in (1, 2, 3, 4, 5, 8, 16, 32):
        families.append(("stride", stride))
    for offset in (8, 16, 32, 64):
        families.append(("pair_split", offset))
    for k in (1, 2, 4):
        families.append(("hot_bank", k))
    for perm in range(8):
        families.append(("perm", perm))
    kind, p = families[index % len(families)]
    rot = index // len(families)
    if kind == "stride":
        words = [(i * p + rot) for i in range(MASTERS)]
    elif kind == "pair_split":
        words = [(i // 2) + (i % 2) * p + rot for i in range(MASTERS)]
    elif kind == "hot_bank":
        words = [(i % p) * 16 + (i // p) * 16 * p + rot for i in range(MASTERS)]
    else:
        rng = random.Random(1000 + p)
        base = list(range(MASTERS))
        rng.shuffle(base)
        words = [b + rot * 8 for b in base]
    return fixed_word_streams(words, count, label=f"sweep {kind}={p} rot={rot}")


# ---------------------------------------------------------------------------
# Semantic mutation operators (used by evolutionary and decision-directed arms)
# ---------------------------------------------------------------------------
def _per(w: dict) -> list[list[dict]]:
    return [list(e["ops"]) for e in w["program"]["per_master"]]


def mutate(w: dict, rng: random.Random) -> dict:
    per = [[dict(o) for o in ops] for ops in _per(w)]
    choice = rng.randrange(8)
    m = rng.randrange(len(per))
    if choice == 0 and per[m]:  # retarget one operation
        k = rng.randrange(len(per[m]))
        per[m][k]["byte_address"] = rng.randrange(WORDS) * 4
    elif choice == 1 and per[m]:  # bank-group collision: copy another initiator's bank group
        other = rng.randrange(len(per))
        if per[other]:
            src = per[other][rng.randrange(len(per[other]))]["byte_address"] >> 2
            for o in per[m]:
                o["byte_address"] = ((src & ~0x3) | ((o["byte_address"] >> 2) & 0x3)) % WORDS * 4
    elif choice == 2:  # burst composition: append a burst to one word
        word = rng.randrange(WORDS)
        per[m].extend(_op(word) for _ in range(rng.randint(2, 12)))
    elif choice == 3 and per[m]:  # toggle release dependency
        k = rng.randrange(len(per[m]))
        if per[m][k].get("release") == "after_response":
            per[m][k].pop("release")
        else:
            per[m][k]["release"] = "after_response"
    elif choice == 4 and per[m]:  # release delay
        k = rng.randrange(len(per[m]))
        per[m][k]["gap"] = rng.randint(0, 4)
        if per[m][k]["gap"] == 0:
            per[m][k].pop("gap")
    elif choice == 5 and len(per[m]) > 1:  # shorten
        del per[m][rng.randrange(len(per[m]))]
    elif choice == 6:  # address permutation across initiators
        a, b = rng.randrange(len(per)), rng.randrange(len(per))
        per[a], per[b] = per[b], per[a]
    else:  # shift bank bits of one initiator's stream
        delta = rng.choice([1, 2, 4, 8, 16])
        for o in per[m]:
            o["byte_address"] = (((o["byte_address"] >> 2) + delta) % WORDS) * 4
    for i in range(len(per)):
        if len(per[i]) > 64:
            per[i] = per[i][:64]
    if sum(len(p) for p in per) == 0:
        per[0] = [_op(0)]
    return read_sequences(per, label="mutant")


# ---------------------------------------------------------------------------
# Decision-map family: two knobs, butterfly route sharing and crossbar bank
# collisions, with no butterfly bank conflicts in any slot.
# ---------------------------------------------------------------------------
def _butterfly(num_in: int = MASTERS, num_out: int = 16, radix: int = 4):
    from rift.model.networks import Butterfly
    return Butterfly(num_in, num_out, radix)


def _router_pairs(net) -> list[list[int]]:
    by_router: dict[int, list[int]] = {}
    for m, (r, _) in sorted(net.inmap.items()):
        by_router.setdefault(r, []).append(m)
    return [ms for _, ms in sorted(by_router.items())]


def _spread(total: int, slots: int, phase: int) -> list[int]:
    """Bresenham spreading: per-slot counts summing exactly to total, evenly spaced, shifted by phase."""
    return [((t + 1) * total + phase) // slots - (t * total + phase) // slots for t in range(slots)]


def _slot_banks(share_pairs: set[int], doubled: int, net, xbar_banks: int, rng: random.Random) -> list[int] | None:
    """Distinct butterfly banks for every initiator: the pairs in share_pairs use one stage-1 output,
    the others two different ones, and exactly `doubled` crossbar banks are requested twice."""
    pairs = _router_pairs(net)
    pair_of = {m: i for i, ms in enumerate(pairs) for m in ms}
    order = [m for ms in pairs for m in ms]
    banks: dict[int, int] = {}

    def doubles(bs) -> int:
        seen: dict[int, int] = {}
        for b in bs:
            seen[b % xbar_banks] = seen.get(b % xbar_banks, 0) + 1
        return sum(1 for c in seen.values() if c > 1)

    def dfs(k: int) -> bool:
        if k == len(order):
            return doubles(banks.values()) == doubled
        m = order[k]
        cands = [b for b in range(net.num_out) if b not in banks.values()]
        rng.shuffle(cands)
        mates = [x for x in pairs[pair_of[m]] if x != m and x in banks]
        for b in cands:
            if mates:
                same = net._port(b, 0) == net._port(banks[mates[0]], 0)
                if same != (pair_of[m] in share_pairs):
                    continue
            banks[m] = b
            d = doubles(banks.values())
            if d <= doubled and d + (len(order) - k - 1) >= doubled and dfs(k + 1):
                return True
            del banks[m]
        return False

    return [banks[m] for m in range(net.num_in)] if dfs(0) else None


_FEASIBLE: dict[tuple[int, int], bool] = {}


def slot_feasibility() -> dict[tuple[int, int], bool]:
    """Which (sharing pairs, doubled crossbar banks) a single slot can realize (exhaustive search)."""
    if not _FEASIBLE:
        net = _butterfly()
        n = len(_router_pairs(net))
        for s in range(n + 1):
            for d in range(n + 1):
                _FEASIBLE[(s, d)] = _slot_banks(set(range(s)), d, net, net.num_out // 2, random.Random(0)) is not None
    return _FEASIBLE


def _repair_plan(share: list[int], double: list[int], ok: dict, top: int) -> list[int]:
    """Move single units of route sharing between slots until every slot is feasible; totals are kept."""
    share = list(share)
    for _ in range(4 * len(share)):
        bad = [t for t in range(len(share)) if not ok[(share[t], double[t])]]
        if not bad:
            return share
        t = bad[0]
        others = [u for u in bad[1:]] + [u for u in range(len(share)) if u not in bad]
        for delta in (1, -1):
            u = next((u for u in others if 0 <= share[t] + delta <= top and 0 <= share[u] - delta <= top
                      and ok[(share[t] + delta, double[t])] and ok[(share[u] - delta, double[u])]), None)
            if u is not None:
                share[t] += delta
                share[u] -= delta
                break
        else:
            raise ValueError("no feasible slot plan")
    raise ValueError("no feasible slot plan")


def decision_map_cell(share_slots: int, collide_slots: int, seed: int, reads: int = 32) -> dict:
    """One decision-map workload: `share_slots` of the 4*reads pair-slots share a stage-1 route and
    `collide_slots` of the 4*reads crossbar-bank slots are requested twice (two colliding requests)."""
    net = _butterfly()
    pairs = _router_pairs(net)
    cap = len(pairs) * reads
    if not (0 <= share_slots <= cap and 0 <= collide_slots <= cap):
        raise ValueError("targets out of range")
    rng = random.Random(seed)
    double = _spread(collide_slots, reads, rng.randrange(reads))
    share = _repair_plan(_spread(share_slots, reads, rng.randrange(reads)), double, slot_feasibility(), len(pairs))
    per: list[list[dict]] = [[] for _ in range(net.num_in)]
    rows = WORDS // net.num_out
    for t in range(reads):
        sp = set(rng.sample(range(len(pairs)), share[t]))
        banks = _slot_banks(sp, double[t], net, net.num_out // 2, rng)
        if banks is None:
            raise ValueError(f"slot ({share[t]}, {double[t]}) is infeasible")
        for m, b in enumerate(banks):
            per[m].append(_op(b + net.num_out * ((t * net.num_in + m) % rows)))
    return read_sequences(per, label=f"decision map share={share_slots}/{cap} collide={collide_slots}/{cap} seed={seed}")


def nominal_features(compiled, xbar_banks: int = 8, net=None) -> dict:
    """Route sharing and crossbar collisions of any workload, by slot index (the t-th read of every initiator)."""
    net = net or _butterfly()
    pairs = _router_pairs(net)
    per = [[o.byte_address // 4 for o in ops] for ops in compiled.per_master]
    shared = pair_slots = collide = req_slots = 0
    for t in range(max((len(p) for p in per), default=0)):
        present = {m: p[t] for m, p in enumerate(per) if t < len(p)}
        for ms in pairs:
            if len(ms) == 2 and all(m in present for m in ms):
                pair_slots += 1
                ba, bb = (present[m] % net.num_out for m in ms)
                shared += ba != bb and net._port(ba, 0) == net._port(bb, 0)
        counts: dict[int, int] = {}
        for q in present.values():
            counts[q % xbar_banks] = counts.get(q % xbar_banks, 0) + 1
        req_slots += len(present)
        collide += sum(1 for q in present.values() if counts[q % xbar_banks] > 1)
    return {"route_sharing": [shared, pair_slots], "crossbar_collisions": [collide, req_slots]}


def crossover(a: dict, b: dict, rng: random.Random) -> dict:
    pa, pb = _per(a), _per(b)
    per = [pa[i] if rng.random() < 0.5 else pb[i] for i in range(len(pa))]
    if sum(len(p) for p in per) == 0:
        per[0] = [_op(0)]
    return read_sequences(per, label="crossover")
