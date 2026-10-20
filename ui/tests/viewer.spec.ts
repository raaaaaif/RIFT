import { expect, test, type Page } from "@playwright/test";

const CASES = ["pattern-m", "c1-discovered", "pattern-l", "pattern-b", "c4-tie", "invalid-reference"];
const STAGES = ["decision", "workload", "difference", "repair", "evidence"];

async function open(page: Page, kase: string, stage = "decision", base = "") {
  await page.goto(`${base}/#/case/${kase}/${stage}`);
  await expect(page.locator("#stage-heading")).toBeVisible();
}
async function openInspector(page: Page) {
  const b = page.getByRole("button", { name: /Open inspector/ });
  if (await b.count()) await b.click();
  await expect(page.locator("#inspector")).toBeVisible();
}

test.describe("decision: exact values, basis, replay", () => {
  test("UI-01/05: values and verdicts equal the evaluator record for every case", async ({ page, request }) => {
    for (const kase of CASES) {
      const cv = await (await request.get(`/api/cases/${kase}`)).json();
      await open(page, kase);
      await page.getByText("View exact values as a table").click();
      const rows = page.locator(".table-details table tbody tr");
      for (const [i, d] of cv.comparison.admitted_order.entries()) {
        const cells = rows.nth(i).locator("td");
        const model = cv.comparison.model_costs?.[d] ?? cv.comparison.model_predictions?.[d]?.makespan;
        await expect(cells.nth(1)).toHaveText(String(model));
        await expect(cells.nth(2)).toHaveText(cv.comparison.rtl_costs ? String(cv.comparison.rtl_costs[d]) : "Comparison blocked");
      }
      await expect(page.locator(".integrity")).toHaveCount(0);
      if (cv.comparison.verdict === "VALID_COUNTEREXAMPLE") {
        await expect(page.locator(".verdict-card")).toContainText(`+${cv.comparison.selection.extra_cycles}`);
        await expect(page.locator(".verdict-card")).toContainText((cv.comparison.selection.regret.decimal * 100).toFixed(1) + "%");
      }
    }
  });

  test("plain-language headline plus the formal verdict", async ({ page }) => {
    await open(page, "pattern-m");
    await expect(page.locator("h1")).toHaveText("The fast model picks the butterfly. The hardware says the crossbar is faster.");
    await expect(page.locator(".formal-line")).toContainText("Following the model costs 24 extra cycles.");
  });

  test("recorded replay: steps through real cycles, both views, finish markers", async ({ page }) => {
    await open(page, "pattern-m");
    await expect(page.locator(".race-grid svg.flow")).toHaveCount(2);
    await expect(page.locator(".cycle-readout")).toHaveText("cycle 1");
    await page.getByRole("button", { name: "Next cycle" }).click();
    await expect(page.locator(".cycle-readout")).toHaveText("cycle 2");
    await page.locator(".scrub").fill("68");
    await expect(page.locator(".race-meter").nth(1)).toContainText("256 / 256");
    await expect(page.locator(".finish")).toContainText("RTL 65");
    await expect(page.locator(".finish")).toContainText("model 33");
    await page.getByRole("button", { name: "Model prediction" }).click();
    await page.locator(".scrub").fill("6");
    await expect(page.locator(".race-note")).toContainText("Model prediction rendered on the real topology");
    await page.getByRole("button", { name: "Hardware (RTL)" }).click();
    await expect(page.locator(".race-note")).toContainText("measured");
    await page.getByRole("button", { name: "Play recorded replay" }).click();
    await page.waitForTimeout(700);
    await expect(page.getByRole("button", { name: "Pause replay" })).toBeVisible();
  });

  test("UI-02: executed cases and illustrative specimens stay distinct", async ({ page }) => {
    await open(page, "pattern-m");
    await expect(page.locator(".evidence-band")).toContainText("Executed evidence");
    await page.goto("/#/specimen/route_contention");
    await expect(page.locator(".evidence-band")).toContainText("Illustrative data · No RTL executed");
    await expect(page.locator("main")).toContainText("not experimental results");
  });

  test("UI-03: source-predicted 40/32/64 never appear as measured makespan", async ({ page }) => {
    await page.goto("/#/specimen/pattern_m");
    await expect(page.locator("main")).toContainText("prediction only");
    await open(page, "pattern-m", "difference");
    await expect(page.locator(".claim-col").first()).toContainText("source-derived hypothesis");
    await open(page, "pattern-m");
    await page.getByText("View exact values as a table").click();
    await expect(page.locator(".table-details table")).not.toContainText("64");
  });
});

