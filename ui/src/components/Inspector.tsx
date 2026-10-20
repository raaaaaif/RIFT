import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { api } from "../api";
import type { CaseView, TraceSelection } from "../types";
import { digestShort, pct, verdictLabel } from "../logic";
import { TERMS, Term, provenanceLabel, scopeLabel, useUi } from "./common";

export type InspectorTab = "overview" | "calculation" | "record";
const TABS: InspectorTab[] = ["overview", "calculation", "record"];

function OpDetail({ cv, op }: { cv: CaseView; op: string }) {
  const c = cv.comparison;
  const [rows, setRows] = useState<{ runner: string; offer?: number; accept?: number; complete?: number; data?: number }[] | null>(null);
  useEffect(() => {
    const m = /^m(\d+):op(\d+)$/.exec(op);
    if (!m) return;
    const master = Number(m[1]), index = Number(m[2]);
    const entries: [string, string][] = [];
    for (const d of c.admitted_order) {
      if (c.model_run_ids?.[d]) entries.push([`Model ${d}`, c.model_run_ids[d]]);
      if (c.rtl_run_ids?.[d]) entries.push([`RTL ${d}`, c.rtl_run_ids[d]]);
    }
    let live = true;
    Promise.all(entries.map(([label, id]) => api.trace(id).then((t: TraceSelection) => {
      const r: { runner: string; offer?: number; accept?: number; complete?: number; data?: number } = { runner: label };
      for (const e of t.events) if (e.master === master && e.operation_index === index) {
        if (e.event_kind === "offer") r.offer = e.cycle; else if (e.event_kind === "accept") r.accept = e.cycle; else if (e.event_kind === "complete") { r.complete = e.cycle; r.data = e.read_data; }
      }
      return r;
    }))).then((x) => { if (live) setRows(x); }).catch(() => { if (live) setRows([]); });
    return () => { live = false; };
  }, [op, c]);
  return (
    <div className="op-detail">
      <h3>Selected operation <span className="mono">{op}</span></h3>
      {!rows ? <p>Loading recorded events…</p> : (
        <table><thead><tr><th>Run</th><th>offer</th><th>accept</th><th>complete</th></tr></thead>
          <tbody>{rows.map((r) => <tr key={r.runner}><td>{r.runner}</td><td className="numeric">{r.offer ?? "—"}</td><td className="numeric">{r.accept ?? "—"}</td><td className="numeric">{r.complete ?? "—"}</td></tr>)}</tbody></table>
      )}
      {rows && rows[0]?.data !== undefined ? <p>Read data {rows.find((r) => r.runner.startsWith("RTL"))?.data} = f(q), checked against the independent oracle.</p> : null}
      <p>Actual cycle coordinates from each run's event stream. Rows are joined by the logical operation ID, not by cycle.</p>
    </div>
  );
}

