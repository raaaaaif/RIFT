# Reproduction

Everything is deterministic and offline after `fetch`: no accounts, API keys or model credentials.
Run IDs and timestamps differ between executions; costs, verdicts and the digests of workloads,
configurations and models do not.

## One command

```bash
python3.12 -m rift fetch && python3.12 -m rift doctor   # locks verified
python3.12 -m rift pipeline                             # ~5 minutes on an M1
```

`pipeline` runs, in order: doctor, Gate 0A, L/B/M comparison, formal properties, runtime benchmark,
the six-case discovery screen, C1 structural repair, independent verification on held-out baskets v1
and v2, the three verifier controls, the published comparisons and reductions (including the
invalid-reference control), the decision map (289 workloads, `experiments/maps/decision_map_v1.json`),
the diagnostic trace runs, the case registry, static site data, the viewer
build and the evidence bundles. It writes the IDs of everything it produced to
`experiments/cases/pipeline_last.json`. If it is interrupted, `--resume` reuses finished stages from
the same reference epoch.

Expected outcomes (any deviation is a finding, not something to tune away):

| Stage | Expected |
|---|---|
| gate0a | 21/21 checks |
| compare | L `TIE_OR_SMALL_MARGIN` (33/33 vs 33/65), B `VALID_NO_REVERSAL`, M `VALID_COUNTEREXAMPLE` with regret 24/41 |
| formal | unrestricted k-induction PROVED, stall-bounded PROVED, BMC-16 no counterexample, 5 covers reached, negative control COUNTEREXAMPLE |
| benchmark | target unmet (absolute times vary by host) |
| search | C1: decision-directed 9 credited reversals |
| repair | `shared_link [2,2]` |
| verify | v1 and v2 `ACCEPTED_UNDER_CONTRACT`; the three controls `REJECTED` |
| map | bank-only model: 11 wrong picks, 16 undecided; repaired model: 2 and 14 (of 289) |

## Stage by stage

```bash
python3.12 -m rift gate0a
python3.12 -m rift compare --experiment experiments/phase0_patterns.json
python3.12 -m rift formal
python3.12 -m rift benchmark --repetitions 3
python3.12 -m rift search  --study experiments/phase0_screen.json
#   put the new screen id into experiments/repair/C1_case.json ("screen_run_id")
python3.12 -m rift repair  --case experiments/repair/C1_case.json
python3.12 -m rift verify  --submission artifacts/studies/<repair id>/submission.json
python3.12 -m rift verify  --submission artifacts/studies/<repair id>/submission.json --basket experiments/heldout/heldout_v2.json
```

## Checking recorded evidence without re-running

Compare every file in a bundle against `evidence/<bundle>/bundle_manifest.json`, and run each
`artifacts/runs/<id>` through `rift.store.verify_run`. The viewer's adapter re-verifies the digests of
every run it shows and recomputes each verdict; a mismatch blocks the claim on screen.

To recompute one result by hand: read `evidence/02-phase0-patterns-LBM/runs/<rtl run>/events.jsonl`,
take the maximum `complete` cycle, subtract the first release cycle (4) and add 1. For M on BFLY4 this
gives 68 − 4 + 1 = 65.
