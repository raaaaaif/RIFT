import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { CaseView, DiagnosticView, TraceSelection } from "../types";
import { plain, wording } from "../logic";
import { buildTimeline, type Timeline } from "../replay";
import { Term, useUi } from "./common";
import { ContentionGrid, RouterHeatmap } from "./Charts";

type Runner = { key: string; label: string; role: string; runId: string };

function RouteExplorer() {
  const [mode, setMode] = useState<"shared" | "separate">("shared");
  const shared = mode === "shared";
  return (
    <section className="panel" aria-labelledby="explore-h" id="explore">
      <div className="panel-head"><div><h2 id="explore-h">Explore the bottleneck</h2><p>A qualitative sketch: switching it changes the drawing only, never a result.</p></div>
        <div className="seg" role="group" aria-label="Route sketch"><button aria-pressed={shared} onClick={() => setMode("shared")}>Shared route</button><button aria-pressed={!shared} onClick={() => setMode("separate")}>Separate routes</button></div></div>
      <div className="panel-body route-explorer">
        <svg viewBox="0 0 420 190" style={{ maxWidth: 440, width: "100%" }} role="img" aria-label={shared ? "Two initiators reach different banks through one shared router output." : "Two initiators reach different banks through separate router outputs."}>
          <rect x="8" y="30" width="78" height="34" rx="6" fill="#18343F" /><text x="47" y="51" textAnchor="middle" fontSize="12" style={{ fill: "white" }}>m0</text>
          <rect x="8" y="126" width="78" height="34" rx="6" fill="#FFF4DA" stroke="#D9A441" /><text x="47" y="147" textAnchor="middle" fontSize="12" fill="#8A5B00">m1</text>
          <rect x="150" y="20" width="110" height="150" rx="10" fill="#FAFBFA" stroke="#CCD6D7" /><text x="205" y="14" textAnchor="middle" fontSize="10">stage-1 router</text>
          {shared ? (<>
            <path d="M86 47H150L205 95" stroke="#006D77" strokeWidth="3" fill="none" />
            <path d="M86 143H150L205 95" stroke="#D9A441" strokeWidth="3" strokeDasharray="5 4" fill="none" />
            <rect x="190" y="82" width="70" height="26" rx="6" fill="#FFF4DA" stroke="#8A5B00" /><text x="225" y="99" textAnchor="middle" fontSize="10">one output</text>
            <path d="M260 95H300L340 47" stroke="#006D77" strokeWidth="2.5" fill="none" />
            <path d="M260 95H300L340 143" stroke="#D9A441" strokeWidth="2" fill="none" strokeDasharray="5 4" />
          </>) : (<>
            <path d="M86 47H215" stroke="#006D77" strokeWidth="3" fill="none" /><path d="M86 143H215" stroke="#006D77" strokeWidth="3" fill="none" />
            <rect x="200" y="34" width="60" height="26" rx="6" fill="#EEF6F6" stroke="#9ABBBF" /><text x="230" y="51" textAnchor="middle" fontSize="10">output 0</text>
            <rect x="200" y="130" width="60" height="26" rx="6" fill="#EEF6F6" stroke="#9ABBBF" /><text x="230" y="147" textAnchor="middle" fontSize="10">output 2</text>
            <path d="M260 47H340" stroke="#006D77" strokeWidth="2.5" fill="none" /><path d="M260 143H340" stroke="#006D77" strokeWidth="2.5" fill="none" />
          </>)}
          <rect x="340" y="30" width="72" height="34" rx="6" fill="#F1F4F1" stroke="#CCD6D7" /><text x="376" y="51" textAnchor="middle" fontSize="11">bank 0</text>
          <rect x="340" y="126" width="72" height="34" rx="6" fill="#F1F4F1" stroke="#CCD6D7" /><text x="376" y="147" textAnchor="middle" fontSize="11">{shared ? "bank 1" : "bank 8"}</text>
        </svg>
        <p aria-live="polite" className="explain">{shared
          ? "Banks 0 and 1 share bank-ID bits [3:2], so both requests leave the router through the same output. Only one passes per cycle, even though the banks differ. A model that only counts bank conflicts expects both to proceed."
          : "Banks 0 and 8 differ in bits [3:2], so the requests leave through different outputs and both pass in the same cycle. Here the bank-only model and the hardware agree."}</p>
      </div>
    </section>
  );
}

function opId(m: number, i: number) { return `m${m}:op${String(i).padStart(4, "0")}`; }

