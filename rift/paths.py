"""Repository-relative locations used by every component."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIGS = ROOT / "configs"
LOCKS = ROOT / "locks"
VENDOR = ROOT / "vendor"
BUILD = ROOT / "build"
# Tests redirect the store with RIFT_ARTIFACTS so they never mix with recorded evidence.
ARTIFACTS = Path(os.environ.get("RIFT_ARTIFACTS", ROOT / "artifacts"))
RUNS = ARTIFACTS / "runs"
STUDIES = ARTIFACTS / "studies"
EVIDENCE = ROOT / "evidence"
EXPERIMENTS = ROOT / "experiments"
TOOLS = ROOT / ".tools"
OSS_CAD_BIN = TOOLS / "oss-cad-suite-20261016" / "oss-cad-suite" / "bin"


def rel(path: Path) -> str:
    """Path relative to the repository root, for manifests."""
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)
