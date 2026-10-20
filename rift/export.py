"""Evidence export: self-contained, digest-verified bundles under evidence/.

A bundle copies the requested study/run, every run it references (raw events,
workloads, runner summaries, independent checks, manifests), the source/tool
locks, configurations and assertion register, and writes a bundle manifest
with per-file digests. Each copied run's manifest digest is re-verified before
inclusion; a mismatch aborts the export.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from rift.contracts.canonical import digest, file_digest, read_json
from rift.paths import CONFIGS, EVIDENCE, LOCKS, ROOT, RUNS, STUDIES, rel
from rift.store import verify_run


def locate(run_id: str) -> Path:
    for base in (STUDIES, RUNS):
        p = base / run_id
        if p.exists():
            return p
    raise FileNotFoundError(run_id)


def _collect_ids(obj, out: set):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.endswith("run_ids") and isinstance(v, dict):
                out.update(x for x in v.values() if isinstance(x, str))
            elif k.endswith("run_ids") and isinstance(v, list):
                out.update(x for x in v if isinstance(x, str))
            elif k in ("run_id", "comparison_run_id") and isinstance(v, str):
                out.add(v)
            else:
                _collect_ids(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect_ids(v, out)


def referenced_runs(path: Path, credited_only: bool) -> set[str]:
    ids: set[str] = set()
    for f in path.glob("*.json"):
        if f.name == "manifest.json":
            continue
        _collect_ids(read_json(f), ids)
    for f in path.glob("*.jsonl"):
        with open(f) as fh:
            for line in fh:
                e = json.loads(line)
                if credited_only and not e.get("discovery_credit") and (e.get("verdict") or {}).get("verdict") != "VALID_COUNTEREXAMPLE":
                    continue
                _collect_ids({k: e.get(k) for k in ("rtl", "prediction")}, ids)
                for d in (e.get("rtl") or {}).values():
                    if isinstance(d, dict) and d.get("run_id"):
                        ids.add(d["run_id"])
    return {i for i in ids if (RUNS / i).exists()}


def export(run_id: str, name: str | None = None, include_all_runs: bool = False) -> dict:
    src = locate(run_id)
    m = read_json(src / "manifest.json")
    name = name or f"{m.get('kind', 'bundle')}-{run_id}"
    dst = EVIDENCE / name
    if dst.exists():
        raise FileExistsError(f"evidence bundle {rel(dst)} already exists (bundles are immutable)")
    dst.mkdir(parents=True)
    shutil.copytree(src, dst / "primary" / run_id)
    is_screen = m.get("kind") == "phase0_screen"
    runs = referenced_runs(src, credited_only=is_screen and not include_all_runs)
    verified = []
    for rid in sorted(runs):
        v = verify_run(rid)
        if not v["ok"]:
            shutil.rmtree(dst)
            raise RuntimeError(f"run {rid} failed digest verification: {v['problems']}")
        shutil.copytree(RUNS / rid, dst / "runs" / rid)
        verified.append(rid)
    (dst / "locks").mkdir()
    for f in LOCKS.glob("*.json"):
        shutil.copy2(f, dst / "locks" / f.name)
    (dst / "configs").mkdir()
    for f in CONFIGS.glob("*.json"):
        shutil.copy2(f, dst / "configs" / f.name)
    (dst / "LIMITATIONS.txt").write_text(LIMITATIONS)
    files = {}
    for p in sorted(dst.rglob("*")):
        if p.is_file():
            files[str(p.relative_to(dst))] = file_digest(p)
    bundle = {
        "schema_version": 1,
        "bundle": name,
        "primary": run_id,
        "primary_kind": m.get("kind"),
        "primary_manifest_digest": m.get("manifest_digest"),
        "runs_included": verified,
        "runs_policy": "all referenced runs" if (include_all_runs or not is_screen) else "credited/valid-counterexample runs only; full ledger retained in primary",
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": files,
    }
    bundle["bundle_digest"] = digest(bundle, exclude=("bundle_digest",), strict=False)
    with open(dst / "bundle_manifest.json", "x") as f:
        json.dump(bundle, f, indent=2)
    return {"bundle": rel(dst), "runs_included": len(verified), "files": len(files), "bundle_digest": bundle["bundle_digest"]}


LIMITATIONS = """RIFT evidence bundle - scope and limitations

* Reference: pinned pulp-platform tcdm_interconnect (2967d8d) + common_cells
  (015917f) simulated with Verilator 5.053 through the RIFT wrapper and C++
  driver. RTL is a reference implementation, not silicon. Cycle makespan at a
  common abstract clock; no physical time, area, power or frequency claim.
* Vendor concurrent assertions are excluded under VERILATOR (see
  locks/assertion_exclusions.json); acceptance relies on RIFT's counted
  monitors and the independent event checker.
* Audit cases were authored by the implementer (authored defects, a permitted
  approximation control). None is independently authored or naturally
  occurring. Public patterns L/B/M carry zero discovery credit.
* Reductions claim at most local 1-minimality under the recorded edit set.
* Repair acceptance is under contract repair-acceptance-v1 on the sealed
  held-out baskets heldout-v1 and heldout-v2; it is not a research-study result.
* Executions are native darwin-arm64; the Linux reproducibility target was not
  exercised.
"""
