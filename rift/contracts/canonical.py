"""Canonical serialization and content digests.

Canonical form: UTF-8 JSON with lexicographically sorted object keys, no
insignificant whitespace, and integers written in base 10. Floats are not
permitted in digested contracts (workloads, configurations, monitors); exact
ratios are stored as integer numerator/denominator pairs. A digest is
"sha256:" + hex of the canonical bytes. Fields named in `exclude` (derived
identifiers such as a manifest's own digest) are removed before hashing.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


class CanonicalError(ValueError):
    pass


def _check(obj: Any, path: str = "$") -> None:
    if isinstance(obj, bool) or obj is None or isinstance(obj, str):
        return
    if isinstance(obj, int):
        return
    if isinstance(obj, float):
        raise CanonicalError(f"float at {path} is not allowed in a digested contract")
    if isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            _check(v, f"{path}[{i}]")
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(k, str):
                raise CanonicalError(f"non-string key at {path}")
            _check(v, f"{path}.{k}")
        return
    raise CanonicalError(f"unsupported type {type(obj).__name__} at {path}")


def canonical_bytes(obj: Any, exclude: Iterable[str] = (), strict: bool = True) -> bytes:
    if exclude and isinstance(obj, dict):
        obj = {k: v for k, v in obj.items() if k not in set(exclude)}
    if strict:
        _check(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(obj: Any, exclude: Iterable[str] = (), strict: bool = True) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(obj, exclude, strict)).hexdigest()


def file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def bytes_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def write_json(path: Path, obj: Any) -> None:
    """Human-readable JSON for artifacts (digests are always over canonical form)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x") as f:  # exclusive create: evidence is never overwritten
        json.dump(obj, f, indent=2, sort_keys=False)
        f.write("\n")


def write_json_replace(path: Path, obj: Any) -> None:
    """For mutable working files only (never for run evidence)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
        f.write("\n")
    tmp.replace(path)


def read_json(path: Path) -> Any:
    with open(path) as f:
        return json.load(f)
