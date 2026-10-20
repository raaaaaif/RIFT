# Limitations, blockers and unmet criteria

## Unmet engineering criteria

* 5× model speed target: not met. On the 400-workload basket, the compiled C++ fast models run 1.66–2.32× faster than batched Verilator when both sides are measured the way the search loop uses them (batched, summary only; study `20261019T222726131162Z-benchmark-634be8`). The simulation kernel alone is 2.4–8.1× faster (2.4× for the topology-aware butterfly model), so most of the remaining time is process start-up and workload parsing that both sides pay. Timings vary by a few tenths between runs on the same host. Verilator compiles this small interconnect to code that is already fast. The pure-Python models are slower than batched Verilator. The primary comparison was declared before measuring and is reported as unmet.
* All six audit cases were authored by the implementer. There is no independently authored, hidden or naturally occurring case and no reconstructed published regression (Gate 0D not met).
* No second subsystem family (for example, the AXI interconnect).
* Linux reproducibility target not exercised. Everything ran natively on darwin-arm64. The Docker daemon was not running and disk was too tight for a Linux image plus the Linux toolchain bundle; the Linux asset's digest is recorded in `locks/toolchain.lock.json`.

## Weak or narrow evidence

* Held-out evidence for the accepted repair is thin. Across both sealed baskets, 3 of 96 held-out workloads were parent reversals (all fixed, no new reversals). Five of the eight families never confused the original model, so they only test for regressions. In one family the candidate's mean regret is slightly higher than the parent's. Basket v2 was defined after v1's result, with the candidate frozen beforehand; it is not an independent replication.
* Decision-directed search is not a general winner. It finds the most reversals on C1 (9 vs 2) and C5 (2 vs 1), but evolutionary search wins C4 (18 vs 8), C6 (19 vs 11) and C2 (1 vs 0), and no method finds one for C3.
* Formal scope is the LIC 2×2 harness only. Properties cover transport (grant/request, single acceptance, conservation, routing, response correspondence, reset, work conservation, monitor consistency). There is no butterfly proof, no memory-content proof and no proof about the fast models.
* Reduction minimality is local. "1-minimal" means every single edit from the recorded edit set breaks the reversal under the event-exact surrogate; 14 neighbours of each witness were also confirmed on the RTL within the 32-execution reserve. It is not a global minimum.
* The decision map is one exploratory family. It is a two-knob slice (back-to-back reads with distinct butterfly banks per slot), defined after the repair was frozen and not part of acceptance. It has one seed per cell, so the noisy boundary layer is not averaged. Its coordinates are nominal (by slot index): once initiators stall, their streams drift, which is why the measured switch-over sits far below the predicted diagonal. Workloads outside the family (such as the C1 witness) can disagree with the map at the same coordinates.
* B3 (bounded SMT) covers only the bank-only acceptance predicate. It is not applicable to the other cases, and it enumerates single-cycle acceptance shortfalls rather than decision reversals.
* Internal activity is measured only for the butterfly's first stage. The diagnostic traces read level-0 router requests/grants and the LFSR priority. Later stages are drawn from the configuration wiring formula.

## Toolchain and frontend

* The OSS CAD Suite archive was verified (sha256) and extracted partially, excluding FPGA place-and-route and VHDL components. The archive was then deleted to free disk; retrieval and checksum are in `locks/toolchain.lock.json`.
* Bender is not part of the bundle. The compile closure was resolved manually from the `Bender.yml` files and verified by elaboration.
* No vendor assertion executed under either frontend. Concurrent assertions are excluded by `ifndef VERILATOR`. Elaboration-time initial assertions are compiled (Verilator ignores `translate_off`) but are constant-folded.
* yosys-slang elaborates zero vendor `$check` cells, and the LockIn/ExtPrio initial assertion raises no error under slang. See `locks/assertion_exclusions.json`.
* Diagnostic trace builds need `lz4` headers (Homebrew `/opt/homebrew`) for FST output.

## Viewer and browser execution

The public site is deployed to Cloudflare Pages and includes browser RTL replay and a bounded workload lab. Chromium, Firefox, and WebKit parity and UI checks passed; installed Safari separately ran the guided experiment. See [browser validation](browser-validation.md) for the full scope and recorded measurements.

* No founder comprehension or expert retrieval study was run.
* Functional tests and responsive checks do not establish WCAG conformance or human usability.
* No physical low-end-device study or assistive-technology audit was completed. Slower loading was tested synthetically.
* Search, structural repair, formal checks, and artifact generation remain local workflows.
* Browser/native event parity is tested evidence, not a formal equivalence proof. Event hashes establish reproduction relative to the site's artifact, not independent authentication of the website.
* Exact native receipt build identity is qualified for macOS arm64. Another host requires separate qualification.
* The public repository includes selected evidence copies and bundle manifests. Bulky run stores and local tool installations are regenerated, not committed.
