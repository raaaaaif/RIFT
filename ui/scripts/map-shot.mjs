// Internal visual QA: the decision map section at fixed viewports, both models and both colourings.
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const base = process.env.RIFT_URL ?? "http://127.0.0.1:8770";
const out = process.env.RIFT_SHOTS ?? "/tmp/rift-map";
mkdirSync(out, { recursive: true });
const kase = process.argv[2] ?? "pattern-m";
const widths = (process.argv[3] ?? "1440").split(",").map(Number);
const browser = await chromium.launch({ channel: "chrome", headless: true });
const errors = [];
for (const width of widths) {
  const page = await browser.newPage({ viewport: { width, height: 1000 }, reducedMotion: "reduce", deviceScaleFactor: 2 });
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  await page.goto(`${base}/#/case/${kase}/decision`);
  const map = page.locator("#decision-map");
  await map.waitFor({ timeout: 15000 });
  await map.scrollIntoViewIfNeeded();
  await map.screenshot({ path: `${out}/${kase}-parent-${width}.png` });
  await page.getByRole("button", { name: "Repaired model" }).click();
  await page.waitForTimeout(100);
  await map.screenshot({ path: `${out}/${kase}-repaired-${width}.png` });
  await page.getByRole("button", { name: "How wrong the model is" }).click();
  await page.getByRole("button", { name: "Bank-only model" }).click();
  await page.waitForTimeout(100);
  await map.screenshot({ path: `${out}/${kase}-error-${width}.png` });
  console.log(width, "overflow px:", await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth));
  await page.close();
}
await browser.close();
if (errors.length) { console.log("ERRORS:\n" + errors.join("\n")); process.exitCode = 1; }