export function Inspector({ cv, tab, setTab, term, clearTerm, onClose }: { cv: CaseView | null; tab: InspectorTab; setTab: (t: InspectorTab) => void; term: string | null; clearTerm: () => void; onClose: () => void }) {
  const { op } = useUi();
  const tabRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const onKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    const i = TABS.indexOf(tab);
    let n = i;
    if (e.key === "ArrowRight") n = (i + 1) % TABS.length; else if (e.key === "ArrowLeft") n = (i + TABS.length - 1) % TABS.length;
    else if (e.key === "Home") n = 0; else if (e.key === "End") n = TABS.length - 1; else return;
    e.preventDefault();
    setTab(TABS[n]);
    tabRefs.current[TABS[n]]?.focus();
  };
  const c = cv?.comparison;
  return (
    <aside className="inspector" id="inspector" aria-labelledby="inspector-heading" tabIndex={-1} onKeyDown={(e) => { if (e.key === "Escape") onClose(); }}>
      <div className="inspector-top"><h2 id="inspector-heading">Evidence inspector</h2><button className="text-button" onClick={onClose} aria-label="Close inspector">Close ×</button></div>
      <div className="inspector-tabs" role="tablist" aria-label="Evidence detail">
        {TABS.map((t) => (
          <button key={t} role="tab" id={`inspector-tab-${t}`} aria-selected={tab === t} aria-controls="inspector-content" tabIndex={tab === t ? 0 : -1}
            ref={(el) => { tabRefs.current[t] = el; }} onClick={() => setTab(t)} onKeyDown={onKey}>{t[0].toUpperCase() + t.slice(1)}</button>
        ))}
      </div>
      <div className="inspector-body" id="inspector-content" role="tabpanel" aria-labelledby={`inspector-tab-${tab}`}>
        {term && TERMS[term] ? (
          <div className="definition" role="note">
            <h3 className="help-title">{TERMS[term][0]}</h3>
            <p>{TERMS[term][1]}</p>
            <button className="text-button" onClick={clearTerm}>Close explanation</button>
          </div>
        ) : null}
        {!cv || !c ? <p>Select a case.</p> : tab === "overview" ? (
          <>
            <h3>What you are looking at</h3>
            <p>An executed case: the fast model and the pinned RTL reference ran the same logical workload; the independent evaluator classified the pair.</p>
            <dl className="kv">
              <dt>Case</dt><dd className="mono">{cv.case_id}</dd>
              <dt>Evidence basis</dt><dd>Executed artifact</dd>
              <dt>Verdict</dt><dd>{verdictLabel(c.verdict)}</dd>
              <dt>Reference</dt><dd>{cv.reference_validity.replaceAll("_", " ").toLowerCase()}</dd>
              <dt>Epoch</dt><dd className="mono">{cv.reference_epoch}</dd>
              <dt>Provenance</dt><dd>{provenanceLabel(cv.case_provenance)}</dd>
              <dt>Scope</dt><dd>{scopeLabel(cv.evaluation_scope)}</dd>
              <dt><Term k="credit">Discovery credit</Term></dt><dd>{cv.discovery_credit}</dd>
              <dt>Patch</dt><dd>{cv.repair ? cv.repair.lifecycle.replaceAll("_", " ").toLowerCase() : "none"}</dd>
            </dl>
            <h3>Interpretation boundary</h3>
            <ul className="checklist">{cv.limitations.slice(0, 6).map((l) => <li key={l}><span className="status-mark">–</span>{l}</li>)}</ul>
            {op ? <><hr className="micro-rule" /><OpDetail cv={cv} op={op} /></> : null}
          </>
        ) : tab === "calculation" ? (
          <>
            <h3>Exact rule</h3>
            <div className="calc">{`dM = M_A − M_B${c.model_costs ? ` = ${c.model_costs.A} − ${c.model_costs.B} = ${c.dM}` : " (unavailable)"}
dR = R_A − R_B${c.rtl_costs ? ` = ${c.rtl_costs.A} − ${c.rtl_costs.B} = ${c.dR}` : " (unavailable)"}
threshold_M = max(2, 0.02 × ${c.model_margin?.min_cost ?? "—"}) = ${c.model_margin?.threshold_decimal ?? "—"} → ${c.model_margin ? (c.model_margin.met ? "met" : "not met") : "—"}
threshold_R = max(2, 0.02 × ${c.rtl_margin?.min_cost ?? "—"}) = ${c.rtl_margin?.threshold_decimal ?? "—"} → ${c.rtl_margin ? (c.rtl_margin.met ? "met" : "not met") : "—"}
strict reversal ⇔ dM·dR < 0 and both thresholds met
dM·dR = ${c.dM !== null && c.dR !== null ? c.dM * c.dR : "—"}
verdict = ${c.verdict}`}</div>
            <h3>Selection and regret</h3>
            <div className="calc">{c.selection ? `model choice = argmin(model) = ${c.model_choice}   (ties → first design)
reference best = argmin(RTL) = ${c.rtl_best}
regret = (R_${c.selection.chosen} − R_${c.selection.reference_best}) / max(1, R_${c.selection.reference_best})
       = ${c.selection.extra_cycles} / ${c.selection.denominator_cycles} = ${c.selection.regret.numerator}/${c.selection.regret.denominator} = ${pct(c.selection.regret.decimal, 2)}${c.verdict === "TIE_OR_SMALL_MARGIN" ? "\n(not a strict reversal: shown for completeness)" : ""}` : "No regret: the comparison is unavailable."}</div>
            <p>Computed by the independent evaluator with exact integers. The viewer re-checks the arithmetic and blocks the claim if it disagrees.</p>
          </>
        ) : (
          <>
            <h3>Record</h3>
            <dl className="kv">
              <dt>Comparison</dt><dd className="mono">{c.comparison_run_id.slice(-24)}</dd>
              {Object.entries(c.rtl_run_ids ?? {}).map(([d, id]) => [<dt key={`r${d}`}>RTL {d}</dt>, <dd key={`rv${d}`} className="mono">{id.slice(-24)}</dd>])}
              {Object.entries(c.model_run_ids ?? {}).map(([d, id]) => [<dt key={`m${d}`}>Model {d}</dt>, <dd key={`mv${d}`} className="mono">{id.slice(-24)}</dd>])}
              <dt>Workload</dt><dd className="mono">{digestShort(c.workload_digest)}</dd>
              {Object.entries(c.models ?? {}).map(([d, m]) => [<dt key={`md${d}`}>{d} model digest</dt>, <dd key={`mdv${d}`} className="mono">{digestShort(m.model_digest)}</dd>])}
              <dt>View digest</dt><dd className="mono">{digestShort(cv.view_digest)}</dd>
            </dl>
            {op ? <OpDetail cv={cv} op={op} /> : <p>Select an operation in Workload or Difference to see its recorded cycles here.</p>}
          </>
        )}
        <div className="inspector-note"><strong>Evidence stays attached.</strong> Every value belongs to this case and epoch. Changing the case resets the selected operation, explanation and exploration state.</div>
      </div>
    </aside>
  );
}
