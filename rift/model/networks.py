"""Interconnect network models (editable fast-model surface).

All networks receive offers as {initiator: logical word q} and apply their own
declared bank mapping (default q mod num_out). Responses are produced by the
engine at the declared response latency.
"""

from __future__ import annotations

from rift.model.arbiters import PresentLfsr, RRArbTree, clog2
from rift.model.engine import Network


class Crossbar(Network):
    """Per-bank rr_arb_tree arbitration with no internal routing conflicts.

    For LIC this is the pinned xbar structure (FairArb=1, LockIn=1). Applied to a
    butterfly configuration it is the bank-only omission model.
    """

    def __init__(self, num_in: int, num_out: int, fair: bool = True, lock_in: bool = True, bank_modulus: int | None = None):
        self.num_in = num_in
        self.num_out = num_out
        self.fair = fair
        self.lock_in = lock_in
        self.bank_modulus = bank_modulus or num_out
        self.reset()

    def reset(self) -> None:
        self.arbs = [RRArbTree(self.num_in, self.fair, self.lock_in) for _ in range(self.num_out)]
        self.locked: set[int] = set()

    def bank(self, q: int) -> int:
        return q % self.bank_modulus

    def arbitrate(self, reqs: dict[int, int], bank_grant: list[bool]) -> set[int]:
        granted = set()
        new_locked = set()
        for b in set(reqs) | self.locked:
            arb = self.arbs[b]
            w, req_d = arb.select(reqs.get(b, 0))
            req_o = w >= 0
            g = bank_grant[b]
            if req_o and g:
                granted.add(w)
            arb.update(req_d, req_o, g)
            if arb.lock_q:
                new_locked.add(b)
        self.locked = new_locked
        return granted

    def cycle(self, offers, bank_grant):
        reqs: dict[int, int] = {}
        for m, q in offers.items():
            b = self.bank(q)
            reqs[b] = reqs.get(b, 0) | (1 << m)
        return self.arbitrate(reqs, bank_grant)


