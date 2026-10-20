# Setup and reproduction

There are two independent entry points: the shipped browser experience and the native research pipeline. A local UI build does not require Verilator or Emscripten.

## Shipped browser experience

Use Node.js 20.19+ or 22.12+, npm, and Python 3 for the static server:

```bash
git clone https://github.com/raaaaaif/RIFT.git
cd RIFT
npm --prefix ui ci
npm --prefix ui run build
python3 -m http.server 8770 --bind 127.0.0.1 --directory ui/dist
```

Open <http://127.0.0.1:8770/>. The repository includes the frozen public views, event data, replay manifest, and three qualified browser modules. Both published RTL replay and the workload experiment run on the visitor's device.

The production static build is self-contained. Vite development mode uses the native API instead, so complete the native setup and generate its artifacts before using the development server described below.

## Native research environment

The recorded execution environment is macOS arm64, Python 3.12, Apple Clang with C++17, and OSS CAD Suite 2026-10-16. The exact tool versions and archive SHA-256 are in `locks/toolchain.lock.json`. Linux is a future qualification target; the lock records a Linux archive digest but the current doctor compares against the qualified macOS tool versions.

Have several GiB available for the toolchain, native builds, and generated run store. Trace-enabled diagnostic builds also require `lz4` headers, available through `brew install lz4`. The original installation excluded unused FPGA place-and-route and VHDL components; that selection is recorded in the lock. Full extraction is also possible when storage permits.

From the repository root, download the pinned archive and check its full digest before extracting:

```bash
mkdir -p .tools/oss-cad-suite-20261016
curl -fL \
  https://github.com/YosysHQ/oss-cad-suite-build/releases/download/2026-10-16/oss-cad-suite-darwin-arm64-20261016.tgz \
  --output .tools/oss-cad-suite-darwin-arm64-20261016.tgz
python3.12 - <<'PY'
import hashlib
import json
from pathlib import Path
lock = json.loads(Path('locks/toolchain.lock.json').read_text())['bundle']
archive = Path('.tools') / lock['asset']
with archive.open('rb') as stream:
    actual = hashlib.file_digest(stream, 'sha256').hexdigest()
if actual != lock['sha256_published']:
    raise SystemExit('Toolchain archive digest mismatch; do not extract')
print('Archive digest verified:', actual)
PY
```

After that check succeeds:

```bash
tar -xzf .tools/oss-cad-suite-darwin-arm64-20261016.tgz \
  -C .tools/oss-cad-suite-20261016
python3.12 -m rift fetch
python3.12 -m rift doctor
```

RIFT prepends the repository-local toolchain directory when invoking tools. It does not need a global replacement of Verilator or Yosys. `fetch` checks out the exact upstream commits under `vendor/`; those sources are retrieved rather than duplicated in this repository.

## Generate the research artifacts

Install the UI dependencies as above, then use a fresh research checkout:

```bash
python3.12 -m rift pipeline
```

Run directories are immutable. The pipeline also regenerates its checkpoint, case registry, static presentation data, viewer build, and evidence bundles, so a second checkout is useful when preserving the shipped website snapshot.

The public Git repository contains selected run copies and bundle manifests. Large search/verification/map run copies and the working `artifacts/` store are omitted. The pipeline reconstructs that working store; fresh run IDs and timestamps differ, while workload/model/configuration identities and scientific outcomes should agree. See [reproduction](reproduction.md) for stage commands and expected results.

After native artifacts exist, `python3.12 -m rift serve --port 8770 --allow-run` serves the investigation with budgeted native replay. Before that point, use the static-server path to inspect the shipped data.

For UI development, leave the native server on port 8770 running in one terminal and run `npm --prefix ui run dev` in another. Vite prints its own URL and proxies `/api` requests to the native server.

## Test layers

The browser lab tests the production static build. Its Chromium project uses installed Google Chrome:

```bash
cd ui
npx playwright test -c playwright.lab.config.ts --project=chromium
```

Install Playwright Firefox and WebKit with `npx playwright install firefox webkit` to include them. Omit `--project` to run all configured engines.

For native and original server-based regression coverage, set up the native toolchain and generate the artifacts, then run from the repository root:

```bash
python3.12 -m unittest discover -s tests -t .
PYTHONPATH=. python3.12 scripts/browser_fixtures.py
cd ui
npx playwright test
npx playwright test -c playwright.browser.config.ts
npx playwright test -c playwright.lab.config.ts
```

The fixture generator creates the independent native C++/Python oracles consumed by the full browser-engine suite. The original UI suite starts native servers on ports 8771/8772 and a static server on 8773. The lab uses port 8790 by default. These checks are separate from an ordinary UI build.

## Rebuild browser engines or verify a receipt

See [browser execution](browser-execution.md) for the pinned Emscripten installer, runtime adaptations, manifest generation, and native receipt verifier. Emscripten is needed only when rebuilding the WASM engines. The browser installer requires at least 3.7 GB free.

Native receipt verification requires the matching source/model/browser identities and qualified native binaries. It does not accept arbitrary executable paths from a receipt. A different platform's native binary needs separate qualification before claiming exact build-identity reproduction.
