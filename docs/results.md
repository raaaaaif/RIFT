# Recorded results

All values below come from one end-to-end `python3.12 -m rift pipeline` run (346.4 s), whose IDs are
in `experiments/cases/pipeline_last.json`. Artifacts are in `artifacts/` and exported to `evidence/`.
Every one of the 9,885 RTL runs in the store carries reference epoch `epoch-dfa3739b2a85`.
Host: Apple M1, macOS 27.0, native arm64, Verilator 5.053 devel (OSS CAD Suite 2026-10-16).

## Gate 0A — LIC 2×2 harness validation (`20261019T222632386466Z-gate0a-d8055c`)

21/21 checks passed:

* **Sampling**: a read offered in cycle 4 is accepted at A₄ and its response arrives at V₅ with f(3) = 2130917193. Inclusive makespan = 2.
* Reset is quiet over 4 cycles. Two independent banks accept in the same cycle. Same-bank contention accepts in cycles 4 and 5 with no duplicate acceptance.
* A bank stalled for cycles 4–6 holds a stable request, which is accepted at 7.
* Back-to-back reads of rows 0–3 on one bank plus the last words (4094/4095) return f(q); word 4095 maps to bank 1, row 2047.
* Response ownership holds, drain is quiet for 3 cycles, and the inventory is 7 SV + 7 C++ monitors.
* Each of the 7 SV monitors and 2 C++ monitors detects its injected fault, and the run is rejected.
* Timeouts yield TIMEOUT with no cost. Invalid workloads are rejected. Tampered event streams are rejected by the independent checker.

## Gate 0C — public calibration programs (`20261019T222633043658Z-compare-45e148`)

| Program | Model A (LIC exact) | Model B (bank-only) | RTL A | RTL B | Verdict |
|---|---:|---:|---:|---:|---|
| L | 33 | 33 | 33 | 65 | TIE_OR_SMALL_MARGIN (model tie) |
| B | 65 | 33 | 65 | 33 | VALID_NO_REVERSAL |
| M | 41 | 33 | 41 | 65 | VALID_COUNTEREXAMPLE, regret 24/41 = 58.5% |

Measured acceptance windows for M were 40 (LIC), 32 (bank-only model) and 64 (BFLY4 RTL), equal to the
source-derived predictions recorded before execution. Makespans add the one-cycle response drain.
L, B and M are supplied calibration programs and earn zero discovery credit.

**Instrument cross-check**: `lic_exact_v1` matches LIC RTL acceptance cycles exactly on 24 random
workloads (8×8 and 2×2). `bfly_lfsr_transliteration_v1` matches BFLY4 8×16 (12/12) and the held-out
BFLY2 8×16 (8/8), including response-dependent releases (`tests/test_rtl_gates.py`).

## Measured internal activity (diagnostic traces)

Each published case was re-run on a trace-enabled build of the unchanged sources (same epoch). For
every diagnostic, the boundary events equal the reference run's and the level-0 router request bits
match the boundary offers in every cycle (0 mismatches). Cycles in which at least one stage-1 router
output of the butterfly has two or more competing requests:

| Pattern | Contended cycles | Cycles observed |
|---|---:|---:|
| M | 59 | 65 |
| L | 59 | 65 |
| B | 0 | 33 |

This is the mechanism the bank-only model omits, now observed directly rather than inferred.

## Runtime (`20261019T222726131162Z-benchmark-634be8`)

Basket: L, B, M + 397 seeded random workloads (400 total); 3 repetitions; median wall time; FST off.

| Model | RTL batched, summary only | Compiled model, summary only | Speed-up | Kernel only | Python model vs batched RTL (primary, v1) |
|---|---:|---:|---:|---:|---:|
| lic_exact_v1 | 0.161 s | 0.069 s | 2.32× | 7.6× | 0.59× |
| bank_only_v1 | 0.149 s | 0.073 s | 2.04× | 8.1× | 0.66× |
| bfly_topology_rr_v1 | 0.153 s | 0.092 s | 1.66× | 2.4× | 0.57× |

**The 5× target is not met**, under either the primary comparison declared before measuring (Python
models with full event I/O) or the useful-loop comparison (compiled models, summary only). The compiled
models are event-exact copies of the Python models (`tests/test_fastmodel.py`). The remaining time is
mostly process start-up and workload parsing that both sides pay; Verilator is already fast on this
small interconnect. Timings shift by a few tenths between runs on the same host.

## Formal checks (`20261019T222633106090Z-formal-b9e2a7`)

