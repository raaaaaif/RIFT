"""Static publication of the viewer's data (Cloudflare Pages / any static host).

Writes immutable JSON snapshots of every read-API response the viewer uses into
ui/public/data/. A static deployment therefore needs no backend: the viewer
reads /data/*.json, labels itself as a recorded (not live) presentation, and
hides run controls. Only artifacts belonging to published cases are copied.
The sealed held-out basket definition is never published.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from rift.paths import ROOT, RUNS, STUDIES, rel
from rift.presentation import adapter

DATA = ROOT / "ui" / "public" / "data"
ARTIFACT_FILES = ("manifest.json", "check.json", "workload.json", "runner_summary.json", "model_summary.json",
                  "comparison.json", "events.jsonl", "events.jsonl.gz", "compiled_workload.txt")


def _dump(path: Path, obj) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(obj, separators=(",", ":"), default=str)
    path.write_text(data)
    return len(data)


def publish_static(out: Path = DATA) -> dict:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    total = 0
    cases = adapter.list_cases()
    total += _dump(out / "cases.json", {"cases": cases, "run_controls_enabled": False, "mode": "static"})
    total += _dump(out / "project.json", adapter.project_record())
    total += _dump(out / "specimens.json", adapter.specimens())
    dmap = adapter.map_view()
    if dmap:
        total += _dump(out / "map.json", dmap)
    traces, artifacts = set(), set()
    for c in cases:
        view = adapter.case_view(c["case_id"])
        total += _dump(out / "case" / f"{c['case_id']}.json", view)
        cmp = view["comparison"]
        for ids in (cmp.get("rtl_run_ids") or {}, cmp.get("model_run_ids") or {}):
            traces.update(ids.values())
        red = view.get("reduction")
        if red:
            traces.update(red["reduced"]["final_rtl_run_ids"].values())
            traces.update(red["reduced"]["final_model_run_ids"].values())
        diag = adapter.diagnostic_view(c["case_id"])
        if diag:
            total += _dump(out / "diag" / f"{c['case_id']}.json", diag)
        for link in view["evidence"]:
            if link["kind"] in ("rtl", "model", "comparison"):
                artifacts.add(link["artifact_id"])
    for rid in sorted(traces):
        total += _dump(out / "trace" / f"{rid}.json", adapter.trace_selection(rid))
    copied = 0
    for rid in sorted(artifacts):
        src = RUNS / rid
        for name in ARTIFACT_FILES:
            if (src / name).exists():
                dst = out / "artifacts" / rid / name
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src / name, dst)
                copied += (src / name).stat().st_size
    return {"out": rel(out), "cases": len(cases), "traces": len(traces), "artifact_runs": len(artifacts),
            "map_cells": len(dmap["cells"]) if dmap else 0, "json_bytes": total, "artifact_bytes": copied}