function MatchedTable({ runners, traces, inspect }: { runners: Runner[]; traces: Record<string, TraceSelection>; inspect: { op: string } | null }) {
  const { op, selectOp } = useUi();
  const [filter, setFilter] = useState("all");
  const inspectedButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (inspect) setFilter(inspect.op.split(":")[0].slice(1));
  }, [inspect]);
  useEffect(() => {
    if (!inspect || filter !== inspect.op.split(":")[0].slice(1)) return;
    const frame = requestAnimationFrame(() => {
      inspectedButton.current?.scrollIntoView({ block: "center", inline: "nearest" });
      inspectedButton.current?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [inspect, filter]);
  const rows = useMemo(() => {
    const map = new Map<string, { op: string; master: number; index: number; word: number; by: Record<string, { offer?: number; accept?: number }> }>();
    for (const [key, t] of Object.entries(traces)) for (const e of t.events) {
      if (e.master === null || e.operation_index === null || !["offer", "accept"].includes(e.event_kind)) continue;
      const id = opId(e.master, e.operation_index);
      const r = map.get(id) ?? { op: id, master: e.master, index: e.operation_index, word: (e.byte_address ?? 0) >> 2, by: {} };
      r.by[key] = { ...(r.by[key] ?? {}), [e.event_kind]: e.cycle };
      map.set(id, r);
    }
    return [...map.values()].sort((a, b) => a.master - b.master || a.index - b.index);
  }, [traces]);
  const masters = [...new Set(rows.map((r) => r.master))];
  const shown = rows.filter((r) => filter === "all" || String(r.master) === filter);
  return (
    <>
      <div className="toolbar">
        <label className="muted" htmlFor="op-filter">Initiator</label>
        <select id="op-filter" value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="all">All initiators</option>{masters.map((m) => <option key={m} value={String(m)}>m{m}</option>)}
        </select>
        <span className="muted" role="status">Viewing {shown.length} of {rows.length} operations{filter !== "all" ? " (filtered view; whole-run metrics unchanged)" : ""}</span>
        {filter !== "all" ? <button className="text-button" onClick={() => setFilter("all")}>Show all operations</button> : null}
      </div>
      <div className="table-wrap" style={{ maxHeight: 380 }}>
        <table className="program">
          <caption className="screenreader">Matched operations: rows align logical operation IDs; each run keeps its own cycle labels.</caption>
          <thead><tr><th>Operation</th><th>Word</th>{runners.map((r) => <th key={r.key} className="numeric">{r.label}<br /><span className="muted" style={{ fontWeight: 400 }}>accept · wait</span></th>)}</tr></thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.op} className={r.op === op ? "selected" : ""}>
                <td><button ref={r.op === inspect?.op ? inspectedButton : undefined} className="link" onClick={() => selectOp(r.op)} aria-pressed={r.op === op}>{r.op}</button></td>
                <td className="mono">{r.word}</td>
                {runners.map((rn) => { const e = r.by[rn.key]; return <td key={rn.key} className="numeric">{e?.accept !== undefined ? e.accept - 3 : "—"} · {e?.accept !== undefined && e.offer !== undefined ? e.accept - e.offer : "—"}</td>; })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export function useTraces(cv: CaseView) {
  const c = cv.comparison;
  const runners: Runner[] = useMemo(() => {
    const out: Runner[] = [];
    for (const d of c.admitted_order) {
      if (c.model_run_ids?.[d]) out.push({ key: `model-${d}`, label: `Model ${d}`, role: `${c.models?.[d]?.model_id ?? ""} · prediction`, runId: c.model_run_ids[d] });
      if (c.rtl_run_ids?.[d]) out.push({ key: `rtl-${d}`, label: `RTL ${d}`, role: `${c.designs?.[d]?.config_id ?? ""} · reference`, runId: c.rtl_run_ids[d] });
    }
    return out;
  }, [c]);
  const [traces, setTraces] = useState<Record<string, TraceSelection> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setTraces(null);
    Promise.all(runners.map((r) => api.trace(r.runId).then((t) => [r.key, t] as const)))
      .then((pairs) => { if (live) setTraces(Object.fromEntries(pairs)); })
      .catch((e) => { if (live) setErr(String(e.message ?? e)); });
    return () => { live = false; };
  }, [runners]);
  return { runners, traces, err };
}

const STEPS = [
  { t: "The model's view", d: "The bank-only model sees eight different banks, so it lets every initiator through every cycle." },
  { t: "What the hardware did", d: "In the real butterfly, initiators 0 and 1 take turns: each waits every other cycle." },
  { t: "Where they collide", d: "Inside the RTL, router 0's output toward banks 0–3 carries both of them. Measured: contended in most cycles." },
  { t: "Tested, not assumed", d: "Pattern B avoids shared outputs and the model is exact there. A repaired model that adds shared links resolves every witness." },
];

export function DifferenceView({ cv }: { cv: CaseView }) {
  const { gotoStage, selectOp } = useUi();
  const wd = wording(cv);
  const c = cv.comparison;
  const { runners, traces, err } = useTraces(cv);
  const [diag, setDiag] = useState<DiagnosticView | null>(null);
  const [step, setStep] = useState(0);
  const tableDetails = useRef<HTMLDetailsElement>(null);
  const [inspect, setInspect] = useState<{ op: string } | null>(null);
  function inspectRead(op: string) {
    if (tableDetails.current) tableDetails.current.open = true;
    selectOp(op);
    setInspect({ op });
  }
  useEffect(() => {
    let live = true;
    if (cv.diagnostic_available) api.diagnostic(cv.case_id).then((d) => live && setDiag(d && d.valid ? d : null));
    else setDiag(null);
    return () => { live = false; };
  }, [cv.case_id, cv.diagnostic_available]);
  const tl: Record<string, Timeline> = useMemo(() => (traces ? Object.fromEntries(Object.entries(traces).map(([k, t]) => [k, buildTimeline(t)])) : {}), [traces]);
  const maxCycle = Math.max(8, ...Object.values(tl).map((t) => t.finish));
  const mech = cv.mechanism;
  const hotRow = diag?.first_stage_outputs.filter((o) => o.cycles.length).sort((a, b) => b.conflict_cycles - a.conflict_cycles)[0];
  const invalid = !c.rtl_costs;
  const title = invalid ? "Fix the instrument before explaining performance." : mech ? "Different banks, one shared route." :
    c.verdict === "VALID_NO_REVERSAL" ? "Nothing consequential to explain here." : !c.model_margin?.met && c.rtl_margin?.met ? "The model sees no decisive difference; the reference does." : "Neither side separates the designs decisively.";
  const sub = invalid ? "A reference run failed its checks, so its timing is not interpreted." : mech
    ? `The ${plain(c, "B")} is slower than the model thinks because pairs of initiators share stage-1 router outputs. Measured inside the RTL, not assumed.`
    : "Recorded cycles are shown so the result can be checked directly.";
  const emphasizeGrid = mech && step === 1 ? [0, 1] : [];
  return (
    <>
      <div className="stage-meta"><span className="eyebrow">03 / Difference</span><span className={`tag ${wd.tone}`}>{wd.tag} · executed</span></div>
      <h1 id="stage-heading" tabIndex={-1} className="hero-title">{title}</h1>
      <p className="hero-sub">{sub}</p>

      {diag && !invalid ? (
        <section className="panel" aria-labelledby="heat-h" id="heat">
          <div className="panel-head"><div><h2 id="heat-h">Where the time goes, measured inside the RTL</h2>
            <p>Each row is a stage-1 router output in the butterfly; each cell one cycle. Amber: two initiators wanted it, so one waited.</p></div><span className="stamp">MEASURED · DIAGNOSTIC TRACE</span></div>
          <div className="panel-body">
            {hotRow && hotRow.conflict_cycles > 0 ? (
              <div className="callout"><strong>{hotRow.label.replace("router", "Router")}</strong> served {hotRow.inputs.map((m) => `m${m}`).join(" and ")}: {hotRow.requests_passed} requests, contended in <b>{hotRow.conflict_cycles}</b> of {diag.window[1] - diag.window[0] + 1} cycles.</div>
            ) : <div className="callout neutral">No stage-1 output was contended in this run.</div>}
            <div className="chart-scroll" tabIndex={0} role="region" aria-label="Router contention by cycle (scrolls sideways on narrow screens)">
              <RouterHeatmap outputs={diag.first_stage_outputs} window={diag.window} emphasize={step === 2 && hotRow ? `${hotRow.router}:${hotRow.output}` : undefined} />
            </div>
            <p className="axis-note">Signals: <span className="mono">bfly_net.router_req_in/router_gnt_out</span> from a trace build of the same sources (run {diag.diagnostic_run_id.slice(-6)}). Boundary events identical to the reference run; input mapping checked in {diag.mapping_check.cycles_checked} cycles, {diag.mapping_check.mismatches} mismatches.</p>
          </div>
        </section>
      ) : null}

      <section className="panel" aria-labelledby="grid-h" id="grids">
        <div className="panel-head"><div><h2 id="grid-h">Butterfly, initiator by initiator</h2><p>Teal: accepted. Amber: waiting. Click an accepted cell to inspect that read.</p></div><span className="stamp">RECORDED EVENTS</span></div>
        <div className="panel-body">
          {err ? <div className="err-box">{err}</div> : !traces ? <div className="loading">Loading recorded events…</div> : (
            <div className="grid-pair">
              {tl["model-B"] ? <figure><figcaption><strong>What the model predicted</strong><span>{c.models?.B?.model_id} · finishes cycle {tl["model-B"].finish - 3}</span></figcaption>
                <div className="chart-scroll"><ContentionGrid tl={tl["model-B"]} masters={8} maxCycle={maxCycle} title="Model B" emphasize={emphasizeGrid} onPick={inspectRead} /></div></figure> : null}
              {tl["rtl-B"] && !invalid ? <figure><figcaption><strong>What the hardware did</strong><span>RTL {c.designs?.B?.config_id} · finishes cycle {tl["rtl-B"].finish - 3}</span></figcaption>
                <div className="chart-scroll"><ContentionGrid tl={tl["rtl-B"]} masters={8} maxCycle={maxCycle} title="RTL B" emphasize={emphasizeGrid} onPick={inspectRead} /></div></figure> : <div className="race-invalid">Reference run invalid · not shown as timing</div>}
            </div>
          )}
        </div>
      </section>

      {mech ? (
        <section className="stepper" aria-label="Walk through the explanation">
          <div className="stepper-dots">{STEPS.map((s, i) => <button key={i} className={i === step ? "on" : i < step ? "past" : ""} onClick={() => setStep(i)} aria-label={`Step ${i + 1}: ${s.t}`} aria-current={i === step}>{i + 1}</button>)}</div>
          <div className="stepper-body"><strong>{STEPS[step].t}</strong><p>{STEPS[step].d}</p></div>
          <div className="stepper-nav"><button className="btn compact" disabled={step === 0} onClick={() => setStep(step - 1)}>Previous</button><button className="btn compact primary" disabled={step === STEPS.length - 1} onClick={() => setStep(step + 1)}>Next step</button></div>
        </section>
      ) : null}

      {mech ? (
        <section className="panel" aria-labelledby="mech-h" id="mech">
          <div className="panel-head"><div><h2 id="mech-h">The claim and its evidence</h2></div><span className="stamp">INTERPRETATION · LINKED EVIDENCE</span></div>
          <div className="claim-grid">
            <div className="claim-col"><span className="field-role">Predicted before running</span>
              {Object.entries(mech.prediction_before_execution.predicted_active_acceptance_windows).map(([k, v]) => <div key={k} className="pred"><span>{k}</span><strong>{v}</strong></div>)}
              <span className="badge caution">source-derived hypothesis</span></div>
            <div className="claim-col wide"><span className="field-role">Observed</span><ul>{mech.observations.slice(0, 4).map((o) => <li key={o.statement}>{o.statement}</li>)}</ul></div>
            <div className="claim-col"><span className="field-role">Ruled out</span><ul>{mech.alternatives.map((a) => <li key={a.explanation}><b>{a.explanation}</b> · {a.status}</li>)}</ul></div>
          </div>
          <div className="diagram-note">Supported explanation: <Term k="route">internal route contention</Term>. The evidence is interventions plus a validated repair; it is not a unique causal proof.</div>
        </section>
      ) : null}

      {mech ? <RouteExplorer /> : null}

      {traces ? (
        <details ref={tableDetails} className="table-details panel" style={{ padding: "0 4px" }} id="traces"><summary>All {Object.values(traces)[0]?.events.length ? "" : ""}recorded operations, matched across the four runs</summary>
          <div className="panel-body"><MatchedTable runners={runners} traces={traces} inspect={inspect} /></div></details>
      ) : null}
      <div className="actions"><button className="btn primary" onClick={() => gotoStage(cv.repair ? 3 : 4)}>{cv.repair ? "See the repair →" : "Inspect the evidence →"}</button></div>
    </>
  );
}
