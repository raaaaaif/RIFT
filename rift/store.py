"""Append-only artifact store.

Every execution receives a fresh run directory under artifacts/runs/ that is
created exclusively (an existing directory is never reused) and an entry in the
append-only index artifacts/index.jsonl. Artifact digests are recorded in the
run manifest once all files are written; a manifest is never rewritten.
"""

from __future__ import annotations

import gzip
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any, Iterator

from rift.contracts.canonical import digest, file_digest, read_json
from rift.paths import ARTIFACTS, RUNS, rel

INDEX = ARTIFACTS / "index.jsonl"


def new_run_id(kind: str) -> str:
    t = time.time()
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime(t)) + f"{int((t % 1) * 1e6):06d}Z"
    return f"{stamp}-{kind}-{secrets.token_hex(3)}"


class RunDir:
    def __init__(self, kind: str, root: Path = RUNS):
        self.kind = kind
        self.run_id = new_run_id(kind)
        self.path = root / self.run_id
        self.path.mkdir(parents=True, exist_ok=False)

    def file(self, name: str) -> Path:
        return self.path / name

    def write_text(self, name: str, text: str) -> Path:
        p = self.file(name)
        with open(p, "x") as f:
            f.write(text)
        return p

    def write_json(self, name: str, obj: Any) -> Path:
        p = self.file(name)
        with open(p, "x") as f:
            json.dump(obj, f, indent=2)
            f.write("\n")
        return p

    def finalize(self, manifest: dict) -> dict:
        """Record artifact digests and write the immutable manifest."""
        arts = {}
        for p in sorted(self.path.rglob("*")):
            if p.is_dir() or p.name == "manifest.json":
                continue
            arts[str(p.relative_to(self.path))] = {"sha256": file_digest(p), "bytes": p.stat().st_size}
        manifest = dict(manifest)
        manifest["run_id"] = self.run_id
        manifest["artifacts"] = arts
        manifest["manifest_digest"] = digest(manifest, exclude=("manifest_digest",), strict=False)
        self.write_json("manifest.json", manifest)
        append_index({
            "run_id": self.run_id,
            "kind": self.kind,
            "path": rel(self.path),
            "manifest_digest": manifest["manifest_digest"],
            "status": manifest.get("status"),
            "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "tags": manifest.get("tags", []),
        })
        return manifest


def append_index(entry: dict) -> None:
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, sort_keys=True) + "\n"
    fd = os.open(INDEX, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line.encode())
    finally:
        os.close(fd)


def iter_index() -> Iterator[dict]:
    if not INDEX.exists():
        return
    with open(INDEX) as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_events(path: Path) -> list[dict]:
    opener = gzip.open if str(path).endswith(".gz") else open
    events = []
    with opener(path, "rt") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def compress_file(path: Path) -> Path:
    gz = path.with_suffix(path.suffix + ".gz")
    with open(path, "rb") as src, gzip.open(gz, "xb", compresslevel=6) as dst:
        dst.write(src.read())
    path.unlink()
    return gz


def find_run(run_id: str) -> Path:
    p = RUNS / run_id
    if not p.exists():
        raise FileNotFoundError(f"run {run_id} not found")
    return p


def load_manifest(run_id: str) -> dict:
    return read_json(find_run(run_id) / "manifest.json")


def verify_run(run_id: str) -> dict:
    """Recompute artifact digests and the manifest digest."""
    path = find_run(run_id)
    m = read_json(path / "manifest.json")
    problems = []
    for name, info in m.get("artifacts", {}).items():
        p = path / name
        if not p.exists():
            problems.append(f"missing {name}")
        elif file_digest(p) != info["sha256"]:
            problems.append(f"digest mismatch {name}")
    md = digest(m, exclude=("manifest_digest",), strict=False)
    if md != m.get("manifest_digest"):
        problems.append("manifest digest mismatch")
    return {"run_id": run_id, "ok": not problems, "problems": problems}
