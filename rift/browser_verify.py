"""Independently re-execute a browser receipt through the native runner/checker.

Receipt data never supplies executable paths, model parameters, or command text.
Outputs are isolated from the research store and earn no discovery credit.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

from rift import toolchain
from rift.contracts.canonical import bytes_digest, file_digest, read_json
from rift.contracts.config import load_config
from rift.contracts.workload import validate_and_compile
from rift.evaluate.checker import check_events
from rift.model.compiled import run_batch
from rift.model.registry import get_spec, model_digest
from rift.paths import ROOT
from rift.rtl import reference_epoch, reference_identity

CHECK_FIELDS = ("status", "functional_valid", "workload_digest", "expected_operations", "makespan",
                "makespan_from_events_unvalidated", "accepted", "completed", "offered", "monitor_failures", "violation_counts")


def run_options(options: dict, banks: int) -> list[str]:
    if not isinstance(options, dict) or set(options) != {"timeout", "stalls", "inject", "sv_inject"}:
        raise ValueError("Unsupported execution options")
    def integer(v, low, high):
        if type(v) is not int or not low <= v <= high:
            raise ValueError(f"Execution option outside [{low}, {high}]")
        return v
    timeout = integer(options["timeout"], 1, 4096)
    mask = integer(options["sv_inject"], 0, 127)
    if options["inject"] not in (None, "unstable_request", "oracle_offset"):
        raise ValueError("Unknown instrument control")
    stalls = options["stalls"]
    if not isinstance(stalls, list) or len(stalls) > 64:
        raise ValueError("Too many bank stalls")
    args = ["--timeout", str(timeout)]
    for s in stalls:
        if not isinstance(s, list) or len(s) != 3:
            raise ValueError("Malformed bank stall")
        bank, start, length = integer(s[0], 0, banks - 1), integer(s[1], 0, 4096), integer(s[2], 1, 4096)
        args += ["--stall", f"{bank}:{start}:{length}"]
    if options["inject"]:
        args += ["--inject", options["inject"]]
    if mask:
        args += ["--sv-inject", str(mask)]
    return args


def verify_receipt(path: Path) -> dict:
    if path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Receipt exceeds 2 MiB")
    receipt = read_json(path)
    if receipt.get("schema_version") != 1 or receipt.get("kind") != "rift-browser-receipt" or receipt.get("discovery_credit") != 0:
        raise ValueError("Unsupported receipt")
    manifest = read_json(ROOT / "ui/public/browser/manifest.json")
    if file_digest(ROOT / "oracle/fastmodel.cpp") != manifest["toolchain"]["fastmodel_source_sha256"]:
        raise ValueError("Compiled model source differs from the browser release")
    if any(receipt.get(k) != manifest[k] for k in ("build_id", "manifest_digest", "reference_epoch")):
        raise ValueError("Receipt belongs to a different browser release; use its matching source/build")
    modules = {k: {f: m[f] for f in ("wasm_sha256", "js_sha256", "build_key")} for k, m in manifest["modules"].items()}
    if receipt.get("modules") != modules:
        raise ValueError("Receipt module fingerprints differ from this release")
    cfg_a = load_config("lic8x8")
    compiled = validate_and_compile(receipt["workload"], cfg_a)
    if compiled.digest != receipt.get("workload_digest"):
        raise ValueError("Workload digest mismatch")
    models = receipt.get("models", {})
    if set(models) != {"A", "parent", "repaired"}:
        raise ValueError("Unexpected model roles")
    for entry in models.values():
        mid = entry.get("model_id")
        if mid not in manifest["models"] or entry.get("model_digest") != model_digest(get_spec(mid)):
            raise ValueError("Unknown or changed model")
    runs = receipt.get("executions", {})
    if set(runs) != {"rtl-A", "rtl-B", "model-A", "model-parent", "model-repaired"}:
        raise ValueError("Receipt must contain the two RTL and three model executions")
    results = {}
    for key, expected in runs.items():
        is_model = key.startswith("model-")
        config_id = "lic8x8" if key in ("rtl-A", "model-A") else "bfly4_8x16"
        if expected.get("config_id") != config_id:
            raise ValueError("Unexpected configuration")
        cfg = load_config(config_id)
        args = run_options(expected.get("options"), cfg.num_out)
        rid = expected.get("run_id")
        if not isinstance(rid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", rid):
            raise ValueError("Unsupported event stream identity")
        with tempfile.TemporaryDirectory(prefix="rift-browser-verify-") as td:
            temp = Path(td)
            if is_model:
                mid = models[key.removeprefix("model-")]["model_id"]
                if expected.get("model_id") != mid or manifest["models"][mid]["config_id"] != config_id:
                    raise ValueError("Model execution identity mismatch")
                if rid != "fastmodel-0" or expected["options"] != {"timeout": 4096, "stalls": [], "inject": None, "sv_inject": 0}:
                    raise ValueError("Compiled model execution options are fixed")
                spec = get_spec(mid)
                summary = run_batch(spec, cfg, [compiled], events=True, workdir=temp)[0]
                events = summary.pop("events")
                raw = (temp / "e0.jsonl").read_bytes()
                check = check_events(compiled, cfg, events, summary, "model", resp_lat=spec.get("resp_lat", 1))
            else:
                bm = toolchain.build(cfg)
                if reference_epoch(reference_identity(cfg, bm)) != receipt["reference_epoch"]:
                    raise ValueError("Native reference epoch changed")
                if reference_identity(cfg, bm) != manifest["modules"][config_id]["native_reference"]:
                    raise ValueError("Native reference build changed")
                (temp / "workload.txt").write_text(compiled.to_text())
                subprocess.run([str(ROOT / bm["binary"]), "--workload", str(temp / "workload.txt"),
                                "--summary", str(temp / "summary.json"), "--events", str(temp / "events.jsonl"),
                                "--run-id", rid, *args], check=True, capture_output=True, timeout=30)
                raw = (temp / "events.jsonl").read_bytes()
                events = [json.loads(line) for line in raw.splitlines() if line]
                summary = read_json(temp / "summary.json")
                check = check_events(compiled, cfg, events, summary, "rtl", timeout=expected["options"]["timeout"])
            mismatches = [f for f in CHECK_FIELDS if check.get(f) != expected.get("check", {}).get(f)]
            hash_match = bytes_digest(raw) == expected.get("events_sha256")
            results[key] = {"events_sha256": bytes_digest(raw), "events_match": hash_match,
                            "checker_matches": not mismatches, "checker_mismatches": mismatches, "check": check,
                            "ok": hash_match and not mismatches}
    return {"schema_version": 1, "kind": "browser_native_verification", "receipt_sha256": bytes_digest(path.read_bytes()),
            "build_id": receipt["build_id"], "reference_epoch": receipt["reference_epoch"], "workload_digest": compiled.digest,
            "ok": all(r["ok"] for r in results.values()), "runs": results, "discovery_credit": 0,
            "scope": "native event reproduction and original Python checker; separate from research/repair acceptance"}
