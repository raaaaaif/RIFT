"""Generate independent browser-test oracles; writes only build/browser-tests/."""
import copy
import gzip
import json
import tempfile
from pathlib import Path

from rift.browser_data import collect
from rift.contracts.canonical import bytes_digest, read_json
from rift.contracts.config import load_config
from rift.contracts.workload import validate_and_compile
from rift.evaluate.checker import check_events
from rift.evaluate.compare import classify
from rift.model.compiled import run_batch
from rift.model.registry import get_spec, run_model
from rift.paths import ROOT, RUNS
from rift.workloads.generators import random_legal


def facts(events):
    return sorted((e['cycle'], e['event_kind'], e.get('master'), e.get('operation_index'), e.get('bank'), e.get('read_data')) for e in events if e['event_kind'] != 'reset')


def main():
    curated, _, defaults = collect()
    workloads = [r['workload'] for r in curated] + [random_legal(72000 + i, 8) for i in range(12)]
    base = {'schema_version': 1, 'capacity_words': 4096, 'word_bytes': 4, 'masters': 8, 'arrival_policy': 'per_operation_release'}
    workloads += [dict(base, label=name, program={'kind': 'read_sequences', 'per_master': [{'master': m, 'ops': ops(m)} for m in range(8)]}) for name, ops in [
        ('single high address, idle initiators', lambda m: [{'byte_address': 16380, 'release': 'after_response', 'gap': 64}] if m == 7 else []),
        ('4096 operations', lambda m: [{'byte_address': m * 4, 'release': 'after_accept', 'gap': 0}] * 1024 if m < 4 else []),
        ('bounded timeout', lambda m: [{'byte_address': 0, 'release': 'after_response', 'gap': 64}] * 80 if m == 0 else []),
    ]]
    models = []
    for i, workload in enumerate(workloads):
        row = {'workload': workload, 'models': {}}
        for role, mid in defaults.items():
            cfg = load_config('lic8x8' if role == 'A' else 'bfly4_8x16')
            c, spec = validate_and_compile(workload, cfg), get_spec(mid)
            with tempfile.TemporaryDirectory() as td:
                out = run_batch(spec, cfg, [c], events=True, workdir=Path(td))[0]
                events = out.pop('events')
                py = run_model(spec, cfg, c, record_events=True)
                assert facts(events) == facts(py.events), (i, mid, 'Python/C++ event mismatch')
                row['models'][role] = {'check': check_events(c, cfg, events, out, 'model', resp_lat=spec.get('resp_lat', 1)), 'events_sha256': bytes_digest((Path(td)/'e0.jsonl').read_bytes())}
        models.append(row)
    r = curated[0]
    path = RUNS / r['rtl']['A']['run_id']
    raw = (path/'events.jsonl').read_bytes() if (path/'events.jsonl').exists() else gzip.decompress((path/'events.jsonl.gz').read_bytes())
    events = [json.loads(line) for line in raw.splitlines()]
    summary = read_json(path/'runner_summary.json')
    c = validate_and_compile(r['workload'], load_config('lic8x8'))
    variants = [('valid', events, summary), ('empty', [], summary)]
    for name, kind, changes in [('data', 'complete', {'read_data': 0}), ('bank', 'accept', {'bank': 99}), ('row', 'accept', {'row': 99}), ('address', 'offer', {'byte_address': 4}), ('identity', 'offer', {'run_id': 'other'}), ('unknown', 'offer', {'operation_index': 999}), ('cycle', 'complete', {'cycle': -1}), ('schema', 'offer', {'schema_version': 9})]:
        mutated = copy.deepcopy(events); next(e for e in mutated if e['event_kind'] == kind).update(changes)
        variants.append((name, mutated, summary))
    duplicate = copy.deepcopy(events); idx = next(i for i,e in enumerate(duplicate) if e['event_kind']=='offer'); duplicate.insert(idx, copy.deepcopy(duplicate[idx]))
    variants += [('duplicate', duplicate, summary), ('incomplete', events[:-8], summary), ('summary mismatch', events, dict(summary, makespan=1234)), ('timeout', events, dict(summary, exit_status='TIMEOUT'))]
    checks = [{'name': name, 'workload': r['workload'], 'events': e, 'summary': s, 'expected': check_events(c, load_config('lic8x8'), e, s, 'rtl')} for name,e,s in variants]
    verdicts = []
    for ma,mb,ra,rb in [(41,33,41,65),(10,10,12,8),(100,102,105,100),(101,103,105,100),(0,2,2,0),(41,33,41,33)]:
        for status in ['COMPLETED','TIMEOUT','HARNESS_INVALID','FUNCTIONAL_MISMATCH','TOOL_ERROR']:
            model = {'A': {'status':'COMPLETED','makespan':ma}, 'B': {'status':'COMPLETED','makespan':mb}}
            rtl = {'A': {'status':'COMPLETED','makespan':ra}, 'B': {'status':status,'makespan':rb if status=='COMPLETED' else None}}
            verdicts.append({'model':model, 'rtl':rtl, 'expected':classify(['A','B'], model, rtl)})
    out=ROOT/'build/browser-tests'; out.mkdir(exist_ok=True)
    (out/'fixtures.json').write_text(json.dumps({'models':models,'checker':checks,'verdicts':verdicts}))
    print(f'{len(models)} workloads × 3 models, {len(checks)} checker streams, {len(verdicts)} verdict boundaries')

if __name__ == '__main__':
    main()