test.describe("adverse and boundary states", () => {
  test("UI-04/20: invalid reference blocks the comparison and never shows zero or a winner", async ({ page }) => {
    await open(page, "invalid-reference");
    await expect(page.locator("h1")).toContainText("This comparison is blocked");
    await expect(page.locator(".formal-line")).toContainText("Comparison unavailable: reference checks failed.");
    await expect(page.locator(".verdict-card")).toContainText("No comparison");
    await expect(page.locator(".verdict-card")).not.toContainText("%");
    await expect(page.getByRole("button", { name: "Try this decision" })).toHaveCount(0);
    await expect(page.locator(".race-invalid")).toBeVisible();
  });

  test("UI-05: a model tie with large regret stays 'no decisive ordering'; exact regret is in details", async ({ page }) => {
    await open(page, "c4-tie");
    await expect(page.locator(".formal-line")).toContainText("No decisive ordering under the declared margin.");
    await expect(page.locator(".verdict-card")).toContainText("No decisive ordering");
    await page.getByRole("button", { name: "See the exact rule" }).click();
    await expect(page.locator(".inspector-body")).toContainText("not a strict reversal");
    await expect(page.locator(".inspector-body")).toContainText("not met");
  });

  test("UI-10: an epoch-mismatched link shows a historical banner", async ({ page }) => {
    await page.goto("/#/case/pattern-m/decision?epoch=epoch-000000000000");
    await expect(page.locator(".evidence-band.historical")).toContainText("differs from this case's epoch");
  });
});

test.describe("mechanism, reduction, repair", () => {
  test("UI-12: internal activity is measured with a validated mapping", async ({ page }) => {
    await open(page, "pattern-m", "difference");
    await expect(page.locator("#heat")).toContainText("measured inside the RTL");
    await expect(page.locator("#heat .callout")).toContainText("contended in");
    await expect(page.locator("#heat")).toContainText("0 mismatches");
    await open(page, "pattern-b", "difference");
    await expect(page.locator("#heat .callout")).toContainText("No stage-1 output was contended");
  });

  test("UI-13: reduction states replay-from-reset and established minimality", async ({ page }) => {
    await open(page, "pattern-m", "workload");
    await expect(page.locator("#red")).toContainText("replayed from reset");
    await expect(page.locator("#red .fact.ok")).toContainText("1-minimal");
  });

  test("UI-08: repair shows independent acceptance on two baskets and rejected controls", async ({ page }) => {
    await open(page, "pattern-m", "repair");
    await expect(page.locator("h1")).toContainText("passed an independent test");
    await expect(page.locator(".gate-pill")).toHaveCount(6);
    await expect(page.locator(".gate-pill.ok")).toHaveCount(6);
    await expect(page.locator(".dotplot")).toHaveCount(2);
    await expect(page.locator(".control-card .badge.error")).toHaveCount(3);
    await expect(page.locator(".model-pair figure")).toHaveCount(2);
    await open(page, "pattern-b", "repair");
    await expect(page.locator("main")).toContainText("Independent evaluation has not run");
  });

  test("walkthrough steps and route sketch change only explanations", async ({ page }) => {
    await open(page, "pattern-m", "difference");
    const before = await page.locator("h1").textContent();
    await page.getByRole("button", { name: "Next step" }).click();
    await expect(page.locator(".stepper-body")).toContainText("What the hardware did");
    await page.getByRole("button", { name: "Separate routes" }).click();
    await expect(page.locator(".route-explorer .explain")).toContainText("different outputs");
    expect(await page.locator("h1").textContent()).toBe(before);
  });
});

