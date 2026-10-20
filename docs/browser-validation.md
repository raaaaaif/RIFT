# Browser validation

The public site at <https://rift-hxp.pages.dev> executes the existing RTL driver and compiled models through WebAssembly. The native research reference remains `epoch-dfa3739b2a85`.

Runtime build: `sha256:39dfefc6a52091058dbc8a57da3232c18cdc012eddc18157a4f4a9d6b3d76dc7`.

## Event and model parity

Six published cases, two reduced witnesses, and all 289 map workloads were replayed across Chromium, Firefox, and WebKit, against both RTL designs. The 1,782 raw event-stream hash comparisons passed. Original run IDs, stalls, injection options, and timeouts are retained, including the invalid-reference control.

Additional fixtures cover 23 workloads across three models, native C++/Python semantic agreement, WASM/C++ raw hashes, 14 checker streams including corruption, and 30 verdict boundary/failure-precedence cases. Exact model semantic fields are compared separately from runtime telemetry.

The guided experiment reproduced these measured outcomes:

| Workload | Crossbar RTL | Butterfly RTL | Original B model | Repaired B model |
|---|---:|---:|---:|---:|
| Pattern M | 41 | 65 | 33 | 65 |
| Complete streams reassigned | 41 | 33 | 33 | 33 |

A downloaded production receipt was reproduced by the known native runners and original Python checker. All five event digests and outcomes matched.

## Regression and failure coverage

| Suite | Recorded result |
|---|---|
| Python, including replay/receipt boundary checks | 40 passed |
| Original browser suite after the final timing-grid fix | 36 passed |
| Engine suite across three browsers | 9 top-level tests passed |
| Production UI suite, including touch | 43 passed; 2 instrumentation-only skips |
| Public distribution verification | All 239 served files matched on preview and production |
| Isolated complete research pipeline | Completed; compared scientific results agreed |

The two skips are Chrome debugging-protocol measurements unavailable in Firefox and WebKit. Functional tests execute in all three engines. Test counts and event-stream comparison counts describe different layers and should not be added together.

Coverage includes maximum workload counts, idle initiators, dependency types, gap/address boundaries, malformed input, corrupted events, checker failures, timeouts, missing or damaged modules, mixed manifest identities, cancellation, rapid reruns, stale messages, failed requests, and recovery. Responsive checks include 320, 390, 768, and 1440 pixels, keyboard focus, reduced motion, and touch.

Live computer-use reviews covered local production, Cloudflare preview, and Cloudflare production. Installed Safari separately executed both guided workloads. Final interaction fixes preserve editor drafts on collapse and reveal/focus operations selected from timing grids. The engine and scientific results were unchanged by those fixes.

## Payload and timings

Measured on the test Mac with Playwright 1.64.1 and Chrome 155.0.8059.85:

| Metric | Result |
|---|---:|
| Additional initial JavaScript | 1,646 gzip bytes |
| Three modules and their loaders | 322,485 gzip bytes |
| Ordinary browsing WASM requests | 0 |
| Cold production Worker run | 216.9 ms |
| Five warm production Worker runs | 27.9–40.4 ms |
| Visible action feedback under throttling | 7.2 ms |
| Throttled cold Worker run | 4,754.1 ms |

Worker timings include loading, fresh-instance setup, simulation, checking, and timeline preparation. They exclude the initial lab-interface and manifest loading before Worker startup. Gzip measurements describe the reviewed files, independent of the CDN's transfer encoding.

The slower-loading test combines 4× page CPU slowdown with explicit runtime-asset delays of 150 ms plus uncompressed size at 200,000 bytes/second. It is synthetic, not a physical low-end-device measurement.

After forced GC at runs 5, 15, and 30, Worker JS heap use was 1,404,928, 1,488,400, and 1,502,020 bytes. Reported backing storage stayed at 222,260 bytes. This measures Worker JS heap behavior, not total process RSS or peak WASM memory.

## Scope and reproduction

Browser parity reproduces artifacts and validates the implemented contract. It is not a formal equivalence proof or independent authentication of the website. The repaired model retains its research limitations, including remaining errors on the decision map. Native build identity is currently qualified on macOS arm64.

The public repository includes the tests and frozen browser reference records. Local execution logs, temporary pipeline copies, and deployment ZIPs are not required for a normal clone or static build and are not included. [Setup](setup.md) describes each test layer. [Browser execution](browser-execution.md) documents manifests, build locks, and receipts.

## Public repository packaging

The initial public snapshot updates the UI build dependency from Vite 7.0.4 to 7.3.7 to resolve reported development-server advisories. The runtime WASM, event-checking contracts, native sources, and recorded scientific artifacts are unchanged. The production timing/payload measurements above describe the deployed release; they are not new benchmark measurements of the updated bundler.

The publication snapshot was checked separately with a fresh dependency install and production build: 20 Python contract/receipt tests, 15 Chromium production UI tests, and six engine tests across Chromium, Firefox, and WebKit passed. Those six engine tests include all 1,782 event-hash comparisons plus cancellation, stream preservation, rapid reruns, corrupted events, and mixed-release rejection. `npm audit` reported zero known vulnerabilities for the pinned dependency tree at publication time. The native scientific pipeline was not rerun for this documentation and build-tool update.
