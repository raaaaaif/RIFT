# Third-party components

RIFT builds its reference from upstream interconnect RTL and uses existing simulation, formal, compilation, and UI tools. Their authors retain ownership of those components.

## PULP interconnect and common_cells

- [cluster_interconnect](https://github.com/pulp-platform/cluster_interconnect), commit `2967d8d17be0a6139229ca8d3d4956e182aec3de`.
- [common_cells](https://github.com/pulp-platform/common_cells), commit `015917ff33e5f944e866814f72f2074fb0f4220f`.

The referenced hardware sources carry copyright notices for ETH Zurich and the University of Bologna and the Solderpad Hardware License 0.51. The license text is included in [licenses/Solderpad-0.51.txt](licenses/Solderpad-0.51.txt). Source pins and compilation order are in [locks/sources.lock.json](locks/sources.lock.json). `python3.12 -m rift fetch` retrieves the original source checkouts and their notices.

RIFT does not claim authorship of the upstream crossbar, butterfly, or common-cell RTL. Its local wrapper and driver provide the audit harness around those implementations.

## Verilator runtime

The browser modules include a build-local adaptation of the pinned Verilator runtime. The original native source is retained unchanged. The adaptations set one context thread and select the applicable non-affinity branches. Original and adapted digests are recorded in [locks/browser-toolchain.lock.json](locks/browser-toolchain.lock.json).

The modified runtime is distributed under the upstream Artistic 2.0 option. See [licenses/Verilator-Artistic-2.0.txt](licenses/Verilator-Artistic-2.0.txt), the accompanying [upstream license text](licenses/Verilator-LICENSE.txt), and the complete runtime-source archive in `ui/public/browser/39dfefc6a5209105/`. Source headers and notices remain in that archive.

## Other tools and packages

Emscripten provides the browser compiler. OSS CAD Suite supplies Verilator, Yosys, yosys-slang, SymbiYosys, and the recorded solvers. Their qualified identities are in the toolchain locks; downloaded installations are excluded from Git.

The UI uses React, TypeScript, Vite, and Playwright. Exact npm dependency versions are recorded in `ui/package-lock.json`; package license files are supplied by their respective distributions.

No project-wide open-source license has been selected for RIFT's original code. Publishing this repository does not replace the licenses of its third-party components.
