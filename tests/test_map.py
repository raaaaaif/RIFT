"""Decision-map family: exact knobs, no butterfly bank conflicts, landmark coordinates, adapter integrity."""

import json
import unittest

from rift.contracts.config import load_config
from rift.contracts.workload import validate_and_compile
from rift.paths import ROOT
from rift.workloads.generators import decision_map_cell, nominal_features, slot_feasibility

MANIFEST = json.load(open(ROOT / "experiments/maps/decision_map_v1.json"))


class GeneratorTest(unittest.TestCase):
    def test_every_grid_target_is_realized_exactly_with_distinct_butterfly_banks(self):
        cfg_a, cfg_b = load_config("lic8x8"), load_config("bfly4_8x16")
        gen = MANIFEST["generator"]
        xs, ys = MANIFEST["axes"]["x"]["levels"], MANIFEST["axes"]["y"]["levels"]
        for i, s in enumerate(xs):
            for j, c in enumerate(ys):
                w = decision_map_cell(s, c, gen["seed_base"] + 17 * i + j, gen["reads_per_initiator"])
                validate_and_compile(w, cfg_a)
                comp = validate_and_compile(w, cfg_b)
                f = nominal_features(comp)
                self.assertEqual(f["route_sharing"], [s, 128], (i, j))
                self.assertEqual(f["crossbar_collisions"], [2 * c, 256], (i, j))
                for t in range(gen["reads_per_initiator"]):
                    banks = [ops[t].byte_address // 4 % cfg_b.num_out for ops in comp.per_master]
                    self.assertEqual(len(set(banks)), 8, (i, j, t))

    def test_generator_is_deterministic(self):
        self.assertEqual(decision_map_cell(40, 72, 71123), decision_map_cell(40, 72, 71123))

    def test_only_the_parity_blocked_slot_is_infeasible(self):
        self.assertEqual([k for k, v in slot_feasibility().items() if not v], [(3, 4)])


class LandmarkTest(unittest.TestCase):
    def test_calibration_patterns_sit_at_their_corners(self):
        cfg = load_config("bfly4_8x16")
        got = {n: nominal_features(validate_and_compile(json.load(open(ROOT / f"experiments/workloads/{n}.json")), cfg)) for n in "LBM"}
        self.assertEqual(got["L"], {"route_sharing": [128, 128], "crossbar_collisions": [0, 256]})
        self.assertEqual(got["B"], {"route_sharing": [0, 128], "crossbar_collisions": [256, 256]})
        self.assertEqual(got["M"], {"route_sharing": [120, 128], "crossbar_collisions": [16, 256]})


class MapIntegrityTest(unittest.TestCase):
    def test_recorded_map_verifies_and_a_tampered_cell_is_caught(self):
        import os
        import subprocess
        reg = ROOT / "experiments/cases/registry.json"
        if not reg.exists() or not json.load(open(reg)).get("map_study"):
            self.skipTest("no decision map recorded")
        env = {k: v for k, v in os.environ.items() if k != "RIFT_ARTIFACTS"}  # read-only view of recorded evidence
        code = (
            "import json, copy\n"
            "from rift.presentation import adapter\n"
            "from rift.paths import STUDIES\n"
            "m = json.load(open(STUDIES / adapter.registry()['map_study'] / 'map.json'))\n"
            "_, ok = adapter.check_map(m)\n"
            "t = copy.deepcopy(m); c = t['cells'][100]\n"
            "c['rtl']['B']['makespan'] += 7\n"
            "_, bad = adapter.check_map(t)\n"
            "t2 = copy.deepcopy(m); t2['cells'][5]['verdict']['parent']['verdict'] = 'VALID_NO_REVERSAL' if t2['cells'][5]['verdict']['parent']['verdict'] != 'VALID_NO_REVERSAL' else 'VALID_COUNTEREXAMPLE'\n"
            "_, bad2 = adapter.check_map(t2)\n"
            "print(json.dumps([len(ok), len(bad), len(bad2)]))\n"
        )
        out = subprocess.run(["python3.12", "-c", code], cwd=ROOT, capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr[-800:])
        ok, bad, bad2 = json.loads(out.stdout)
        self.assertEqual(ok, 0)
        self.assertGreater(bad, 0)
        self.assertGreater(bad2, 0)


if __name__ == "__main__":
    unittest.main()