Harness `formal/rift_lic2x2_formal.sv` (yosys-slang frontend). The elaborated inventory has
18 asserts, 10 assumes, 5 covers and 0 blackboxes, matching the frozen expectation. Properties P1–P9
cover grant/request, single acceptance per bank, conservation, payload routing, RespLat=1 response
correspondence, response data routing, reset, LIC work conservation and wrapper-monitor consistency.
P10 is a strengthening invariant on the arbiters' LockIn state (asserted, so it is proved too).

| Task | Outcome |
|---|---|
| k-induction, depth 16, unrestricted | **PROVED** |
| k-induction with bank stalls ≤ 3 cycles (earlier variant) | PROVED |
| BMC to depth 16 | BOUNDED_NO_COUNTEREXAMPLE |
| Covers | all 5 reached (not vacuous) |
| Negative control (one deliberately false assertion) | COUNTEREXAMPLE |

Scope: transport on the 2×2 crossbar only. No memory-content, butterfly or fast-model claim.

## Phase 0 discovery screen (`20261019T222726639417Z-screen-e245c0`)

Six authored cases. Budget per case and method: 32 accepted proposals (64 RTL executions). There were
880 distinct RTL executions and 1,104 disclosed cache hits (charged). The table shows credited strict
reversals, with maximum regret over valid proposals in parentheses.

| Case (models A / B) | Sweeps (B1) | Random (B2) | Evolutionary (B2) | SMT (B3) | Error-directed (B5) | Decision-directed |
|---|---|---|---|---|---|---|
| C1 bank-only omission | 0 (58.5%, M uncredited) | 1 (7.1%) | 0 (4.3%) | 0 (0%) | 2 (6.5%) | **9 (16.7%)** |
| C2 topology RR (permitted approx.) | 0 | 0 (7.7%) | **1 (4.8%)** | n/a | 0 (9.5%) | 0 |
| C3 LFSR advances every cycle | 0 | 0 | 0 (2.0%) | n/a | 0 | 0 |
| C4 bank mapping q mod 8 | 0 (98.5%)* | 8 (16.9%) | **18 (42.6%)** | n/a | 1 (106%) | 0 (98.5%)* |
| C5 LIC FairArb=0 | 0 | 1 (16.9%) | 1 (11.5%) | n/a | 1 (7.1%) | **2 (13.6%)** |
| C6 response latency +1 | 0 | 11 (16.9%) | **19 (11.9%)** | n/a | 0 (3.0%) | 3 (9.5%) |

\* High regret from model **ties** resolved by the frozen tie policy. These are consequential but are
not credited as strict reversals.

Reading:

* Decision-directed acquisition wins where its variant library contains the omitted mechanism (C1, and narrowly C5). It loses clearly on C4 and C6, where evolutionary and random search win.
* My pre-registered expectation that C6 would be decision-irrelevant was **wrong**: the extra cycle compounds along response-dependency chains.
* C2 shows the permitted round-robin approximation can occasionally flip a decision.
* The screen is deterministic: this run reproduces the credited counts of the four earlier screens run with the same code exactly. The first screen (`…screen-e6ca04`) predates a model-engine fix for response latency > 1 (caught by the independent checker as MODEL_ERROR and never scored) and differs.

## Witness reduction (surrogate-complete, RTL-confirmed)

| Witness | Operations | Model A/B | RTL A/B | Regret | RTL executions | Minimality |
|---|---|---|---|---|---|---|
| Pattern M (`…reduction-2f5e99`) | 256 → 14 | 9 / 7 | 9 / 11 | 2/9 | 32 of 32 | **1-minimal**: all 31 one-edit neighbours break the reversal; 14 re-checked on RTL |
| C1 discovered (`…reduction-4f1b15`) | 95 → 19 | 17 / 15 | 17 / 19 | 2/17 | 32 of 32 | **1-minimal**: all 49 neighbours break it; 14 re-checked on RTL |

Every candidate is replayed from reset; there are no checkpoints. The original and the final witness
are both executed on the RTL. No RTL re-check contradicted the surrogate.

## Published cases

| Case | Model A/B | RTL A/B | Verdict |
|---|---|---|---|
| C1 decision-directed witness (screen step 23) | 45 / 43 | 45 / 49 | VALID_COUNTEREXAMPLE, regret 4/45 |
| C4 decision-directed proposal (screen step 21) | 129 / 129 | 129 / 65 | TIE_OR_SMALL_MARGIN; the tie policy picks A, regret 64/65 |
| Invalid-reference control (M with an injected payload-routing monitor fault on B) | — | B `HARNESS_INVALID` | HARNESS_INVALID: comparison blocked |

## Decision map (`20261019T223116166650Z-map-b7a943`)

Manifest `experiments/maps/decision_map_v1.json`, committed (with its prediction) before the map ran.
It is a 17×17 grid of workloads from one family: eight initiators, 32 back-to-back reads each, and in
every slot eight distinct butterfly banks, so no butterfly bank conflicts. Two knobs vary:

