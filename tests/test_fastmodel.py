"""Compiled C++ fast models agree with the Python models event for event."""

import json
import shutil
import unittest

from rift.contracts.config import load_config
from rift.contracts.workload import validate_and_compile
from rift.model.registry import get_spec, run_model
from rift.paths import ROOT
from rift.workloads.generators import random_legal

CASES = [
    ("lic8x8", {"family": "crossbar", "params": {"fair": True, "lock_in": True}, "applies_to": ["LIC"]}),
    ("lic8x8", {"family": "crossbar", "params": {"fair": False, "lock_in": True}, "applies_to": ["LIC"]}),
    ("bfly4_8x16", {"family": "crossbar", "params": {"fair": True, "lock_in": True}, "applies_to": ["BFLY4"]}),
    ("bfly4_8x16", {"family": "shared_link", "params": {"links": [[2, 2]]}, "applies_to": ["BFLY4"]}),
    ("bfly4_8x16", {"family": "shared_link", "params": {"links": [[2, 1], [4, 0]]}, "applies_to": ["BFLY4"]}),
    ("bfly4_8x16", {"family": "butterfly", "params": {"prio_mode": "rr"}, "applies_to": ["BFLY4"]}),
    ("bfly4_8x16", {"family": "butterfly", "params": {"prio_mode": "rr", "bank_modulus": 8}, "applies_to": ["BFLY4"]}),
    ("bfly4_8x16", {"family": "butterfly", "params": {"prio_mode": "rr"}, "resp_lat": 2, "applies_to": ["BFLY4"]}),
]


def _strip(events):
    """Events as facts; emission order within one cycle carries no meaning."""
    return sorted((e["cycle"], e["event_kind"], e.get("master"), e.get("operation_index"), e.get("bank"), e.get("read_data"))
                  for e in events if e["event_kind"] != "reset")


@unittest.skipUnless(shutil.which("c++"), "no C++ compiler")
class CompiledModelCrossCheck(unittest.TestCase):
    def test_compiled_matches_python_on_patterns_and_random_workloads(self):
        from rift.model import compiled
        workloads = [json.load(open(ROOT / f"experiments/workloads/{n}.json")) for n in ("L", "B", "M")]
        workloads += [random_legal(9000 + i, 8) for i in range(12)]
        for config_id, spec in CASES:
            cfg = load_config(config_id)
            spec = dict(spec, model_id="crosscheck")
            self.assertTrue(compiled.supports(spec))
            comp = [validate_and_compile(w, cfg) for w in workloads]
            fast = compiled.run_batch(spec, cfg, comp, events=True)
            for w, c, f in zip(workloads, comp, fast):
                py = run_model(spec, cfg, c, record_events=True)
                label = f"{config_id} {spec['family']} {spec['params']} {w.get('label', '')}"
                self.assertEqual(f["exit_status"], py.status, label)
                self.assertEqual(f["makespan"], py.makespan, label)
                self.assertEqual(_strip(f["events"]), _strip(py.events), label)

    def test_lfsr_priority_models_are_not_compiled(self):
        from rift.model import compiled
        self.assertFalse(compiled.supports(get_spec("bfly_lfsr_transliteration_v1")))


if __name__ == "__main__":
    unittest.main()
