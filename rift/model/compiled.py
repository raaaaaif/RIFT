"""Compiled (C++) fast models: same contracts as the Python models, built for speed.

The binary is content-addressed by its source digest. Model identity for a
compiled execution is the Python model digest plus the compiled source digest;
both implementations are cross-checked event-for-event by tests.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from rift.contracts.canonical import file_digest
from rift.contracts.config import ArchConfig
from rift.paths import BUILD, ROOT

SOURCE = ROOT / "oracle" / "fastmodel.cpp"


def build() -> Path:
    d = BUILD / f"fastmodel-{file_digest(SOURCE)[7:19]}"
    exe = d / "rift_fastmodel"
    if not exe.exists():
        d.mkdir(parents=True, exist_ok=True)
        subprocess.run(["c++", "-std=c++17", "-O2", str(SOURCE), "-o", str(exe)], check=True, capture_output=True, text=True)
    return exe


def supports(spec: dict) -> bool:
    fam, p = spec["family"], spec.get("params", {})
    return fam in ("crossbar", "shared_link") or (fam == "butterfly" and p.get("prio_mode", "rr") == "rr")


def args_for(spec: dict, cfg: ArchConfig) -> list[str]:
    fam, p = spec["family"], spec.get("params", {})
    a = ["--family", fam, "--num-in", str(cfg.num_in), "--num-out", str(cfg.num_out), "--resp-lat", str(spec.get("resp_lat", 1))]
    if fam == "crossbar":
        a += ["--fair", "1" if p.get("fair", True) else "0", "--lock-in", "1" if p.get("lock_in", True) else "0"]
        if p.get("bank_modulus"):
            a += ["--bank-mod", str(p["bank_modulus"])]
    elif fam == "shared_link":
        a += ["--links", ";".join(f"{g},{s}" for g, s in p["links"])]
    elif fam == "butterfly":
        if p.get("prio_mode", "rr") != "rr":
            raise ValueError("compiled butterfly supports round-robin priorities only")
        a += ["--radix", str({"BFLY4": 4, "BFLY2": 2}[cfg.topology])]
        if p.get("bank_modulus"):
            a += ["--bank-mod", str(p["bank_modulus"])]
    else:
        raise ValueError(f"family {fam} not compiled")
    return a


def run_batch(spec: dict, cfg: ArchConfig, compiled_list, events: bool = False, workdir: Path | None = None) -> list[dict]:
    exe = build()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(workdir or td)
        lines = []
        for i, c in enumerate(compiled_list):
            wf = tmp / f"w{i}.txt"
            wf.write_text(c.to_text())
            lines.append(f"{wf} {tmp / f's{i}.json'} {tmp / f'e{i}.jsonl' if events else '-'}")
        (tmp / "batch.txt").write_text("\n".join(lines) + "\n")
        subprocess.run([str(exe)] + args_for(spec, cfg) + ["--batch", str(tmp / "batch.txt")], check=True, capture_output=True, text=True)
        out = []
        for i in range(len(compiled_list)):
            s = json.loads((tmp / f"s{i}.json").read_text())
            if events:
                s["events"] = [json.loads(x) for x in (tmp / f"e{i}.jsonl").read_text().splitlines() if x]
            out.append(s)
        return out
