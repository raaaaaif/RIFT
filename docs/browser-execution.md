# Browser execution

RIFT's public site is a static investigation with an optional execution lab. The lab compiles the original `oracle/main.cpp`, generated Verilator models, and `oracle/fastmodel.cpp` to three WebAssembly modules. It is not a JavaScript approximation of the RTL. The native reference epoch and original research artifacts are unchanged.

## Rebuild

The qualified compiler is Emscripten 6.0.13, commit `e13ee988ce3d87a738dd8f3661d02223308c412a`, from the official macOS arm64 archive recorded in `locks/browser-toolchain.lock.json`. The native toolchain must already pass `python3.12 -m rift doctor`.

```bash
python3.12 scripts/install_browser_sdk.py
python3.12 -m rift.browser_build
python3.12 -m rift.browser_data
python3.12 -m rift publish
npm --prefix ui ci
npm --prefix ui run build
```

The installer needs approximately 286 MB for download and approximately 2.47 GB of extracted file contents (about 1.54 GB allocated on this APFS volume), and a free-space reserve. It installs only under `.tools/emsdk`, uses an existing Node executable, verifies the archive digest, and deletes its own download after extraction. It does not alter the native OSS CAD Suite, shell profile, or shared installations. Other compiler hosts require a separately qualified official archive and browser lock. The task-created SDK installation was removed after qualification to restore disk headroom; rerun the pinned installer before rebuilding WASM. Ordinary web builds and native receipt verification do not require Emscripten.

Native sources, driver arguments, configuration defines, harness monitors, and generated models are reused. Three adaptations are applied only to a private copy of the Verilator runtime: initialize one context thread, and select the upstream non-affinity branches in two guards. The lock records each original and adapted source digest. Relative compiler inputs prevent embedding this workstation's home path in public binaries. The optional runtime-source download contains the complete copied runtime, modifications, and third-party licenses. The modified runtime is available under the upstream Artistic 2.0 option.

The build emits a content-addressed generation under `ui/public/browser/`. The replay manifest binds module hashes, native references, model specifications, browser contract source hashes, exact execution options, and exported evidence inputs. Its digest is embedded into the production frontend. `manifest.json` revalidates; generation assets are immutable. Both the manifest digest and the native epoch must agree before execution. WASM loads require a successful response, `application/wasm`, the WASM magic bytes, and the expected SHA-256 digest.

## Execution and limits

Opening a replay or sandbox explicitly loads the lab. No WASM or editor code is downloaded during ordinary browsing. A single ordinary Worker loads and compiles the modules, creates a fresh simulator instance for every execution, and performs parsing, independent event checking, hashing, and timeline preparation. Only compact results return to the UI. Shared memory, Pthreads, cross-origin isolation, and a server execution service are unnecessary.

The compiled module is cached inside that Worker. Cancel terminates the Worker, rejects its active promise, and invalidates the job identity. A subsequent run creates a new Worker. A separate 60-second loading/execution watchdog bounds stalled downloads and runtime failures; the actual simulation contract remains 4,096 cycles. Workloads allow eight initiators, aligned byte addresses 0–16,380, at most 1,024 reads per initiator and 4,096 total, gaps 0–64, and after-accept/after-response dependencies. Empty individual initiators are valid; an entirely empty workload is not. Repeat reads, ordered segments, and read sequences compile to the same neutral driver format.

Published replay preserves each run ID, timeout, bank stalls, C++ injection, and SystemVerilog injection mask. Exact raw-event hashing is separate from checker validity. Reproducing the invalid-reference control must still produce `HARNESS_INVALID` and withhold its comparative performance claim. Hash agreement demonstrates reproduction of the site's artifact, not independent authentication of the site.

Sandbox runs use clean reference options. Its guided permutation assigns original streams `[0,4,1,5,2,6,3,7]` to destination initiators 0–7. Complete stream contents and order stay fixed. Every shown cycle count and prediction comes from the current execution; a stored in-session baseline supplies the before row. The editor changes the workload itself. Live outcomes never change the frozen decision map, discovery ledger, or repair acceptance.

The browser checker independently implements the existing Python contract: event structure, reset, operation lifecycle, address-to-bank/row mapping, release timing, one bank acceptance per cycle, response latency, deterministic memory data, summary agreement, timeouts, and harness monitor failures. The browser animation uses only observed boundary events. Internal contention signals remain part of the existing recorded diagnostic view.

## Native receipt verification

```bash
python3.12 -m rift browser-verify --receipt /path/to/receipt.json
```

Use the matching source checkout, browser manifest, model specifications, and known native builds. Verification checks bounded inputs and allowlisted configurations/models/options before invoking those runners. Receipt data cannot select executables or output paths. It reconstructs raw events with the original run IDs, compares SHA-256 digests, and runs the original Python checker. Runtime timing telemetry is deliberately excluded from semantic comparison. Native outputs are temporary; a separate verification report is written under `build/browser-verification/`. An explicit `--out` uses exclusive creation and cannot overwrite a report or evidence file. Verification earns zero discovery credit. This release's exact native build identity is macOS arm64; another platform's binary needs separate qualification.

## Tests

```bash
python3.12 -m unittest discover -s tests -t .
PYTHONPATH=. python3.12 scripts/browser_fixtures.py
npm --prefix ui run build
cd ui
npx playwright install firefox webkit
npx playwright test
npx playwright test -c playwright.browser.config.ts
npx playwright test -c playwright.lab.config.ts
```

The engine suite runs all six cases, both reduced witnesses, and 289 map cells in Chromium, Firefox, and WebKit. Additional native C++/Python oracles exercise random workloads, maximum counts, gaps, high addresses, idle initiators, and timeouts. Corrupted event streams and exact tie/margin boundaries are independently checked. The production UI suite covers replay, winner change, editor, receipt download, map integration, cancellation, missing modules, responsive layouts, and keyboard focus. `RIFT_TEST_URL=https://preview-host` runs the same UI checks against a deployed package.

On macOS 27, Playwright Firefox may try to access the real Firefox application-data directory despite using a temporary profile ([upstream issue 42768](https://github.com/microsoft/playwright/issues/42768)). The test helper starts the same engine with a separately named test application-data directory, using a copy of its application descriptor and a launch wrapper. It does not read the user's browser profile or change sandbox, signing, or privacy permissions.

## Deploy and roll back

Only `ui/dist` is uploaded to the dedicated Cloudflare Pages project `rift`. The existing Cloudflare project is untouched. Public execution is entirely static; search, repair, formal checks, and artifact generation stay local. The production domain is `https://rift-hxp.pages.dev`.

The original production deployment is `15e4987f-3e15-40ab-91ca-04df742d95d8`, accessible at `https://15e4987f.rift-hxp.pages.dev`. In Cloudflare Workers & Pages → rift → Deployments, select that production deployment's menu and **Rollback to this deployment**. Preview deployments cannot serve as rollback targets. Keep the baseline ZIP in `build/browser-baseline/rift-baseline.zip` as an additional recovery copy.

The enhanced package must pass preview checks before that exact ZIP is uploaded as production. Verify `.wasm` MIME, magic, and digest on the deployed host; a missing asset can otherwise receive Cloudflare's HTML SPA fallback with status 200. Direct Upload supports future Wrangler automation; switching to built-in Git integration requires a separate Pages project.
