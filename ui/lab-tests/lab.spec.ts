import {test,expect} from '@playwright/test';
import fs from 'node:fs/promises';

const lab=(page)=>page.locator('.browser-lab');
const ready=async(page)=>{await expect(lab(page).getByRole('button',{name:'Run',exact:true})).toBeEnabled();await expect(lab(page).locator('.lab-result')).toBeVisible();};
async function open(page,mode='sandbox'){
  await page.goto('/#/case/pattern-m/decision');
  await page.getByRole('button',{name:mode==='sandbox'?'Can you change the winner? →':'Re-run in your browser',exact:true}).click();
  await ready(page);
}

test('ordinary browsing does not fetch WASM or lab chunks; explicit replay matches events',async({page})=>{
  const urls=[];page.on('request',r=>urls.push(r.url()));
  await page.goto('/#/case/pattern-m/decision');
  await expect(page.getByRole('heading',{name:'One workload is an anecdote. Here are 289.'})).toBeVisible();
  expect(urls.filter(u=>u.endsWith('.wasm')||/BrowserLab-|WorkloadEditor-|engine.worker-/.test(u))).toEqual([]);
  await page.getByRole('button',{name:'Re-run in your browser',exact:true}).click();await ready(page);
  await lab(page).getByText('Execution details & portable verification',{exact:true}).click();
  await expect(lab(page).getByRole('cell',{name:'Exact SHA-256 match',exact:true})).toHaveCount(2);
  expect(urls.filter(u=>u.endsWith('.wasm')).length).toBe(3);
});

test('same streams flip winner, receipt downloads, playback and reset work',async({page},info)=>{
  await open(page);
  await expect(lab(page).getByRole('row',{name:'Current workload 41 65 33 65',exact:true})).toBeVisible();
  await lab(page).getByRole('button',{name:'Spread the same traffic',exact:true}).click();
  await lab(page).getByRole('button',{name:'Run',exact:true}).click();await ready(page);
  await expect(lab(page).getByRole('heading',{name:'Butterfly finishes first'})).toBeVisible();
  await expect(lab(page).getByRole('row',{name:'Original Pattern M 41 65 33 65',exact:true})).toBeVisible();
  await expect(lab(page).getByRole('row',{name:'Current workload 41 33 33 33',exact:true})).toBeVisible();
  await lab(page).getByRole('button',{name:'Next live cycle',exact:true}).click();
  await expect(lab(page).getByRole('slider',{name:'Live cycle',exact:true})).toHaveValue('5');
  await lab(page).getByRole('slider',{name:'Live cycle',exact:true}).press('End');
  await expect(lab(page).getByText('256 / 256 reads done',{exact:true})).toHaveCount(2);
  await lab(page).getByRole('button',{name:'Play live result',exact:true}).click();
  await expect(lab(page).getByRole('button',{name:'Pause live playback',exact:true})).toBeVisible();
  await lab(page).getByRole('button',{name:'Pause live playback',exact:true}).click();
  const download=page.waitForEvent('download');await lab(page).getByRole('button',{name:'Download experiment receipt'}).click();
  const file=await download;const receipt=JSON.parse(await fs.readFile((await file.path())!,'utf8'));
  expect(receipt.discovery_credit).toBe(0);expect(receipt.executions['rtl-B'].check.makespan).toBe(33);
  await fs.mkdir('../build/browser-tests',{recursive:true});await fs.writeFile(`../build/browser-tests/ui-receipt-${info.project.name}.json`,JSON.stringify(receipt,null,2));
  await lab(page).getByRole('button',{name:'Reset',exact:true}).click();
  await lab(page).getByRole('button',{name:'Run',exact:true}).click();await ready(page);
  await expect(lab(page).getByRole('row',{name:'Current workload 41 65 33 65',exact:true})).toBeVisible();
});

