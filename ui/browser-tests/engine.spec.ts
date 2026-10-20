import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';

const fields = ['status','functional_valid','workload_digest','expected_operations','makespan','makespan_from_events_unvalidated','accepted','completed','offered','monitor_failures','violation_counts'];
test('all published, reduced and 289 map workloads reproduce both RTL streams and model checks', async ({page}, info) => {
  await page.goto('/');
  const out = await page.evaluate(async (fields) => {
    const { loadManifest, loadRecords } = await import('/src/browser/assets.ts');
    const { BrowserRunner } = await import('/src/browser/client.ts');
    const m = await loadManifest(), runner = new BrowserRunner();
    const records = [...await loadRecords(m, 'curated'), ...await loadRecords(m, 'map')];
    const results = [], failures = [];
    for (const r of records) {
      const result = await runner.run(m, r.workload, () => {}, r);
      for (const d of ['A','B']) {
        const run = result.executions[`rtl-${d}`];
        if (!run.hash_match || !run.check_match) failures.push(`${r.id}:rtl-${d}`);
      }
      for (const [role, expected] of Object.entries(r.expected_models)) {
        const run = result.executions[`model-${role === 'B' ? 'parent' : role}`];
        for (const f of fields) if (JSON.stringify(run.check[f]) !== JSON.stringify(expected[f])) failures.push(`${r.id}:model-${role}:${f}`);
      }
      results.push({id:r.id, elapsed_ms:result.elapsed_ms, loading_ms:result.loading_ms, simulation_ms:result.simulation_ms, checking_ms:result.checking_ms});
    }
    runner.cancel(); return {count:records.length, failures, results};
  }, fields);
  await fs.mkdir('../build/browser-tests', {recursive:true});
  await fs.writeFile(`../build/browser-tests/parity-${info.project.name}.json`,JSON.stringify(out,null,2));
  expect(out.count).toBe(297); expect(out.failures).toEqual([]);
});

test('native C++ / Python model oracles, checker corruptions, exact verdict boundaries and workload limits', async ({page}, info) => {
  const fixtures = JSON.parse(await fs.readFile('../build/browser-tests/fixtures.json','utf8'));
  await page.goto('/');
  const failures = await page.evaluate(async ({fixtures,fields}) => {
    const { loadManifest } = await import('/src/browser/assets.ts');
    const { BrowserRunner } = await import('/src/browser/client.ts');
    const { compile, workloadDigest, classify } = await import('/src/browser/contracts.ts');
    const { checkEvents } = await import('/src/browser/checker.ts');
    const m = await loadManifest(), runner = new BrowserRunner(), failures = [];
    for (const [i,row] of fixtures.models.entries()) {
      const result = await runner.run(m,row.workload,()=>{});
      for (const [role,expected] of Object.entries(row.models)) {
        const actual=result.executions[`model-${role}`];
        if(actual.events_sha256!==expected.events_sha256) failures.push(`model hash:${i}:${role}`);
        for(const f of fields) if(JSON.stringify(actual.check[f])!==JSON.stringify(expected.check[f])) failures.push(`model check:${i}:${role}:${f}`);
      }
    }
    runner.cancel();
    for(const row of fixtures.checker) {
      const actual=checkEvents(compile(row.workload),await workloadDigest(row.workload),8,row.events,row.summary,'rtl');
      for(const f of fields) if(JSON.stringify(actual[f])!==JSON.stringify(row.expected[f])) failures.push(`checker:${row.name}:${f}:${JSON.stringify(actual[f])}:${JSON.stringify(row.expected[f])}`);
    }
    for(const row of fixtures.verdicts) {
      const actual=classify(row.model,row.rtl);
      if(actual.verdict!==row.expected.verdict || (row.expected.model_choice && actual.model_choice!==row.expected.model_choice)) failures.push(`verdict:${JSON.stringify(row)}`);
    }
    const base={schema_version:1,capacity_words:4096,word_bytes:4,masters:8,arrival_policy:'saturated_after_accept',program:{kind:'repeat_read',byte_addresses:[0,4,8,12,16,20,24,28],reads_per_master:32}};
    for(const mutate of [w=>w.masters=9,w=>w.program.byte_addresses[0]=3,w=>w.program.byte_addresses[0]=16384,w=>w.program.reads_per_master=1025,w=>w.program.reads_per_master=513,w=>w.capacity_words=2048,w=>w.untrusted='extra']) {
      const w=structuredClone(base);mutate(w);let rejected=false;try{compile(w);}catch{rejected=true;} if(!rejected) failures.push(`accepted malformed workload:${JSON.stringify(w)}`);
    }
    return failures;
  }, {fixtures,fields});
  await fs.writeFile(`../build/browser-tests/contracts-${info.project.name}.json`,JSON.stringify({failures},null,2));
  expect(failures).toEqual([]);
});

test('guided stream preservation, cancellation, rapid reruns, corruption and release mismatch', async ({page}, info) => {
  await page.goto('/');
  const out=await page.evaluate(async()=>{
    const {loadManifest,loadRecords,verifiedBytes}=await import('/src/browser/assets.ts');
    const {BrowserRunner}=await import('/src/browser/client.ts');
    const {compile,spreadTraffic}=await import('/src/browser/contracts.ts');
    const m=await loadManifest(), r=(await loadRecords(m,'curated')).find(r=>r.id==='pattern-m'), runner=new BrowserRunner();
    const original=compile(r.workload), w=spreadTraffic(r.workload), moved=compile(w);
    const preserved=[0,4,1,5,2,6,3,7].every((src,dst)=>JSON.stringify(original[src].map(({master,...op})=>op))===JSON.stringify(moved[dst].map(({master,...op})=>op)));
    const canceled=runner.run(m,w,()=>{}).then(()=>false,e=>e.name==='AbortError');runner.cancel();
    const superseded=runner.run(m,r.workload,()=>{}).then(()=>false,e=>e.name==='AbortError');
    const result=await runner.run(m,w,()=>{});
    let epoch=false,digest=false,missing=false;
    try{await loadManifest('epoch-other');}catch{epoch=true;}
    try{await verifiedBytes({...m.curated,sha256:'sha256:bad'});}catch{digest=true;}
    try{await verifiedBytes({url:'/browser/missing.wasm',sha256:'sha256:bad'},true);}catch{missing=true;}
    runner.cancel();return {preserved,canceled:await canceled,superseded:await superseded,epoch,digest,missing,receipt:result.receipt,costs:['rtl-A','rtl-B','model-parent','model-repaired'].map(k=>result.executions[k].check.makespan)};
  });
  expect(out.costs).toEqual([41,33,33,33]);
  for(const key of ['preserved','canceled','superseded','epoch','digest','missing']) expect(out[key],key).toBe(true);
  await fs.writeFile(path.resolve(`../build/browser-tests/receipt-${info.project.name}.json`),JSON.stringify(out.receipt,null,2));
});
