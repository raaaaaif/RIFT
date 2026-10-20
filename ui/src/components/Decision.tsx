import { useState } from "react";
import type { CaseView, Costs, Design } from "../types";
import { DESIGN_SHORT, consistency, designName, pct, plainHeadline, wording } from "../logic";
import { ScopeBar, Term, useUi } from "./common";
import { Race } from "./Race";
import { DecisionMap } from "./DecisionMap";
import { BrowserEntry, type BrowserIntent } from "./BrowserEntry";

function niceMax(v: number): number {
  const steps = [40, 60, 80, 100, 120, 160, 200, 240, 320, 400, 600, 800, 1000, 1200, 1600];
  for (const s of steps) if (v * 1.12 <= s) return s;
  return Math.ceil((v * 1.12) / 400) * 400;
}

export function CostChart({ order, labels, model, reference, masked, refUnavailable, caption }: {
  order: Design[]; labels: Record<string, string>; model: Costs | null; reference: Costs | null; masked?: boolean; refUnavailable?: string; caption: string;
}) {
  const all = [...Object.values(model ?? {}), ...Object.values(reference ?? {})];
  const max = niceMax(Math.max(10, ...all));
  const x0 = 132, w = 432, sc = w / max;
  const ticks = [0, max / 4, max / 2, (3 * max) / 4, max];
  const desc = order.map((d) => `Design ${d}: model ${model ? model[d] + " cycles" : "unavailable"}; reference ${masked ? "hidden while you decide" : reference ? reference[d] + " cycles" : "unavailable"}`).join(". ");
  return (
    <>
      <div className="chart-wrap cost-chart-desktop">
        <svg className="chart" viewBox="0 0 620 232" role="img" aria-labelledby="cost-title cost-desc">
          <title id="cost-title">{caption}</title>
          <desc id="cost-desc">{desc}. The same values are listed in the exact-value table.</desc>
          <defs>
            <pattern id="mask-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="6" height="6" fill="#ECEFEA" /><line x1="0" y1="0" x2="0" y2="6" stroke="#9ABBBF" strokeWidth="2" />
            </pattern>
          </defs>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={x0 + t * sc} y1={29} x2={x0 + t * sc} y2={185} stroke="#E0E6E4" />
              <text x={x0 + t * sc} y={208} textAnchor="middle" fontSize={10}>{t}</text>
            </g>
          ))}
          {order.map((d, i) => {
            const y = 59 + i * 95, m = model?.[d], r = reference?.[d];
            return (
              <g key={d}>
                <text x={10} y={y + 6} fontSize={13} fontWeight={650}>Design {d}</text>
                <text x={10} y={y + 24} fontSize={10}>{labels[d]}</text>
                {m !== undefined ? (
                  <>
                    <rect x={x0} y={y - 12} width={m * sc} height={15} fill="#ECEFEA" stroke="#18343F" strokeWidth={1.25} strokeDasharray="4 3" />
                    <text x={x0 + m * sc + 7} y={y} fontSize={11} fontWeight={600}>{m}</text>
                  </>
                ) : <text x={x0} y={y} fontSize={10} fill="#A03432">Model prediction unavailable</text>}
                {masked ? (
                  <>
                    <rect x={x0} y={y + 11} width={w} height={15} className="mask-bar" />
                    <text x={x0 + 8} y={y + 23} fontSize={10}>Reference hidden while you decide</text>
                  </>
                ) : r !== undefined && r !== null ? (
                  <>
                    <rect x={x0} y={y + 11} width={r * sc} height={15} fill="#006D77" />
                    <text x={x0 + r * sc + 7} y={y + 23} fontSize={11} fontWeight={650}>{r}</text>
                  </>
                ) : <text x={x0} y={y + 24} fontSize={10} fill="#A03432">{refUnavailable ?? "Reference unavailable"}</text>}
              </g>
            );
          })}
          <text x={342} y={228} textAnchor="middle" fontSize={10}>Completion cycles (makespan) · lower is better</text>
        </svg>
      </div>
      <div className="cost-chart-mobile" aria-label={`${caption}. ${desc}`}>
        {order.map((d) => (
          <div className="cost-group" key={d}>
            <div className="cost-group-head"><strong>Design {d}</strong><span>{labels[d]}</span></div>
            <div className="cost-bar-row"><span>Model</span>
              {model ? <svg viewBox="0 0 100 12" preserveAspectRatio="none" aria-hidden="true"><rect x="0" y="1" width={(model[d] / max) * 100} height="10" fill="#ECEFEA" stroke="#18343F" strokeWidth=".65" strokeDasharray="2 1.5" /></svg> : <span>Unavailable</span>}
              <strong>{model ? model[d] : "—"}</strong></div>
            <div className="cost-bar-row"><span>Reference</span>
              {masked ? <span>Hidden</span> : reference ? <svg viewBox="0 0 100 12" preserveAspectRatio="none" aria-hidden="true"><rect x="0" y="1" width={(reference[d] / max) * 100} height="10" fill="#006D77" /></svg> : <span>Unavailable</span>}
              <strong>{masked ? "?" : reference ? reference[d] : "—"}</strong></div>
          </div>
        ))}
        <div className="mobile-axis"><span></span><div>{ticks.map((t) => <span key={t}>{t}</span>)}</div><span></span></div>
        <div className="mobile-axis-caption">Completion cycles (makespan) · lower is better</div>
      </div>
    </>
  );
}

