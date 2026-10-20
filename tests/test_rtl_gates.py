"""Executes the real Verilator harness (requires the pinned toolchain and sources)."""

import json
import unittest

from rift.contracts.config import load_config
from rift.contracts.workload import validate_and_compile
from rift.gates import gate0a
from rift.model.registry import get_spec, run_model
from rift.paths import ROOT
from rift.rtl import run_rtl
from rift.store import load_events
from rift.workloads.generators import random_legal


class Gate0ATest(unittest.TestCase):
    def test_gate0a_passes(self):
        report = gate0a("lic2x2")
        failed = [c["check"] for c in report["checks"] if not c["passed"]]
        self.assertEqual(failed, [])
        self.assertGreaterEqual(len(report["checks"]), 21)


class PatternTests(unittest.TestCase):
    """Measured L/B/M costs on both architectures (Gate 0C reference values)."""

    EXPECTED = {("lic8x8", "L"): 33, ("lic8x8", "B"): 65, ("lic8x8", "M"): 41,
                ("bfly4_8x16", "L"): 65, ("bfly4_8x16", "B"): 33, ("bfly4_8x16", "M"): 65}

    def test_patterns(self):
        for (cfg_id, n), ms in self.EXPECTED.items():
            cfg = load_config(cfg_id)
            c = validate_and_compile(json.load(open(ROOT / f"experiments/workloads/{n}.json")), cfg)
            r = run_rtl(cfg, c)
            self.assertEqual(r["check"]["status"], "COMPLETED", (cfg_id, n))
            self.assertEqual(r["check"]["makespan"], ms, (cfg_id, n))


class ModelCrossCheck(unittest.TestCase):
    """Python and C++ event accounting agree exactly where the model claims exactness."""

    def _accepts(self, events):
        return {(e["master"], e["operation_index"]): e["cycle"] for e in events if e["event_kind"] == "accept"}

    def test_exact_models_match_rtl_events(self):
        for cfg_id, mid in (("lic8x8", "lic_exact_v1"), ("bfly4_8x16", "bfly_lfsr_transliteration_v1")):
            cfg = load_config(cfg_id)
            for seed in range(4):
                c = validate_and_compile(random_legal(500 + seed, hot_words=6), cfg)
                r = run_rtl(cfg, c)
                m = run_model(get_spec(mid), cfg, c)
                self.assertEqual(self._accepts(load_events(r["path"] / "events.jsonl")), self._accepts(m.events), (cfg_id, mid, seed))


if __name__ == "__main__":
    unittest.main()
