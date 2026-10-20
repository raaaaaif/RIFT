// Internal visual QA: full-page screenshots of real cases at fixed viewports.
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const base = process.env.RIFT_URL ?? "http://127.0.0.1:8770";
const out = process.env.RIFT_SHOTS ?? "/tmp/rift-shots";
mkdirSync(out, { recursive: true });
const targets = (process.argv[2] ?? "pattern-m:decision@1440").split(",");
const browser = await chromium.launch({ channel: "chrome", headless: true });
const errors = [];
for (const t of targets) {
  const [route, w] = t.split("@");
  const [kase, stage] = route.split(":");
  const width = Number(w ?? 1440);
  const page = await browser.newPage({ viewport: { width, height: width < 600 ? 844 : 1000 }, reducedMotion: "reduce" });
  page.on("pageerror", (e) => errors.push(`${t}: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error") errors.push(`${t}: console ${m.text()}`); });
  const url = kase.startsWith("specimen=") ? `${base}/#/specimen/${kase.slice(9)}` : `${base}/#/case/${kase}/${stage ?? "decision"}`;
  await page.goto(url);
  await page.waitForSelector("#stage-heading", { timeout: 15000 });
  await page.waitForTimeout(stage === "difference" ? 1500 : 400);
  const file = `${out}/${kase.replace("=", "-")}-${stage ?? "x"}-${width}.png`;
  await page.screenshot({ path: file, fullPage: true });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  console.log(file, "horizontal overflow px:", overflow);
  await page.close();
}
await browser.close();
if (errors.length) { console.log("ERRORS:\n" + errors.join("\n")); process.exitCode = 1; }
