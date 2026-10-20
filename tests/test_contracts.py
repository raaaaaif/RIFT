import json
import unittest

from rift.contracts.canonical import CanonicalError, digest
from rift.contracts.config import ConfigError, load_config, validate_config
from rift.contracts.workload import WorkloadError, read_sequences, repeat_read, to_read_sequences, validate_and_compile
from rift.evaluate.compare import classify, margin_met
from rift.paths import ROOT


class CanonicalTests(unittest.TestCase):
    def test_digest_is_order_independent(self):
        self.assertEqual(digest({"a": 1, "b": [1, 2]}), digest({"b": [1, 2], "a": 1}))

    def test_floats_rejected(self):
        with self.assertRaises(CanonicalError):
            digest({"x": 0.5})

    def test_exclusion(self):
        self.assertEqual(digest({"a": 1, "self": "x"}, exclude=("self",)), digest({"a": 1}))


class ConfigTests(unittest.TestCase):
    def test_phase0_configs_valid(self):
        for c in ("lic2x2", "lic8x8", "bfly4_8x16"):
            cfg = load_config(c)
            self.assertEqual(cfg.num_out * (1 << cfg.addr_mem_width), 4096)

    def test_capacity_mismatch_rejected(self):
        raw = json.load(open(ROOT / "configs/lic8x8.json"))
        raw["addr_mem_width"] = 10
        with self.assertRaises(ConfigError):
            validate_config(raw)

    def test_resp_lat_fixed(self):
        raw = json.load(open(ROOT / "configs/lic8x8.json"))
        raw["resp_lat"] = 2
        with self.assertRaises(ConfigError):
            validate_config(raw)


class WorkloadTests(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config("lic8x8")

    def test_supplied_patterns_compile(self):
        for n in "LBM":
            c = validate_and_compile(json.load(open(ROOT / f"experiments/workloads/{n}.json")), self.cfg)
            self.assertEqual(c.total_ops, 256)

    def test_pattern_m_segment_order(self):
        c = validate_and_compile(json.load(open(ROOT / "experiments/workloads/M.json")), self.cfg)
        m7 = [op.byte_address for op in c.per_master[7]]
        self.assertEqual(m7, [32] * 8 + [28] * 24)

    def test_rejections(self):
        bad = [
            repeat_read([1, 4, 8, 12, 16, 20, 24, 28], 1),       # unaligned
            repeat_read([16384] + [0] * 7, 1),                    # out of range
            repeat_read([0] * 7, 1),                              # wrong initiator count
            repeat_read([0] * 8, 0),                              # zero count
        ]
        for w in bad:
            with self.assertRaises(WorkloadError):
                validate_and_compile(w, self.cfg)
        w = read_sequences([[{"byte_address": 0, "release": "after_store"}]] + [[]] * 7)
        with self.assertRaises(WorkloadError):
            validate_and_compile(w, self.cfg)
        w = read_sequences([[]] * 8)
        with self.assertRaises(WorkloadError):
            validate_and_compile(w, self.cfg)

    def test_segments_require_each_initiator_once(self):
        w = json.load(open(ROOT / "experiments/workloads/M.json"))
        w["program"]["per_master"] = w["program"]["per_master"][:-1]
        with self.assertRaises(WorkloadError):
            validate_and_compile(w, self.cfg)

    def test_round_trip_to_read_sequences_preserves_semantics(self):
        c = validate_and_compile(json.load(open(ROOT / "experiments/workloads/M.json")), self.cfg)
        c2 = validate_and_compile(to_read_sequences(c), self.cfg)
        self.assertEqual([[(o.byte_address, o.release, o.gap) for o in p] for p in c.per_master],
                         [[(o.byte_address, o.release, o.gap) for o in p] for p in c2.per_master])


class VerdictTests(unittest.TestCase):
    def _r(self, ms):
        return {"status": "COMPLETED", "makespan": ms}

    def test_margins(self):
        self.assertTrue(margin_met(2, 50, 52))
        self.assertFalse(margin_met(1, 50, 51))
        self.assertFalse(margin_met(2, 200, 202))   # 0.02*200 = 4 > 2
        self.assertTrue(margin_met(4, 200, 204))

    def test_reversal_and_regret(self):
        v = classify(["A", "B"], {"A": self._r(48), "B": self._r(36)}, {"A": self._r(50), "B": self._r(72)})
        self.assertEqual(v["verdict"], "VALID_COUNTEREXAMPLE")
        self.assertEqual(v["selection"]["extra_cycles"], 22)
        self.assertEqual((v["selection"]["regret"]["numerator"], v["selection"]["regret"]["denominator"]), (11, 25))

    def test_small_margin_keeps_regret_in_details(self):
        v = classify(["A", "B"], {"A": self._r(48), "B": self._r(47)}, {"A": self._r(50), "B": self._r(49)})
        self.assertEqual(v["verdict"], "TIE_OR_SMALL_MARGIN")
        self.assertIn("selection", v)

    def test_tie_policy_first_design(self):
        v = classify(["A", "B"], {"A": self._r(48), "B": self._r(48)}, {"A": self._r(72), "B": self._r(50)})
        self.assertEqual(v["verdict"], "TIE_OR_SMALL_MARGIN")
        self.assertEqual(v["model_choice"], "A")
        self.assertEqual(v["selection"]["extra_cycles"], 22)

    def test_failures_block_comparison(self):
        for st in ("TIMEOUT", "HARNESS_INVALID", "FUNCTIONAL_MISMATCH", "TOOL_ERROR"):
            v = classify(["A", "B"], {"A": self._r(48), "B": self._r(36)}, {"A": self._r(50), "B": {"status": st, "makespan": None}})
            self.assertEqual(v["verdict"], st)
            self.assertNotIn("selection", v)
        v = classify(["A", "B"], {"A": {"status": "MODEL_ERROR", "makespan": None}, "B": self._r(36)}, {"A": self._r(50), "B": self._r(72)})
        self.assertEqual(v["verdict"], "MODEL_ERROR")


if __name__ == "__main__":
    unittest.main()
