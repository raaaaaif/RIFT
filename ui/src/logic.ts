import type { CaseView, ComparisonView, Design } from "./types";

export const DESIGN_SHORT: Record<string, string> = { lic8x8: "LIC · 8 banks", bfly4_8x16: "BFLY4 · 16 banks", bfly2_8x16: "BFLY2 · 16 banks", lic2x2: "LIC 2×2" };

export const pct = (x: number, digits = 1) => `${(x * 100).toFixed(digits)}%`;
export const short = (id: string, n = 10) => (id.length > n + 3 ? `${id.slice(0, n)}…` : id);
export const digestShort = (d: string | null | undefined) => (d ? d.replace("sha256:", "").slice(0, 12) : "—");

export type Tone = "caution" | "teal" | "error" | "neutral";

export interface Wording { tag: string; tone: Tone; headline: string; lead: string; next: { label: string; stage: number; inspect?: string } }

const VERDICT_LABEL: Record<string, string> = {
  VALID_COUNTEREXAMPLE: "Strict reversal",
  VALID_NO_REVERSAL: "Ordering agrees",
  TIE_OR_SMALL_MARGIN: "No decisive ordering",
  HARNESS_INVALID: "Reference invalid",
  FUNCTIONAL_MISMATCH: "Reference functional mismatch",
  TIMEOUT: "Comparison incomplete",
  TOOL_ERROR: "Tool failure",
  MODEL_ERROR: "Model execution invalid",
  INVALID_WORKLOAD: "Workload rejected",
};
export const verdictLabel = (v: string) => VERDICT_LABEL[v] ?? v;

export function designName(c: ComparisonView, d: Design | string | null): string {
  if (!d) return "—";
  const cfg = c.designs?.[d]?.config_id;
  return `Design ${d}${cfg && DESIGN_SHORT[cfg] ? ` (${DESIGN_SHORT[cfg].split(" · ")[0]})` : ""}`;
}

/** Deterministic structured copy keyed only on the evaluator's verdict and recorded values. */
export function wording(cv: CaseView): Wording {
  const c = cv.comparison;
  const v = c.verdict;
  if (c.display_blocked) {
    return { tag: "Display blocked", tone: "error", headline: "This result cannot be displayed as a finding.",
      lead: "The presentation consistency check or the reference epoch disagrees with the recorded evaluator output. The evaluator's record is unchanged; the viewer refuses to substitute its own calculation.",
      next: { label: "Inspect the integrity problem", stage: 4 } };
  }
  if (v === "VALID_COUNTEREXAMPLE" && c.selection && c.rtl_costs) {
    const s = c.selection;
    return { tag: "Strict reversal", tone: "caution",
      headline: `Following the model costs ${s.extra_cycles} extra cycles.`,
      lead: `The fast model selects <b>${designName(c, c.model_choice)}</b>. The reference simulation of the RTL prefers <b>${designName(c, c.rtl_best)}</b>. Choosing ${s.chosen} adds ${s.extra_cycles} completion cycles, ${pct(s.regret.decimal)} above the ${s.denominator_cycles}-cycle reference-best option for this workload.`,
      next: { label: "Inspect the difference", stage: 2 } };
  }
  if (v === "VALID_NO_REVERSAL") {
    return { tag: "Ordering agrees", tone: "teal", headline: `Model and reference both prefer ${designName(c, c.rtl_best)}.`,
      lead: "The fast model and the reference simulation make the same choice, with both orderings beyond the declared margin. Agreement on this workload does not validate the model on others.",
      next: { label: "Examine the workload", stage: 1 } };
  }
  if (v === "TIE_OR_SMALL_MARGIN") {
    const mm = c.model_margin?.met, rm = c.rtl_margin?.met;
    const who = !mm && !rm ? "Neither ordering reaches" : !mm ? `The model's ordering (${c.dM} cycles) does not reach` : `The reference ordering (${c.dR} cycles) does not reach`;
    return { tag: "No decisive ordering", tone: "caution", headline: "No decisive ordering under the declared margin.",
      lead: `${who} the fixed margin of max(2 cycles, 2% of the smaller cost), so this case is not presented as a decisive reversal. The frozen tie policy still yields a numeric choice; its exact regret is kept in the calculation details.`,
      next: { label: "Check the calculation", stage: 0, inspect: "calculation" } };
  }
  if (v === "MODEL_ERROR") {
    return { tag: "Model execution invalid", tone: "error", headline: "Comparison unavailable: the fast-model run failed its checks.",
      lead: "A crashed or malformed model execution is never treated as a performance result.", next: { label: "Inspect failed checks", stage: 4 } };
  }
  if (v === "TIMEOUT") {
    return { tag: "Comparison incomplete", tone: "error", headline: "Performance comparison incomplete.",
      lead: "At least one run reached the declared active-cycle limit. A timeout is not an infinite cost and not a win for the other design.", next: { label: "Inspect failed checks", stage: 4 } };
  }
  return { tag: verdictLabel(v), tone: "error", headline: "Comparison unavailable: reference checks failed.",
    lead: `${(c.blocking_reason ?? "A reference run did not pass its checks").replace(/\.$/, "")}. ${Object.entries(c.rtl_observations ?? {}).filter(([, o]) => o.status !== "COMPLETED").map(([d, o]) => `Design ${d} reference: ${o.status}${o.violations.length ? ` (${o.violations.join(", ")})` : ""}`).join("; ")}. No winner, comparative cost or selection regret is reported for this case.`,
    next: { label: "Inspect failed checks", stage: 4 } };
}