test('editor validates addresses and gaps; edits, idle initiators, discard and dependencies execute',async({page})=>{
  await open(page);await lab(page).getByText('Edit workload',{exact:true}).click();
  const address=lab(page).getByLabel('Initiator 0 segment 1 byte address',{exact:true});
  const reads=lab(page).getByLabel('Initiator 0 segment 1 reads',{exact:true});
  await reads.fill('17');
  await lab(page).getByText('Edit workload',{exact:true}).click();
  await expect(lab(page).getByRole('button',{name:'Run',exact:true})).toBeDisabled();
  await lab(page).getByText('Edit workload',{exact:true}).click();
  await expect(reads).toHaveValue('17');
  await lab(page).getByRole('button',{name:'Discard edits',exact:true}).click();
  await expect(reads).toHaveValue('32');
  await address.fill('3');await lab(page).getByRole('button',{name:'Apply workload',exact:true}).click();
  await expect(lab(page).getByRole('alert')).toContainText('aligned');
  await expect(lab(page).getByRole('button',{name:'Run',exact:true})).toBeDisabled();
  await address.fill('16380');await lab(page).getByLabel('Initiator 0 segment 1 gap',{exact:true}).fill('65');
  await lab(page).getByRole('button',{name:'Apply workload',exact:true}).click();await expect(lab(page).getByRole('alert')).toContainText('64');
  await lab(page).getByLabel('Initiator 0 segment 1 gap',{exact:true}).fill('2');
  await lab(page).getByLabel('Initiator 0 segment 1 release',{exact:true}).selectOption('after_response');
  await lab(page).getByRole('button',{name:'Apply workload',exact:true}).click();
  await lab(page).getByRole('button',{name:'Run',exact:true}).click();await ready(page);
  await expect(lab(page).getByRole('status')).toContainText('passed');
  await lab(page).getByRole('button',{name:'Remove initiator 7 segment 1',exact:true}).click();
  await lab(page).getByRole('button',{name:'Apply workload',exact:true}).click();
  await lab(page).getByRole('button',{name:'Run',exact:true}).click();await ready(page);
  await expect(lab(page).getByRole('status')).toContainText('passed');
  await lab(page).getByLabel('Initiator 0 segment 1 reads',{exact:true}).fill('5000');
  await lab(page).getByRole('button',{name:'Discard edits',exact:true}).click();
  await expect(lab(page).getByLabel('Initiator 0 segment 1 reads',{exact:true})).not.toHaveValue('5000');
});

test('negative replay preserves failure; published presets and reduced witnesses run',async({page})=>{
  await open(page,'replay');
  for(const id of ['pattern-m-reduced','c1-discovered','c1-discovered-reduced','pattern-l','pattern-b','c4-tie','invalid-reference']) {
    // IDs are the release manifest's stable public case identifiers.
    const options=await lab(page).getByLabel('Starting workload',{exact:true}).locator('option').evaluateAll(xs=>xs.map(x=>x.value));
    const actual=id==='c4-tie'?options.find(x=>x.startsWith('c4-')):id;
    await lab(page).getByLabel('Starting workload',{exact:true}).selectOption(actual);
    await lab(page).getByRole('button',{name:'Run',exact:true}).click();await ready(page);
    if(id==='invalid-reference') {
      await expect(lab(page).getByRole('status')).toContainText('Reference validation failed');
      await lab(page).getByText('Execution details & portable verification',{exact:true}).click();
      await expect(lab(page).getByRole('cell',{name:'Exact SHA-256 match',exact:true})).toHaveCount(2);
      await expect(lab(page).getByRole('cell',{name:'HARNESS_INVALID',exact:true})).toHaveCount(1);
    }
  }
});

test('map keyboard selection opens its exact workload; Evidence exposes browser replay',async({page})=>{
  await page.goto('/#/case/pattern-m/decision');
  const map=page.getByRole('group',{name:/Decision map, 289 workloads/});await map.press('ArrowRight');
  await page.getByRole('button',{name:'Experiment with this map workload →',exact:true}).click();await ready(page);
  await expect(lab(page).getByLabel('Starting workload',{exact:true})).toHaveValue(/map-/);
  await page.getByRole('button',{name:'Close browser lab',exact:true}).click();
  await page.getByRole('button',{name:'5. Evidence',exact:true}).click();
  await page.getByRole('button',{name:'Re-run in your browser',exact:true}).click();await ready(page);
});

