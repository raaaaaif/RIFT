"""Pipeline-level checks: adapter integrity, sealed-data guard, verifier boundary, toolchain semantics."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from rift.contracts.config import load_config
from rift.contracts.workload import validate_and_compile
from rift.evaluate.compare import classify
from rift.model.registry import get_spec, run_model
from rift.paths import ROOT, OSS_CAD_BIN


class SealedAccessTest(unittest.TestCase):
    def test_repair_code_path_cannot_open_heldout(self):
        import builtins
        from rift.repair.repair import SealedAccessError, _guard_open
        real, guarded = _guard_open()
        builtins.open = guarded
        try:
            with self.assertRaises(SealedAccessError):
                open(ROOT / "experiments/heldout/heldout_v1.json")
            with open(ROOT / "experiments/phase0_screen.json") as f:  # ordinary files stay readable
                self.assertIn("study_id", f.read())
        finally:
            builtins.open = real


class PatchBoundaryTest(unittest.TestCase):
    def test_benchmark_specific_patch_rejected(self):
        from rift.evaluate.verify import patch_boundary
        parent = get_spec("bank_only_v1")
        sub = {"models": {"A": "lic_exact_v1", "B": "x"}, "parent_models": {"A": "lic_exact_v1", "B": "bank_only_v1"}}
        bad = {"family": "lookup_override", "params": {"overrides": {"sha256:abc": 65}}}
        problems = patch_boundary(sub, bad, parent)
        self.assertTrue(any("outside the editable" in p for p in problems))
        self.assertTrue(any("workload identities" in p for p in problems))
        ok = {"family": "shared_link", "params": {"links": [[2, 2]]}, "applies_to": ["BFLY4"]}
        self.assertEqual(patch_boundary(sub, ok, parent), [])
        sub_a = dict(sub, models={"A": "defect_lic_unfair_arb_v1", "B": "x"})
        self.assertTrue(any("non-editable" in p for p in patch_boundary(sub_a, ok, parent)))


class RepairStructureTest(unittest.TestCase):
    def test_shared_link_2_2_reproduces_butterfly_capacity_on_patterns(self):
        cfg = load_config("bfly4_8x16")
        spec = {"model_id": "t", "family": "shared_link", "params": {"links": [[2, 2]]}, "applies_to": ["BFLY4"]}
        for n, expected in (("L", 65), ("B", 33), ("M", 65)):
            c = validate_and_compile(json.load(open(ROOT / f"experiments/workloads/{n}.json")), cfg)
            self.assertEqual(run_model(spec, cfg, c, record_events=False).makespan, expected, n)


class AdapterIntegrityTest(unittest.TestCase):
    def test_recomputation_detects_a_tampered_comparison(self):
        reg = ROOT / "experiments/cases/registry.json"
        if not reg.exists() or not (ROOT / "artifacts/runs").exists():
            self.skipTest("case registry or recorded artifacts not present")
        import os
        cid = json.load(open(reg))["cases"][0]["comparison_run_id"]
        env = {k: v for k, v in os.environ.items() if k != "RIFT_ARTIFACTS"}  # read-only view of recorded evidence
        out = subprocess.run(["python3.12", "-c", f"import json; from rift.presentation import adapter; print(json.dumps(adapter.comparison_view('{cid}')))"],
                             cwd=ROOT, capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr[-800:])
        view = json.loads(out.stdout)
        self.assertEqual(view["integrity_errors"], [])
        self.assertTrue(view["epochs_consistent"])
        # Same recomputation against a forged record must disagree.
        order = view["admitted_order"]
        forged = dict(view["model_costs"])
        forged["B"] = forged["A"]
        re = classify(order, {d: {"status": "COMPLETED", "makespan": forged[d]} for d in order},
                      {d: {"status": "COMPLETED", "makespan": view["rtl_costs"][d]} for d in order})
        self.assertNotEqual(re["verdict"], view["verdict"])

    def test_specimens_are_namespaced(self):
        from rift.presentation import adapter
        s = adapter.specimens()
        self.assertEqual(s["namespace"], "example/")
        self.assertEqual(s["evidence_basis_default"], "ILLUSTRATIVE_FIXTURE")


class ToolchainSemanticsTest(unittest.TestCase):
    """Verilator 5.053 does not honour `// pragma translate_off` (recorded in locks/preprocessing.json)."""

    def test_translate_off_is_compiled(self):
        if not (OSS_CAD_BIN / "verilator").exists():
            self.skipTest("pinned toolchain not installed")
        d = Path(tempfile.mkdtemp())
        (d / "t.sv").write_text("module t(input logic clk_i);\n// pragma translate_off\ninitial $display(\"TRANSLATE_OFF_EXECUTED\");\n// pragma translate_on\nendmodule\n")
        (d / "m.cpp").write_text('#include "Vt.h"\n#include "verilated.h"\nint main(){VerilatedContext c; Vt t(&c); t.clk_i=0; t.eval(); t.final(); return 0;}\n')
        from rift.toolchain import tool_env
        r = subprocess.run(["verilator", "--cc", "--exe", "--build", "-Wno-fatal", "--top-module", "t", "t.sv", "m.cpp", "-o", "tsim"],
                           cwd=d, capture_output=True, text=True, env=tool_env())
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        out = subprocess.run([str(d / "obj_dir/tsim")], capture_output=True, text=True).stdout
        self.assertIn("TRANSLATE_OFF_EXECUTED", out)
        shutil.rmtree(d, ignore_errors=True)


class FormalInventoryTest(unittest.TestCase):
    def test_lic2x2_harness_inventory_matches_frozen_expectation(self):
        if not (OSS_CAD_BIN / "yosys").exists():
            self.skipTest("pinned toolchain not installed")
        from rift.formal import LIC2X2_HARNESS, inventory
        inv = inventory("rift_lic2x2_formal", LIC2X2_HARNESS)
        exp = json.load(open(ROOT / "formal/expected_inventory.json"))["lic2x2"]
        self.assertTrue(inv["ok"])
        self.assertEqual({k: inv[k] for k in exp}, exp)
        self.assertEqual(inv["blackboxes"], 0)


if __name__ == "__main__":
    unittest.main()