/** Exact margin rule, used only as a display consistency check (the evaluator is authoritative). */
export function marginMet(d: number, a: number, b: number): boolean {
  const m = Math.min(a, b);
  return Math.abs(d) >= 2 && Math.abs(d) * 50 >= m;
}

export function consistency(c: ComparisonView): string[] {
  const out: string[] = [];
  if (!c.model_costs || !c.rtl_costs) return out;
  const [a, b] = c.admitted_order;
  const dM = c.model_costs[a] - c.model_costs[b];
  const dR = c.rtl_costs[a] - c.rtl_costs[b];
  if (dM !== c.dM || dR !== c.dR) out.push("signed differences disagree with the evaluator record");
  const mm = marginMet(dM, c.model_costs[a], c.model_costs[b]);
  const rm = marginMet(dR, c.rtl_costs[a], c.rtl_costs[b]);
  const expected = mm && rm ? (dM * dR < 0 ? "VALID_COUNTEREXAMPLE" : "VALID_NO_REVERSAL") : "TIE_OR_SMALL_MARGIN";
  if (expected !== c.verdict) out.push(`browser margin check gives ${expected}; evaluator recorded ${c.verdict}`);
  return out;
}

// ---------------------------------------------------------------------------
// Butterfly wiring (mirrors rift/model/networks.py Butterfly, which mirrors bfly_net.sv)
// ---------------------------------------------------------------------------
export interface Hop { level: number; router: number; inPort: number; outPort: number }

export function bflyRoute(numIn: number, numOut: number, radix: number, master: number, bank: number): Hop[] {
  const addW = Math.log2(numOut), lr = Math.log2(radix);
  const levels = Math.ceil(addW / lr);
  const routers = numOut / radix, bankFact = numOut / numIn;
  let router = 0, port = 0;
  for (let j = 0; j < radix * routers; j++) {
    if (bankFact < radix) { if (j % bankFact === 0 && j / bankFact === master) { router = Math.floor(j / radix); port = j % radix; } }
    else if (j % radix === 0 && j / radix === master) { router = j / radix; port = 0; }
  }
  const hops: Hop[] = [];
  for (let l = 0; l < levels; l++) {
    const out = (bank >> (addW - (l + 1) * lr)) & (radix - 1);
    hops.push({ level: l, router, inPort: port, outPort: out });
    if (l < levels - 1) {
      const pw = radix ** (levels - l - 2);
      const k = pw * out + (router % pw) + Math.floor(Math.floor(router / pw) / radix) * pw * radix;
      const jj = Math.floor(router / pw) % radix;
      router = k; port = jj;
    }
  }
  return hops;
}

export function plain(c: ComparisonView, d: string | null): string {
  const cfg = d ? c.designs?.[d]?.config_id ?? "" : "";
  return cfg.startsWith("lic") ? "crossbar" : cfg.startsWith("bfly") ? "butterfly" : `design ${d}`;
}

/** Founder-readable headline. The formal verdict wording stays alongside it. */
export function plainHeadline(cv: CaseView): { title: string; sub: string } {
  const c = cv.comparison;
  const R = c.rtl_costs, M = c.model_costs;
  if (c.verdict === "VALID_COUNTEREXAMPLE" && R && c.selection) {
    return { title: `The fast model picks the ${plain(c, c.model_choice)}. The hardware says the ${plain(c, c.rtl_best)} is faster.`,
      sub: `On this workload the ${plain(c, "A")} finishes in ${R.A} cycles and the ${plain(c, "B")} in ${R.B}. Following the model costs ${c.selection.extra_cycles} extra cycles (${pct(c.selection.regret.decimal)}).` };
  }
  if (c.verdict === "VALID_NO_REVERSAL" && R) {
    return { title: `Model and hardware agree: the ${plain(c, c.rtl_best)} is faster here.`,
      sub: `Hardware: ${plain(c, "A")} ${R.A} cycles, ${plain(c, "B")} ${R.B}. The model predicted ${M?.A} and ${M?.B}. Agreement on one workload does not validate the model elsewhere.` };
  }
  if (c.verdict === "TIE_OR_SMALL_MARGIN" && R && M) {
    const mm = c.model_margin?.met, rm = c.rtl_margin?.met;
    const title = !mm && rm ? "The model can't tell these designs apart. The hardware can." : mm && !rm ? "The model picks a winner the hardware doesn't confirm." : "Neither the model nor the hardware separates these designs.";
    return { title, sub: `Model: ${M.A} vs ${M.B} cycles. Hardware: ${R.A} vs ${R.B}. A difference must reach the declared margin to count as a decisive verdict.` };
  }
  return { title: "This comparison is blocked: a hardware reference run failed its checks.",
    sub: "When the reference cannot be trusted, RIFT reports no winner and no cost, by design." };
}

export const epochState = (cv: CaseView) =>
  cv.reference_epoch === cv.current_reference_epoch ? "current" : "historical";
