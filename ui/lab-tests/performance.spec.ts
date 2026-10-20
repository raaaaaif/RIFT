import { test, expect } from '@playwright/test';
import fs from 'node:fs/promises';

test('measured cold, warm, throttled execution and repeated-run worker memory', async ({ page, browserName, browser }) => {
  test.skip(browserName !== 'chromium', 'Chromium CDP instrumentation');
  test.setTimeout(120_000);
  const session = await page.context().newCDPSession(page);
  const browserSession = await browser.newBrowserCDPSession();
  const lab = page.locator('.browser-lab');
  await page.goto('/#/case/pattern-m/decision');
  await page.getByRole('button', { name: 'Can you change the winner? →', exact: true }).click();
  await expect(lab.locator('.lab-result')).toBeVisible();
  const measurements = [];
  const sample = async () => {
    await lab.getByText('Execution details & portable verification', { exact: true }).click();
    const text = await lab.locator('.axis-note').allTextContents();
    measurements.push(text.find(x => x.includes('Total Worker time')));
    await lab.getByText('Execution details & portable verification', { exact: true }).click();
  };
  await sample();
  const targets = await browserSession.send('Target.getTargets');
  const target = targets.targetInfos.find(t => t.type === 'worker' && t.url.includes('engine.worker-'))!;
  const { sessionId } = await browserSession.send('Target.attachToTarget', { targetId: target.targetId });
  let requestId = 0;
  const workerCommand = async (method: string): Promise<any> => {
    const id = ++requestId;
    const response = new Promise(resolve => {
      const handler = event => {
        const body = JSON.parse(event.message);
        if (event.sessionId === sessionId && body.id === id) { browserSession.off('Target.receivedMessageFromTarget', handler); resolve(body.result); }
      };
      browserSession.on('Target.receivedMessageFromTarget', handler);
    });
    await browserSession.send('Target.sendMessageToTarget', { sessionId, message: JSON.stringify({ id, method }) });
    return response;
  };
  const memory = [];
  for (let i = 0; i < 30; i++) {
    await lab.getByRole('button', { name: 'Run', exact: true }).click();
    await expect(lab.locator('.lab-result')).toBeVisible();
    if (i < 5) await sample();
    if ([4,14,29].includes(i)) { await workerCommand('HeapProfiler.collectGarbage'); memory.push({run:i+1, ...await workerCommand('Runtime.getHeapUsage')}); }
  }
  expect(memory[2].usedSize - memory[0].usedSize).toBeLessThan(4 * 1024 * 1024);
  await browserSession.detach();
  await page.getByRole('button', { name: 'Close browser lab', exact: true }).click();
  await session.send('Network.enable');
  await session.send('Network.setCacheDisabled', { cacheDisabled: true });
  await session.send('Network.emulateNetworkConditions', { offline:false, latency:150, downloadThroughput:200_000, uploadThroughput:100_000 });
  await session.send('Emulation.setCPUThrottlingRate', { rate:4 });
  // Explicit delivery delay also covers fetches originating in the Worker.
  await page.context().route('**/browser/**', async route => {
    const response = await route.fetch(), body = await response.body();
    await new Promise(resolve => setTimeout(resolve, 150 + body.length / 200_000 * 1000));
    await route.fulfill({ response, body });
  });
  await page.evaluate(() => {
    const button = [...document.querySelectorAll('button')].find(b => b.textContent === 'Can you change the winner? →')!;
    button.addEventListener('click', () => {
      performance.mark('lab-click');
      const observer = new MutationObserver(() => {
        if (document.querySelector('.browser-region')) { performance.mark('lab-feedback'); observer.disconnect(); }
      });
      observer.observe(document.body, { subtree:true, childList:true });
    }, { once:true });
  });
  await page.getByRole('button', { name: 'Can you change the winner? →', exact: true }).click();
  await expect(lab.locator('.lab-result')).toBeVisible({timeout:45_000});
  await sample();
  const feedbackMs = await page.evaluate(() => performance.getEntriesByName('lab-feedback')[0].startTime - performance.getEntriesByName('lab-click')[0].startTime);
  expect(feedbackMs).toBeLessThan(200);
  await fs.mkdir('../build/browser-tests', {recursive:true});
  await fs.writeFile('../build/browser-tests/performance.json', JSON.stringify({url:page.url(), measurements, memory, feedbackMs, throttle:{cpu:4,latency:150,download_bytes_per_second:200_000}},null,2));
});