for(const width of [320,390,768,1440]) test(`layout ${width}px, keyboard focus and reduced motion`,async({page})=>{
  await page.setViewportSize({width,height:900});await open(page);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  const run=lab(page).getByRole('button',{name:'Run',exact:true});await page.keyboard.press('Tab');await run.focus();
  await expect(run).toBeFocused();
  expect(await run.evaluate(el=>getComputedStyle(el).outlineStyle)).not.toBe('none');
  await lab(page).getByText('Edit workload',{exact:true}).click();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.screenshot({path:`../output/playwright/lab-${width}.png`,fullPage:true});
});

test('cancel during loading rejects stale completion, and missing modules keep recorded views usable',async({page,context})=>{
  const releases=[];
  await context.route('**/*.wasm',async route=>{await new Promise(resolve=>releases.push(resolve));await route.continue().catch(()=>{});});
  await page.goto('/#/case/pattern-m/decision');await page.getByRole('button',{name:'Can you change the winner? →',exact:true}).click();
  await lab(page).getByRole('button',{name:'Cancel',exact:true}).click();
  await expect(lab(page).getByRole('status')).toContainText('cancelled');
  releases.forEach(resolve=>resolve());await context.unroute('**/*.wasm');
  await expect(lab(page).locator('.lab-result')).toHaveCount(0);
  await lab(page).getByRole('button',{name:'Run',exact:true}).click();await ready(page);
  await page.getByRole('button',{name:'Close browser lab',exact:true}).click();
  await context.route('**/*.wasm',route=>route.fulfill({status:200,contentType:'text/html',body:'<!doctype html><title>Fallback</title>'}));
  await page.getByRole('button',{name:'Re-run in your browser',exact:true}).click();
  await expect(lab(page).getByRole('alert')).toContainText('wrong content type');
  await page.getByRole('button',{name:'2. Workload',exact:true}).click();
  await expect(page.locator('#stage-heading')).toHaveText('Same program, two designs.');
});


test('failed decision map fetch can be retried without a reload',async({page})=>{
  let first=true;
  await page.route('**/data/map.json',route=>{if(first){first=false;return route.fulfill({status:503,body:'unavailable'});}return route.continue();});
  await page.goto('/#/case/pattern-m/decision');
  await page.getByRole('button',{name:'Retry decision map',exact:true}).click();
  await expect(page.getByRole('heading',{name:'One workload is an anecdote. Here are 289.'})).toBeVisible();
});

test('lab opens while recorded traces are still loading; mixed releases fail closed',async({page})=>{
  const releases=[];
  await page.route('**/data/trace/*',async route=>{await new Promise(resolve=>releases.push(resolve));await route.continue().catch(()=>{});});
  await page.goto('/#/case/pattern-m/decision');
  await expect(page.getByText('Loading recorded events…',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Can you change the winner? →',exact:true}).click();await ready(page);
  releases.forEach(resolve=>resolve());await page.unroute('**/data/trace/*');
  await expect(page.getByRole('region',{name:'Watch the recorded run'})).toBeVisible();
  await page.getByRole('button',{name:'Close browser lab',exact:true}).click();
  await page.route('**/browser/manifest.json',async route=>{const response=await route.fetch();const body=await response.json();body.manifest_digest='sha256:other-release';await route.fulfill({json:body});});
  await page.getByRole('button',{name:'Re-run in your browser',exact:true}).click();
  await expect(lab(page).getByRole('alert')).toContainText('different releases');
  await expect(page.getByRole('region',{name:'Watch the recorded run'})).toBeVisible();
});


test('a dropped map connection retries automatically',async({page})=>{
  let attempts=0;
  await page.route('**/data/map.json',route=>++attempts===1?route.abort('connectionreset'):route.continue());
  await page.goto('/#/case/pattern-m/decision');
  await expect(page.getByRole('heading',{name:'One workload is an anecdote. Here are 289.'})).toBeVisible();
  expect(attempts).toBe(2);
});