export function ExactTable({ order, labels, model, reference, caption, refUnavailable }: {
  order: Design[]; labels: Record<string, string>; model: Costs | null; reference: Costs | null; caption: string; refUnavailable?: string;
}) {
  return (
    <details className="table-details">
      <summary>View exact values as a table</summary>
      <div className="table-wrap">
        <table>
          <caption className="screenreader">{caption}</caption>
          <thead><tr><th>Design</th><th className="numeric">Fast model (prediction)</th><th className="numeric">RTL reference (observation)</th></tr></thead>
          <tbody>
            {order.map((d) => (
              <tr key={d}><td>{d} · {labels[d]}</td><td className="numeric">{model ? model[d] : "Unavailable"}</td><td className="numeric">{reference ? reference[d] : refUnavailable ?? "Unavailable"}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function Encounter({ cv, state, setState }: { cv: CaseView; state: EncounterState; setState: (s: EncounterState) => void }) {
  const c = cv.comparison;
  if (!c.rtl_costs || !c.model_costs) return null;
  if (state.mode === "off") return null;
  const best = c.rtl_best!;
  return (
    <div className="encounter" role="region" aria-label="Try this decision (optional, unscored)">
      <h3>Try this decision <span className="muted" style={{ fontWeight: 500 }}>· optional · not scored · nothing is recorded</span></h3>
      {state.mode === "choosing" ? (
        <>
          <p style={{ margin: 0 }}>The fast model predicts {c.admitted_order.map((d) => `${d} = ${c.model_costs![d]}`).join(", ")} cycles and selects <b>{c.model_choice}</b>. Before seeing the reference simulation, which design do you expect to finish sooner?</p>
          <div className="choice-row">
            {c.admitted_order.map((d) => <button key={d} className="btn compact" onClick={() => setState({ mode: "revealed", pick: d })}>{designName(c, d)}</button>)}
            <button className="btn compact" onClick={() => setState({ mode: "revealed", pick: null })}>Just show the reference</button>
            <button className="text-button" onClick={() => setState({ mode: "off", pick: null })}>Leave</button>
          </div>
        </>
      ) : (
        <>
          <p style={{ margin: 0 }} role="status">
            The reference simulation {c.verdict === "TIE_OR_SMALL_MARGIN" && !c.rtl_margin?.met ? "does not separate the designs by the declared margin" : <>prefers <b>{designName(c, best)}</b></>}
            {state.pick ? <> · you picked {state.pick}</> : null}; the model chose {c.model_choice}.
            {" "}This exploration changes nothing in the recorded evidence.
          </p>
          <div className="choice-row">
            <button className="btn compact" onClick={() => setState({ mode: "choosing", pick: null })}>Try again</button>
            <button className="text-button" onClick={() => setState({ mode: "off", pick: null })}>Close</button>
          </div>
        </>
      )}
    </div>
  );
}

export interface EncounterState { mode: "off" | "choosing" | "revealed"; pick: Design | null }

const STEPS = [
  { n: "1", t: "Same work, two designs", d: "Identical read programs run on both interconnects.", stage: 1 },
  { n: "2", t: "Fast model predicts", d: "A cheap model estimates cycles and picks a winner.", stage: 0 },
  { n: "3", t: "Hardware measures", d: "The pinned RTL is simulated cycle by cycle.", stage: 2 },
  { n: "4", t: "Repair, then verify", d: "A model fix must pass a sealed, independent test.", stage: 3 },
];

export function DecisionView({ cv }: { cv: CaseView }) {
  const { gotoStage, inspect } = useUi();
  const [enc, setEnc] = useState<EncounterState>({ mode: "off", pick: null });
  const [browserRequest, setBrowserRequest] = useState<BrowserIntent | null>(null);
  const c = cv.comparison;
  const wd = wording(cv);
  const ph = plainHeadline(cv);
  const labels: Record<string, string> = Object.fromEntries(c.admitted_order.map((d) => [d, DESIGN_SHORT[c.designs?.[d]?.config_id] ?? c.designs?.[d]?.config_id ?? d]));
  const browserCheck = consistency(c);
  const masked = enc.mode === "choosing";
  const comparative = !!c.rtl_costs && !c.display_blocked;
  const modelVals = c.model_costs ?? (c.model_predictions && Object.values(c.model_predictions).every((p) => p.makespan !== null)
    ? Object.fromEntries(Object.entries(c.model_predictions).map(([d, p]) => [d, p.makespan as number])) : null);
  return (
    <>
      <div className="stage-meta">
        <span className="eyebrow">01 / Decision</span>
        <span className={`tag ${wd.tone === "neutral" ? "" : wd.tone}`}>{wd.tag} · executed</span>
      </div>
      <h1 id="stage-heading" tabIndex={-1} className="hero-title">{ph.title}</h1>
      <p className="hero-sub">{ph.sub}</p>
      <p className="formal-line"><span>Decision verdict</span> {wd.headline} <button className="text-button" onClick={() => inspect("calculation")}>See the exact rule</button></p>
      {browserCheck.length ? <div className="integrity" role="alert"><strong>Presentation integrity error.</strong> {browserCheck.join("; ")}. The comparative claim is blocked.</div> : null}
      {c.integrity_errors?.length ? <div className="integrity" role="alert"><strong>Artifact integrity error.</strong> {c.integrity_errors.join("; ")}</div> : null}
      <BrowserEntry key={cv.case_id} cv={cv} request={browserRequest} />
      <Race cv={cv} />
      <div className="result-row">
        <section className="panel result-panel" aria-labelledby="cmp-title">
          <div className="panel-head"><div><h2 id="cmp-title">Prediction vs measurement</h2><p>Completion cycles, lower is better.</p></div>
            {comparative ? <button className="btn compact" onClick={() => setEnc({ mode: "choosing", pick: null })} disabled={enc.mode !== "off"}>Try this decision</button> : null}</div>
          <div className="legend">
            <span className="legend-item"><span className="legend-line" />Fast model · dashed</span>
            <span className="legend-item"><span className="legend-line solid" />RTL reference · solid</span>
          </div>
          <CostChart order={c.admitted_order} labels={labels} model={modelVals} reference={c.rtl_costs} masked={masked}
            refUnavailable={c.rtl_costs ? undefined : "Comparison blocked"} caption="Fast-model predictions and RTL reference completion cycles" />
          <Encounter cv={cv} state={enc} setState={setEnc} />
          <ExactTable order={c.admitted_order} labels={labels} model={modelVals} reference={c.rtl_costs} caption="Completion cycles by design and role" refUnavailable="Comparison blocked" />
        </section>
        <aside className={`verdict-card ${wd.tone}`} aria-label="Consequence">
          {c.verdict === "VALID_COUNTEREXAMPLE" && c.selection ? (<>
            <span className="vc-k">Cost of following the model</span>
            <span className="vc-big">+{c.selection.extra_cycles}<small>cycles</small></span>
            <span className="vc-pct">{pct(c.selection.regret.decimal)} <Term k="regret">selection regret</Term></span>
            <p>({c.rtl_costs![c.selection.chosen]} − {c.rtl_costs![c.selection.reference_best]}) ÷ {c.selection.denominator_cycles}. Both differences clear the <Term k="margin">margin</Term>.</p>
          </>) : c.verdict === "VALID_NO_REVERSAL" ? (<>
            <span className="vc-k">Cost of following the model</span><span className="vc-big">0<small>cycles</small></span><p>Same choice as the hardware for this workload.</p>
          </>) : c.verdict === "TIE_OR_SMALL_MARGIN" ? (<>
            <span className="vc-k">Verdict</span><span className="vc-big small">No decisive ordering</span>
            <p>Model gap {c.dM} cycles, hardware gap {c.dR}. The <Term k="tie">tie policy</Term> still picks {c.model_choice}; its regret is in the calculation.</p>
          </>) : (<>
            <span className="vc-k">Verdict</span><span className="vc-big small">No comparison</span><p>{c.blocking_reason}</p>
          </>)}
          <button className="btn primary" onClick={() => (wd.next.inspect ? inspect(wd.next.inspect as "calculation") : gotoStage(wd.next.stage))}>{wd.next.label} →</button>
        </aside>
      </div>
      <DecisionMap cv={cv} onExplore={preset => setBrowserRequest({ mode: "sandbox", preset, case_id: cv.case_id })} />
      <ScopeBar cv={cv} />
      <section className="how" aria-label="How RIFT works">
        {STEPS.map((s) => (
          <button key={s.n} className="how-step" onClick={() => gotoStage(s.stage)}>
            <span className="how-n">{s.n}</span><strong>{s.t}</strong><span>{s.d}</span>
          </button>
        ))}
      </section>
    </>
  );
}
