"""Receipt boundary and original replay option regression tests."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rift.browser_verify import run_options, verify_receipt
from rift.contracts.canonical import read_json
from rift.paths import ROOT


class BrowserBoundaryTests(unittest.TestCase):
    def test_option_whitelist_and_bounds(self):
        valid = {'timeout':4096,'stalls':[[0,4,12]],'inject':'oracle_offset','sv_inject':8}
        self.assertIn('0:4:12',run_options(valid,8))
        for key,value in [('timeout',4097),('timeout',True),('stalls',[[8,0,1]]),('inject','/tmp/program'),('sv_inject',128)]:
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                run_options(dict(valid,**{key:value}),8)
        with self.assertRaises(ValueError):run_options(dict(valid,executable='/bin/sh'),8)

    def test_receipt_rejects_untrusted_release_and_oversize(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'receipt.json'
            p.write_text(json.dumps({'schema_version':1,'kind':'rift-browser-receipt','discovery_credit':0,'build_id':'other'}))
            with self.assertRaises(ValueError):verify_receipt(p)
            p.write_bytes(b' '*(2*1024*1024+1))
            with self.assertRaises(ValueError):verify_receipt(p)

    def test_local_replay_forwards_every_recorded_option(self):
        from rift.server import Controller
        from rift.presentation import adapter
        # Read the frozen public view; test-owned fake run files isolate all writes.
        view=read_json(ROOT/'ui/public/data/case/invalid-reference.json')
        rec=view['comparison'];calls=[]
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for d,rid in rec['rtl_run_ids'].items():
                p=root/rid;p.mkdir()
                manifest={'stalls':[[0,4,3]],'cpp_inject':'oracle_offset','sv_inject_mask':8,'timeout_cycles':500}
                (p/'manifest.json').write_text(json.dumps(manifest))
                (p/'check.json').write_text(json.dumps({'status':'HARNESS_INVALID','makespan':None,'violation_counts':{'MONITOR_FAILURE':1}}))
            for rid in rec['model_run_ids'].values():
                p=root/rid;p.mkdir();(p/'check.json').write_text(json.dumps({'status':'COMPLETED','makespan':33}))
            def fake(cfg,workload,**options):
                calls.append(options)
                return {'run_id':'test','check':{'status':'HARNESS_INVALID','makespan':None,'violation_counts':{'MONITOR_FAILURE':1}}}
            controller=Controller();job={'used_rtl_executions':0,'budget_rtl_executions':2}
            with patch('rift.server.RUNS',root),patch('rift.rtl.run_rtl',fake),patch.object(controller,'_log'):
                controller._run(job,view)
            self.assertEqual(job['state'],'COMPLETED',job.get('error'))
            self.assertEqual(job['result']['verdict_against_recorded_model'],'HARNESS_INVALID')
            self.assertTrue(job['result']['matches_recorded_reference'])
            self.assertEqual(len(calls),2)
            for opts in calls:
                self.assertEqual(opts['stalls'],((0,4,3),));self.assertEqual(opts['inject'],'oracle_offset');self.assertEqual(opts['sv_inject'],8);self.assertEqual(opts['timeout'],500)

    def test_reduction_displays_surrogate_acceptances(self):
        from rift.presentation import adapter
        # Existing adapter tests redirect the store; the static export is the UI contract.
        for case in ('pattern-m','c1-discovered'):
            view=read_json(ROOT/f'ui/public/data/case/{case}.json')
            self.assertGreater(len(view['reduction']['accepted_edits']),0)

if __name__=='__main__':unittest.main()
