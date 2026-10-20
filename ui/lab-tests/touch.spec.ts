import { test, expect } from '@playwright/test';

test('touch controls run the guided experiment at phone width', async ({ browser, baseURL }) => {
  const context = await browser.newContext({ baseURL, viewport: { width:390, height:844 }, hasTouch:true, reducedMotion:'reduce' });
  const page = await context.newPage();
  await page.goto('/#/case/pattern-m/decision');
  await page.getByRole('button', {name:'Can you change the winner? →',exact:true}).tap();
  const lab = page.locator('.browser-lab');
  await expect(lab.locator('.lab-result')).toBeVisible();
  await lab.getByRole('button', {name:'Spread the same traffic',exact:true}).tap();
  await lab.getByRole('button', {name:'Run',exact:true}).tap();
  await expect(lab.getByRole('row', {name:'Current workload 41 33 33 33',exact:true})).toBeVisible();
  await lab.getByText('Edit workload',{exact:true}).tap();
  await expect(lab.getByLabel('Initiator 0 segment 1 byte address',{exact:true})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await context.close();
});
