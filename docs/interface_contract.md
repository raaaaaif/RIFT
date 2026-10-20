# Interface, sampling and workload contract

## Reference conditions

All configurations use AddrWidth=32, DataWidth=32, ByteOffWidth=2, BeWidth=4, RespLat=1,
WriteRespOn=1 and NumPar=1, with 4096 logical words (16 KiB). For aligned byte address `a`:
`q = a >> 2`, `bank = q mod NumOut`, `row = q / NumOut`.

| Config | Topology | NumIn | NumOut | AddrMemWidth | Role |
|---|---|---:|---:|---:|---|
| lic2x2 | LIC | 2 | 2 | 11 | harness gate |
| lic8x8 | LIC | 8 | 8 | 9 | Architecture A |
| bfly4_8x16 | BFLY4 | 8 | 16 | 8 | Architecture B |
| bfly2_8x16 | BFLY2 | 8 | 16 | 8 | held-out architecture (verifier only) |

Phase 0 traffic is read-only: `wen_i=0`, `be_i=0xf`. Banks always grant unless a stall is declared.

## Clock and sampling (`pre_rise_v1`, verified by Gate 0A)

For every cycle `c` the driver does the following:

1. Drives inputs with the clock low and evaluates.
2. Samples, immediately before rising edge `c`:
   * `A_c = req_i & gnt_o`
   * bank acceptances `req_o & gnt_i` with `add_o`
   * `V_c = vld_o / rdata_o`
   * the wrapper monitor outputs
3. Applies rising edge `c`.

Banks capture the accepted row at edge `c` and present registered data for `V_(c+1)`. RespLat=1
therefore means `A_c → V_(c+1)`; this was established by the single-read test (A₄ → V₅).

Reset holds `rst_ni=0` for 4 request-free rising edges (cycles 0–3). The first release cycle is 4.
No request is offered before reset completes, so no response needs cancelling.

**Metric** `inclusive_cycle_makespan_v1` = `last_response_cycle − first_release_cycle + 1`.

## Memory oracle

The oracle is `f(q) = ((q × 0x9E3779B1) XOR 0xA5A55A5A) mod 2³²`. The image is distributed into banks
by each configuration's mapping. The scoreboard derives expected data from the operation's logical
address, never from the bank arrays.

## Workload semantics

* Program kinds:
  * `repeat_read` and `ordered_read_segments` (handoff kinds): `after_accept`, gap 0.
  * `read_sequences` (RIFT schema-v1 extension): each operation carries a release rule, `after_accept` or `after_response`, and a gap of 0–64.
* Every initiator presents at most one request and holds it stable until accepted.
* A response-dependent operation waits for its **immediate predecessor's** response. A response observed at sample `t` releases it no earlier than `t+1`.
* Operation identity is `m<initiator>:op<index>`. Repeated addresses are distinct operations.
* Cross-initiator edges, stores, races and data-dependent addresses are rejected.
* Limits: 1024 operations per initiator and 4096 per workload.

## Independent checker (`rift/evaluate/checker.py`)

The checker recomputes validity and cost from raw events alone. It checks:

* schema and run identity
* the reset sequence
* exactly one offer/accept/complete per operation
* bank/row mapping
* `complete = accept + RespLat`
* read data against its own copy of `f(q)`
* release-rule conformance (no bubbles, no early offers)
* at most one acceptance per bank per cycle
* monitor failures
* agreement with the runner's summary

Status precedence is TOOL_ERROR > TIMEOUT > HARNESS_INVALID (MODEL_ERROR for models) > FUNCTIONAL_MISMATCH > COMPLETED.

## Pairwise verdict (`rift/evaluate/compare.py`)

* `dM = M_A − M_B` and `dR = R_A − R_B`. A strict reversal requires `dM·dR < 0` and, independently in each domain, `|d| ≥ max(2, 0.02·min)`. The relative term is evaluated exactly as `50·|d| ≥ min`.
* Selection uses argmin, with ties resolved to the first admitted design.
* Regret is `(R_chosen − R_best) / max(1, R_best)`, stored as an exact fraction.
* Any failed reference run blocks the comparison with its own status. A failed model run is MODEL_ERROR.

## Reference epoch

An epoch is a digest of: RTL and dependency commits, wrapper digest, driver digest, memory-oracle
spec, sampling convention, and toolchain-lock digest. Changing any of them starts a new epoch. The
viewer refuses to transfer old acceptance across epochs.
