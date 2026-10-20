"""Arbitration primitives used by the fast models.

RRArbTree reproduces the pinned common_cells rr_arb_tree selection tree:
leaf pairs choose with  sel = ~req[2l] | (req[2l+1] & rr_q[0]);  inner nodes
choose with the corresponding higher priority bit. With FairArb=1 the internal
priority jumps to the next requesting index above the current one (wrapping),
updated only when the output request is granted. LockIn freezes the request
vector while the output is not granted. With ExtPrio the priority is supplied
externally and there is no state.

PresentLfsr reproduces common_cells lfsr with LfsrWidth=64, three PRESENT
cipher layers and CipherReg=1: on an enabled edge the output register captures
the cipher of the *old* LFSR state and the LFSR advances one Galois step.
"""

from __future__ import annotations

SBOX = [0xC, 0x5, 0x6, 0xB, 0x9, 0x0, 0xA, 0xD, 0x3, 0xE, 0xF, 0x8, 0x4, 0x7, 0x1, 0x2]
PERM = [(16 * i) % 63 if i < 63 else 63 for i in range(64)]
LFSR_MASK_64 = 0x80000000000019E2
MASK64 = (1 << 64) - 1


def clog2(n: int) -> int:
    return max(0, (n - 1).bit_length())


class RRArbTree:
    __slots__ = ("n", "levels", "fair", "lock_in", "ext_prio", "rr_q", "lock_q", "req_q")

    def __init__(self, n: int, fair: bool = True, lock_in: bool = False, ext_prio: bool = False):
        self.n = n
        self.levels = clog2(n)
        self.fair = fair
        self.lock_in = lock_in and not ext_prio
        self.ext_prio = ext_prio
        self.rr_q = 0
        self.lock_q = False
        self.req_q = 0

    def select(self, req_mask: int, rr: int | None = None) -> tuple[int, int]:
        """Return (winner index or -1, effective request mask req_d)."""
        if self.n == 1:
            return (0 if req_mask & 1 else -1), req_mask
        req_d = self.req_q if (self.lock_in and self.lock_q) else req_mask
        prio = rr if self.ext_prio else self.rr_q
        if req_d == 0:
            return -1, req_d
        L = self.levels
        # leaves
        width = 1 << (L - 1)
        nodes_req = [0] * width
        nodes_idx = [0] * width
        bit = (prio >> 0) & 1
        for l in range(width):
            i0, i1 = 2 * l, 2 * l + 1
            if i0 < self.n - 1:
                r0 = (req_d >> i0) & 1
                r1 = (req_d >> i1) & 1
                nodes_req[l] = r0 | r1
                nodes_idx[l] = 1 if ((not r0) or (r1 and bit)) else 0
            elif i0 == self.n - 1:
                nodes_req[l] = (req_d >> i0) & 1
                nodes_idx[l] = 0
        # inner levels, from leaf-parent level up to the root
        depth = 1
        while width > 1:
            bit = (prio >> depth) & 1
            nw = width >> 1
            nreq = [0] * nw
            nidx = [0] * nw
            for l in range(nw):
                r0, r1 = nodes_req[2 * l], nodes_req[2 * l + 1]
                nreq[l] = r0 | r1
                sel = (not r0) or (r1 and bit)
                nidx[l] = ((1 << depth) | nodes_idx[2 * l + 1]) if sel else nodes_idx[2 * l]
            nodes_req, nodes_idx, width = nreq, nidx, nw
            depth += 1
        return (nodes_idx[0] if nodes_req[0] else -1), req_d

    def update(self, req_d: int, req_o: bool, gnt_i: bool) -> None:
        """Clock edge: FairArb priority and LockIn registers."""
        if self.ext_prio or self.n == 1:
            return
        if req_o and gnt_i:
            if self.fair:
                upper = req_d & ~((1 << (self.rr_q + 1)) - 1)
                pick = upper if upper else (req_d & ((1 << (self.rr_q + 1)) - 1))
                self.rr_q = (pick & -pick).bit_length() - 1
            else:
                self.rr_q = 0 if self.rr_q == self.n - 1 else self.rr_q + 1
        if self.lock_in:
            self.lock_q = bool(req_o and not gnt_i)
            self.req_q = req_d


def _sbox_layer(x: int) -> int:
    out = 0
    for j in range(16):
        out |= SBOX[(x >> (4 * j)) & 0xF] << (4 * j)
    return out


def _perm_layer(x: int) -> int:
    out = 0
    for j in range(64):
        if (x >> j) & 1:
            out |= 1 << PERM[j]
    return out


def present_cipher(x: int, layers: int = 3) -> int:
    for _ in range(layers):
        x = _perm_layer(_sbox_layer(x))
    return x


class PresentLfsr:
    """lfsr #(.LfsrWidth(64), .OutWidth(w), .CipherLayers(3), .CipherReg(1)), RstVal='1."""

    __slots__ = ("width", "lfsr_q", "out_q", "advance_every_cycle", "no_cipher_reg")

    def __init__(self, out_width: int, advance_every_cycle: bool = False, no_cipher_reg: bool = False):
        self.width = out_width
        self.lfsr_q = MASK64
        self.out_q = 0
        self.advance_every_cycle = advance_every_cycle  # authored defect variant
        self.no_cipher_reg = no_cipher_reg              # authored defect variant

    def out(self) -> int:
        if self.no_cipher_reg:
            return present_cipher(self.lfsr_q) & ((1 << self.width) - 1)
        return self.out_q

    def edge(self, enable: bool) -> None:
        if self.advance_every_cycle:
            enable = True
        if not enable:
            return
        self.out_q = present_cipher(self.lfsr_q) & ((1 << self.width) - 1)
        q = self.lfsr_q
        self.lfsr_q = ((q >> 1) ^ (LFSR_MASK_64 if q & 1 else 0)) & MASK64