class SharedLinkCrossbar(Crossbar):
    """Crossbar plus shared intermediate links (repair grammar structure).

    Each link level k is (group_size g_k, bank_shift s_k): initiators m // g_k
    share one link per destination class bank >> s_k, so at most one request per
    (m // g_k, bank >> s_k) can proceed per cycle. Links are arbitrated in order
    with round-robin trees, then the bank stage arbitrates among survivors.
    """

    def __init__(self, num_in, num_out, links: list[tuple[int, int]], fair=True, lock_in=False):
        self.links = [tuple(l) for l in links]
        super().__init__(num_in, num_out, fair, lock_in)

    def reset(self) -> None:
        super().reset()
        self.link_arbs = [dict() for _ in self.links]

    def cycle(self, offers, bank_grant):
        survivors = dict(offers)
        stage_records = []
        for k, (g, s) in enumerate(self.links):
            groups: dict[tuple[int, int], int] = {}
            for m, q in survivors.items():
                key = (m // g, self.bank(q) >> s)
                groups[key] = groups.get(key, 0) | (1 << (m % g))
            nxt = {}
            for key, mask in groups.items():
                arb = self.link_arbs[k].get(key)
                if arb is None:
                    arb = self.link_arbs[k][key] = RRArbTree(g, True, False)
                w, req_d = arb.select(mask)
                m = key[0] * g + w
                nxt[m] = survivors[m]
                stage_records.append((arb, req_d, m))
            survivors = nxt
        reqs: dict[int, int] = {}
        for m, q in survivors.items():
            b = self.bank(q)
            reqs[b] = reqs.get(b, 0) | (1 << m)
        granted = self.arbitrate(reqs, bank_grant)
        for arb, req_d, m in stage_records:
            arb.update(req_d, True, m in granted)
        return granted


class Butterfly(Network):
    """Radix-2/4 butterfly following the pinned bfly_net wiring.

    prio_mode "lfsr": external priorities from the 64-bit PRESENT LFSR exactly as
    in tcdm_interconnect (diagnostic transliteration and its authored defects).
    prio_mode "rr": each router output keeps its own FairArb round-robin state
    (the reviewed topology-aware model's declared approximation).
    """

    def __init__(self, num_in: int, num_out: int, radix: int, prio_mode: str = "rr",
                 lfsr_every_cycle: bool = False, lfsr_no_cipher_reg: bool = False, bank_modulus: int | None = None):
        if radix not in (2, 4):
            raise ValueError("radix must be 2 or 4")
        self.num_in, self.num_out, self.radix = num_in, num_out, radix
        self.add_w = clog2(num_out)
        self.lr = clog2(radix)
        if radix == 4 and self.add_w % 2:
            raise ValueError("radix-4 butterflies needing a radix-2 stage are not modelled")
        self.levels = (self.add_w + self.lr - 1) // self.lr
        self.routers = num_out // radix
        self.bank_fact = num_out // num_in
        self.prio_mode = prio_mode
        self.lfsr_every_cycle = lfsr_every_cycle
        self.lfsr_no_cipher_reg = lfsr_no_cipher_reg
        self.bank_modulus = bank_modulus or num_out
        # input connections: master -> (router, port)
        self.inmap = {}
        for j in range(radix * self.routers):
            if self.bank_fact < radix:
                if j % self.bank_fact == 0:
                    self.inmap[j // self.bank_fact] = (j // radix, j % radix)
            elif j % radix == 0 and j // radix < num_in:
                self.inmap[j // radix] = (j // radix, 0)
        # inter-level wiring: (l, r, s) -> (k, j)
        self.wire = {}
        for l in range(self.levels - 1):
            pw = radix ** (self.levels - l - 2)
            for r in range(self.routers):
                for s in range(radix):
                    k = pw * s + (r % pw) + (r // pw // radix) * pw * radix
                    j = (r // pw) % radix
                    self.wire[(l, r, s)] = (k, j)
        self.reset()

    def reset(self) -> None:
        self.arbs = {}
        self.lfsr = PresentLfsr(clog2(self.num_in), self.lfsr_every_cycle, self.lfsr_no_cipher_reg)

    def _prio(self, level: int) -> int:
        rr1 = self.lfsr.out()
        p = 0
        for j in range(self.lr):
            idx = self.add_w - (level + 1) * self.lr + j
            bit = (rr1 >> idx) & 1 if idx >= 0 else 0
            pos = (self.lr - 1 - j) if self.bank_fact < self.radix else j
            p |= bit << pos
        return p

    def _port(self, bank: int, level: int) -> int:
        return (bank >> (self.add_w - (level + 1) * self.lr)) & (self.radix - 1)

    def cycle(self, offers, bank_grant):
        # current request at each router input: (level, router, port) -> master
        cur = {}
        for m, q in offers.items():
            r, p = self.inmap[m]
            cur[(r, p)] = m
        bank_of = {m: q % self.bank_modulus for m, q in offers.items()}
        records = []
        for l in range(self.levels):
            prio = self._prio(l) if self.prio_mode == "lfsr" else None
            groups: dict[tuple[int, int], int] = {}
            for (r, p), m in cur.items():
                s = self._port(bank_of[m], l)
                groups[(r, s)] = groups.get((r, s), 0) | (1 << p)
            nxt = {}
            for (r, s), mask in groups.items():
                key = (l, r, s)
                arb = self.arbs.get(key)
                if arb is None:
                    arb = self.arbs[key] = RRArbTree(self.radix, True, False, ext_prio=(self.prio_mode == "lfsr"))
                w, req_d = arb.select(mask, prio)
                m = cur[(r, w)]
                if l < self.levels - 1:
                    k, j = self.wire[(l, r, s)]
                    nxt[(k, j)] = m
                else:
                    nxt[(r, s)] = m
                records.append((arb, req_d, m))
            cur = nxt
        granted = set()
        for (r, s), m in cur.items():
            if bank_grant[r * self.radix + s]:
                granted.add(m)
        for arb, req_d, m in records:
            arb.update(req_d, True, m in granted)
        if self.prio_mode == "lfsr":
            self.lfsr.edge(bool(granted))
        return granted


class FittedPenalty(Crossbar):
    """Bank-only arbitration plus fitted per-path penalties (black-box calibration).

    penalty_milli[m][b] = init_milli[m] + bank_milli[b]; each acceptance on path
    (m, b) adds that many thousandths of a cycle to the initiator's debt, and an
    initiator holding at least one full cycle of debt sits out one cycle.
    """

    def __init__(self, num_in, num_out, init_milli: list[int], bank_milli: list[int]):
        self.init_milli = list(init_milli)
        self.bank_milli = list(bank_milli)
        super().__init__(num_in, num_out, True, True)

    def reset(self) -> None:
        super().reset()
        self.debt = [0] * self.num_in

    def cycle(self, offers, bank_grant):
        eff = {}
        for m, q in offers.items():
            if self.debt[m] >= 1000:
                self.debt[m] -= 1000
            else:
                eff[m] = q
        g = super().cycle(eff, bank_grant)
        for m in g:
            b = self.bank(offers[m])
            self.debt[m] += max(0, self.init_milli[m] + self.bank_milli[b])
        return g