test.describe("decision map", () => {
  const pct = (f: [number, number]) => Math.round((100 * f[0]) / Math.max(1, f[1]));

  test("cells and counts equal the API; the repaired toggle changes the count", async ({ page, request }) => {
    const m = await (await request.get("/api/map")).json();
    expect(m.integrity_error_count).toBe(0);
    await open(page, "pattern-m");
    const map = page.locator("#decision-map");
    await expect(map.locator("h2")).toContainText(`Here are ${m.cells.length}.`);
    await expect(map.locator("g.dm-cell")).toHaveCount(m.cells.length);
    await expect(map.locator('g.dm-cell[data-state="wrong"]')).toHaveCount(m.summary.parent.strict_reversals);
    await expect(map.locator('g.dm-cell[data-state="unsure"]')).toHaveCount(m.summary.parent.model_undecided_hardware_decisive);
    await expect(map.locator(".dm-big")).toHaveText(String(m.summary.parent.strict_reversals));
    await map.getByRole("button", { name: "Repaired model" }).click();
    await expect(map.locator(".dm-big")).toHaveText(String(m.summary.repaired.strict_reversals));
    await expect(map.locator('g.dm-cell[data-state="wrong"]')).toHaveCount(m.summary.repaired.strict_reversals);
    await expect(map.locator(".dm-foot")).toContainText(`${m.executor.distinct_rtl_executions} RTL simulations`);
  });

  test("hover and keyboard readouts show the API's exact cell values", async ({ page, request }) => {
    const m = await (await request.get("/api/map")).json();
    const wrong = m.cells.find((c: { verdict: { parent: { verdict: string } } }) => c.verdict.parent.verdict === "VALID_COUNTEREXAMPLE");
    await open(page, "pattern-m");
    const map = page.locator("#decision-map");
    await map.locator(`g.dm-cell[data-i="${wrong.i}"][data-j="${wrong.j}"]`).hover();
    const r = map.locator(".dm-readout");
    await expect(r).toContainText(`Route sharing ${pct(wrong.x)}% · collisions ${pct(wrong.y)}%`);
    await expect(r).toContainText(`crossbar ${wrong.rtl.A} · butterfly ${wrong.rtl.B} cycles`);
    await expect(r).toContainText(`crossbar ${wrong.model.A} · butterfly ${wrong.model.parent} → picks the butterfly: wrong`);
    await map.locator(".dm-svg").focus();
    await page.keyboard.press("ArrowUp");
    const up = m.cells.find((c: { i: number; j: number }) => c.i === wrong.i && c.j === Math.min(wrong.j + 1, m.grid.y.length - 1));
    await expect(r).toContainText(`Route sharing ${pct(up.x)}% · collisions ${pct(up.y)}%`);
    await expect(r).toContainText(`crossbar ${up.rtl.A} · butterfly ${up.rtl.B} cycles`);
  });

  test("landmarks sit on the map, the current case is marked, and a landmark opens its case", async ({ page, request }) => {
    const m = await (await request.get("/api/map")).json();
    await open(page, "pattern-m");
    const map = page.locator("#decision-map");
    await expect(map.locator("g.dm-pin")).toHaveCount(m.landmarks.length);
    await expect(map.locator("g.dm-pin.here")).toHaveCount(1);
    await expect(map.locator(".dm-readout")).toContainText("M · pattern-m");
    const outside = m.landmarks.filter((l: { in_family: boolean }) => l.in_family === false).length;
    await expect(map.locator("g.dm-pin.outside")).toHaveCount(outside);
    await map.getByRole("button", { name: /^L: pattern-l/ }).click();
    await expect(page).toHaveURL(/#\/case\/pattern-l\/decision/);
    await expect(page.locator("#decision-map g.dm-pin.here")).toHaveCount(1);
  });

  test("shown only where the audited model is the map's model; the Repair link opens the repaired view", async ({ page }) => {
    await open(page, "c4-tie");
    await expect(page.locator("#stage-heading")).toBeVisible();
    await expect(page.locator("#decision-map")).toHaveCount(0);
    await open(page, "invalid-reference");
    await expect(page.locator("#decision-map")).toHaveCount(0);
    await open(page, "pattern-m", "repair");
    await page.getByRole("button", { name: /See the fix across/ }).click();
    await expect(page).toHaveURL(/#\/case\/pattern-m\/decision/);
    await expect(page.locator("#decision-map").getByRole("button", { name: "Repaired model" })).toHaveAttribute("aria-pressed", "true");
  });

  test("the prediction recorded before execution is shown next to the measured result", async ({ page, request }) => {
    const m = await (await request.get("/api/map")).json();
    await open(page, "pattern-m");
    const d = page.locator("#decision-map details");
    await d.locator("summary").click();
    await expect(d).toContainText(m.prediction_before_execution.hardware);
    const [above, total] = m.summary.prediction_checks.parent_reversals_where_sharing_exceeds_collisions;
    await expect(d).toContainText(`${above} of ${total} wrong picks lie where route sharing exceeds collisions`);
  });
});

test.describe("selection, filters, exploration state", () => {
  test("UI-11: selection uses logical operation identity across views", async ({ page }) => {
    await open(page, "pattern-m", "workload");
    await page.getByRole("button", { name: "m7: 8 reads of word 8" }).click();
    await expect(page).toHaveURL(/op=m7(%3A|:)op0000/);
    await expect(page.locator("#topo h2")).toContainText("m7:op0000 (word 8)");
    await page.locator(".nav button", { hasText: "Difference" }).click();
    await page.locator("#traces summary").click();
    await expect(page.locator("#traces tr.selected")).toContainText("m7:op0000");
    await openInspector(page);
    await page.getByRole("tab", { name: "Record" }).click();
    await expect(page.locator(".op-detail table tbody tr")).toHaveCount(4);
  });

  test("UI-14/21: filtering the event table never changes whole-run metrics", async ({ page }) => {
    await open(page, "pattern-m", "difference");
    await page.locator("#traces summary").click();
    const bar = page.locator(".toolbar:has(#op-filter)");
    await expect(bar).toContainText("Viewing 256 of 256");
    await page.selectOption("#op-filter", "7");
    await expect(bar).toContainText("Viewing 32 of 256 operations (filtered view; whole-run metrics unchanged)");
    await page.locator(".nav button", { hasText: "Decision" }).click();
    await expect(page.locator(".verdict-card")).toContainText("+24");
  });

  test("accepted timing cells reveal and focus their read despite an earlier table filter", async ({ page }) => {
    await open(page, "pattern-m", "difference");
    await page.locator("#traces summary").click();
    await page.selectOption("#op-filter", "7");
    await page.locator("#traces summary").click();
    const accepted = page.locator('svg[aria-label="RTL B: per-initiator acceptances and waits by cycle"] rect').filter({ hasText: /^m1:op0031 accepted/ });
    await accepted.click();
    await expect(page.locator("#traces")).toHaveAttribute("open", "");
    await expect(page.locator("#op-filter")).toHaveValue("1");
    const read = page.locator("#traces").getByRole("button", { name: "m1:op0031", exact: true });
    await expect(read).toBeFocused();
    await expect(read).toBeInViewport();
    await expect(page.locator("#traces tr.selected")).toContainText("m1:op0031");
    await page.locator("#traces summary").click();
    await accepted.click();
    await expect(read).toBeFocused();
    await expect(read).toBeInViewport();
  });

  test("encounter: optional, masks the reference, reveals, and is not persisted", async ({ page }) => {
    await open(page, "pattern-m");
    await page.getByRole("button", { name: "Try this decision" }).click();
    await expect(page.locator(".cost-chart-desktop")).toContainText("Reference hidden while you decide");
    await page.locator(".encounter").getByRole("button", { name: /Design A/ }).click();
    await expect(page.locator(".encounter")).toContainText("changes nothing in the recorded evidence");
    await page.reload();
    await expect(page.locator(".encounter")).toHaveCount(0);
  });

  test("UI-22: rapid case changes never show stale cross-case evidence", async ({ page }) => {
    await open(page, "pattern-m");
    for (const k of ["pattern-l", "invalid-reference", "pattern-b", "c4-tie"]) await page.selectOption("#case-select", k);
    await expect(page.locator(".run-line .mono")).toHaveText("c4-tie");
    await expect(page.locator(".formal-line")).toContainText("No decisive ordering");
  });
});

test.describe("keyboard, accessibility, layout", () => {
  test("UI-17: keyboard stage navigation, inspector tabs, visible focus, glossary", async ({ page }) => {
    await open(page, "pattern-m");
    await page.locator(".nav button").first().focus();
    await page.keyboard.press("End");
    await expect(page).toHaveURL(/\/evidence/);
    await page.keyboard.press("Home");
    await expect(page).toHaveURL(/\/decision/);
    await openInspector(page);
    await page.getByRole("tab", { name: "Overview" }).focus();
    await page.keyboard.press("ArrowRight");
    await expect(page.getByRole("tab", { name: "Calculation" })).toHaveAttribute("aria-selected", "true");
    expect(await page.evaluate(() => getComputedStyle(document.activeElement as Element).outlineStyle)).not.toBe("none");
    await page.keyboard.press("Escape");
    await expect(page.locator("#inspector")).toHaveCount(0);
    await page.getByRole("button", { name: /^Explain Completion cycles/ }).first().click();
    await expect(page.locator(".inspector-body .definition")).toContainText("first request-release cycle");
  });

  test("UI-23: no horizontal page overflow at 320/390/768/1440 for every case and stage", async ({ browser }) => {
    for (const width of [320, 390, 768, 1440]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      for (const kase of CASES) for (const stage of STAGES) {
        await page.goto(`/#/case/${kase}/${stage}`);
        await expect(page.locator("#stage-heading")).toBeVisible();
        expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth), `${kase}/${stage}@${width}`).toBeLessThanOrEqual(0);
      }
      await page.close();
    }
  });

  test("no page errors while visiting every case and stage", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    for (const kase of CASES) for (const stage of STAGES) { await open(page, kase, stage); await page.waitForTimeout(150); }
    expect(errors).toEqual([]);
  });
});