- **Route sharing:** the share of initiator pairs whose two requests need the same stage-1 butterfly output.
- **Crossbar collisions:** the share of requests that land on a crossbar bank another initiator wants in the same slot.

Every cell runs on both RTL designs, plus the exact crossbar model, the bank-only model and the
repaired model. That is 578 RTL runs and 867 model runs, and every verdict comes from the same evaluator.

| | Bank-only model | Repaired model |
|---|---:|---:|
| Wrong picks (strict reversals) | 11 | 2 |
| Model undecided where the hardware is decisive | 16 | 14 |
| Worst cost of following the model | +9 cycles (20.5%) | +5 cycles (10.2%) |
| Largest error on the butterfly | 21 cycles | 9 cycles |

Hardware outcome: crossbar faster in 27 cells, butterfly faster in 218, within margin in 44.

How the prediction recorded before execution compared:

* **Bank-only model: held.** It predicts 33 cycles for the butterfly in every cell. It is undecided with no collisions and never picks the crossbar.
* **Location of the wrong picks: held.** All 11 lie where route sharing exceeds crossbar collisions.
* **Hardware switch-over near the diagonal: did not hold.** The crossbar wins in only 27 of the 136 cells below the diagonal, and never above 25% collisions. The bottom row (no collisions) is crossbar territory at every sharing level. Above it, collisions quickly make the crossbar slower.
* **Repaired model: held.** It tracks the boundary closely (2 wrong picks left).

The error versus decision point is visible directly: the bank-only model misjudges the butterfly by
up to 21 cycles across almost the whole map, but its choice changes only in the band near zero collisions.

Landmarks are placed by the same nominal-feature formula: L at (1, 0), B at (0, 1), M at (0.94, 0.06).
The C1 witness is shown as outside the family (unequal stream lengths, 24 response-dependent
releases, 17 gaps, 9 slots with a butterfly bank conflict): the search found a reversal at
coordinates where this family's cells show none.

A 3×3 smoke test of the map runner (9 cells, in a throwaway artifact store) ran after the manifest
was committed and before the full map. Nothing in the manifest or the generator changed afterwards.

## Structural repair and independent verification (case C1)

* Repair `20261019T223036360386Z-repair-8f3a10`: a deterministic search over 25 grammar candidates selected `shared_link [2,2]` (`repair_C1_bank_only_omission_68fb9e6b`): initiator pairs share one link per `bank >> 2`, which is the butterfly's first-stage structure. On development data, strict reversals went 13 → 0, wrong choices 54 → 11 and butterfly MAE 6.01 → 0.91 cycles. Among the rejected alternatives, unfair arbitration leaves 7 of 13 witnesses unresolved and response latency +1 raises reversals to 20.
* Verification on `heldout-v1` (`…verify-2e78e7`): **ACCEPTED_UNDER_CONTRACT** (`repair-acceptance-v1`, 48 workloads in 4 families, including the held-out BFLY2 architecture). R1 no model errors; R2 reversals 1 → 0; R3 no regressions; R4 runtime 1.47× the parent; R5 13/13 development witnesses resolved on fresh RTL replays; R6 patch boundary respected.
* Verification on `heldout-v2` (`…verify-5ef01f`): **ACCEPTED_UNDER_CONTRACT** (48 workloads in 4 mechanism-oriented families with fresh seeds 65000–68011; defined after v1's result, candidate frozen beforehand). R2 reversals 2 → 0 (both in H6 two-phase, where mean regret fell from 3.24% to 0.12%); R4 1.47×.
* **Caveat**: 3 of 96 held-out workloads were parent reversals. Five of the eight families (H1, H3, H5, H7, H8) never confused the parent, so they test only for regressions. In H2 the candidate's mean regret rose from 0.48% to 0.65%.

Controls submitted to the same verifier:

| Submission | Disposition | Failed rules |
|---|---|---|
| Memorized witness costs (lookup patch) | REJECTED, not built | R6 (patch boundary) |
| Wrong structure `[8,0]` | REJECTED | R2, R5 |
| Conventional parametric fit only | REJECTED | R1, R2, R4, R5 (cannot run BFLY2; 3/13 witnesses unresolved) |

## Tests

* `python3.12 -m unittest discover -s tests -t .`: 36 tests, OK (real Verilator harness and Yosys; compiled-vs-Python model cross-check; VCD parsing; decision-map generator, landmarks and tamper detection).
* `cd ui && npx playwright test`: 35 tests in Chrome against the read-only server, the `--allow-run` server (one real budgeted RTL replay) and the static build served by a plain file server, including the decision map and the contour functions.
