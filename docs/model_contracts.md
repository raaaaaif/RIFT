# Fast-model approximation contracts

Specifications live in `rift/model/registry.py`; fitted and candidate models live in `models/`.
A model digest covers its specification and the model source files (`engine.py`, `networks.py`,
`arbiters.py`), so any code or parameter change yields a new identity.

| Model | Family | Promise | Scope / declared omissions | Status |
|---|---|---|---|---|
| `lic_exact_v1` | crossbar (rr_arb_tree FairArb=1, LockIn=1) | EXACT_TIMING | LIC configurations | event-exact vs RTL on 24 random workloads |
| `bank_only_v1` | crossbar applied to the butterfly | RANKING_PRESERVATION | omits internal route contention and LFSR priorities (handoff-seeded omission) | strict reversal on M; 9–13 witnesses in screen C1 |
| `fitted_penalty_bfly4_8x16_v1` | bank-only + fitted per-path penalties | BOUNDED_ERROR (training distribution) | 40 training workloads, seeds 7000–7039; training MAE 1.55 cycles | predicts L=42 (RTL 65), B=48 (RTL 33) |
| `bfly_topology_rr_v1` | butterfly wiring + per-output round robin | BOUNDED_ERROR | permitted approximation: arbitration winner choice | 1 decision reversal found in screen C2 |
| `bfly_lfsr_transliteration_v1` | butterfly + PRESENT-cipher LFSR | EXACT_TIMING | **diagnostic only, not admissible** (copies RTL state) | event-exact vs BFLY4 and BFLY2 RTL |
| `defect_*` (5 models) | authored defects | as declared | LFSR every cycle; no cipher register; bank q mod 8; FairArb=0; response latency 2 | labelled AUTHORED throughout |
| `repair_C1_bank_only_omission_68fb9e6b` | shared_link `[2,2]` | RANKING_PRESERVATION | candidate repair of `bank_only_v1` | ACCEPTED_UNDER_CONTRACT (thin held-out evidence) |

## Model-change grammar (repair)

The repairer may edit only the butterfly-side specification. The grammar contains:

* parent
* `shared_link [g, s]` for g ∈ {2, 4, 8} and s ∈ {0..3}
* two-level links `[2, s1]+[4, s2]`
* unfair arbitration
* response latency +1
* parametric fit only

Structure is chosen on development evidence by the following ordering: unresolved witnesses, then
strict reversals, then wrong choices, then mean regret, then complexity, then MAE.

## Acquisition variants (decision- and error-directed arms)

The permitted variant ensemble is:

* the audited model
* `lic_exact + bank_only`
* `lic_exact + shared_link {[2,2], [2,1], [4,2]}`
* `lic_unfair + audited B`
* `audited A + fitted_penalty`

Scores follow report section 5 (λ = 0.2, μ = 0.1, one exploration pick in five). These are
heuristics, not a calibrated posterior. The library is source-informed: it contains the C1 mechanism
(shared links) but no bank-mapping-width or response-latency variant, which is consistent with its
advantage on C1 and its losses on C4 and C6.

## Compiled implementations

`oracle/fastmodel.cpp` implements the `crossbar`, `shared_link` and round-robin `butterfly` families
(including `bank_modulus` and `resp_lat`) in C++17. It reads the same compiled-workload text as the
RTL driver and writes the same summary and event schema. A compiled execution is identified by the
Python model digest plus the C++ source digest, and the binary is content-addressed under
`build/fastmodel-<digest>`. `tests/test_fastmodel.py` requires identical status, makespan and event
sets against the Python models for 8 model configurations on L, B, M and 12 random workloads. The LFSR
transliteration and the LFSR-based authored defects have no compiled form.