test.describe("exports, sealed data, run controls, static deployment", () => {
  test("UI-18: case export carries provenance, scope, epoch and limitations", async ({ page }) => {
    await open(page, "pattern-m", "evidence");
    const [dl] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: /Export this case/ }).click()]);
    const body = JSON.parse(Buffer.concat(await (await dl.createReadStream())!.toArray()).toString());
    expect(body.evidence_basis).toBe("EXECUTED_ARTIFACT");
    expect(body.provenance).toBe("SUPPLIED_CALIBRATION");
    expect(body.scope).toBe("STRESS_WITNESS");
    expect(body.limitations.length).toBeGreaterThan(1);
  });

  test("UI-09: the sealed held-out basket is never served", async ({ request }) => {
    const cv = await (await request.get("/api/cases/pattern-m")).json();
    expect(JSON.stringify(cv)).not.toContain("heldout_v1.json");
    for (const u of ["/api/artifacts/../../experiments/heldout/heldout_v1.json", `/api/artifacts/${cv.comparison.comparison_run_id}/..%2F..%2F..%2Fexperiments%2Fheldout%2Fheldout_v1.json`, "/experiments/heldout/heldout_v1.json"]) {
      expect(await (await request.get(u)).text()).not.toContain("acceptance_contract");
    }
  });

  test("UI-19: run controls are disabled without --allow-run", async ({ page, request }) => {
    expect((await request.post("/api/replay", { data: { case_id: "pattern-m", budget_rtl_executions: 2 } })).status()).toBe(403);
    await open(page, "pattern-m", "evidence");
    await expect(page.getByRole("button", { name: /Replay the reference locally/ })).toBeDisabled();
  });

  test("live replay through the controller executes real RTL within the declared budget", async ({ request }) => {
    const base = "http://127.0.0.1:8772";
    expect((await request.post(`${base}/api/replay`, { data: { case_id: "pattern-b", budget_rtl_executions: 9 } })).status()).toBe(400);
    const job = await (await request.post(`${base}/api/replay`, { data: { case_id: "pattern-b", budget_rtl_executions: 2 } })).json();
    let j = job;
    for (let i = 0; i < 60 && !["COMPLETED", "FAILED"].includes(j.state); i++) {
      await new Promise((r) => setTimeout(r, 500));
      j = (await (await request.get(`${base}/api/jobs`)).json()).jobs.find((x: { job_id: string }) => x.job_id === job.job_id);
    }
    expect(j.state).toBe("COMPLETED");
    expect(j.used_rtl_executions).toBe(2);
    expect(j.result.matches_recorded_reference).toBe(true);
  });

  test("static deployment (no backend): every case and stage renders from /data", async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    const base = "http://127.0.0.1:8773";
    for (const kase of CASES) for (const stage of STAGES) await open(page, kase, stage, base);
    await open(page, "pattern-m", "decision", base);
    await expect(page.locator(".race-grid svg.flow")).toHaveCount(2);
    const m = await (await page.request.get(`${base}/data/map.json`)).json();
    await expect(page.locator("#decision-map g.dm-cell")).toHaveCount(m.cells.length);
    await expect(page.locator("#decision-map .dm-big")).toHaveText(String(m.summary.parent.strict_reversals));
    await open(page, "pattern-m", "difference", base);
    await expect(page.locator("#heat")).toContainText("measured inside the RTL");
    await open(page, "pattern-m", "evidence", base);
    await expect(page.getByRole("button", { name: /Replay the reference locally/ })).toBeDisabled();
    expect(errors).toEqual([]);
  });
});
