import type { Specimen, Specimens } from "../types";
import { CostChart, ExactTable } from "./Decision";

function teach(f: Specimen) {
  if (!f.model || !f.reference || !f.reference_valid) return null;
  const m = f.model, r = f.reference;
  const dm = m.A - m.B, dr = r.A - r.B;
  const ok = (d: number, a: number, b: number) => Math.abs(d) >= 2 && Math.abs(d) * 50 >= Math.min(a, b);
  const enough = ok(dm, m.A, m.B) && ok(dr, r.A, r.B);
  const verdict = !enough ? "TIE_OR_SMALL_MARGIN" : dm * dr < 0 ? "VALID_COUNTEREXAMPLE" : "VALID_NO_REVERSAL";
  const mc = m.A <= m.B ? "A" : "B";
  const extra = r[mc] - Math.min(r.A, r.B);
  return { verdict, mc, extra, regret: extra / Math.max(1, Math.min(r.A, r.B)) };
}

export function SpecimenView({ data, id, onOpenCase }: { data: Specimens; id: string; onOpenCase: (id: string) => void }) {
  const f = data.fixtures.find((x) => x.id === id) ?? data.fixtures[0];
  const t = teach(f);
  const labels = { A: "LIC · 8 banks", B: "BFLY · 16 banks" };
  return (
    <>
      <div className="stage-meta"><span className="eyebrow">Illustrative specimen · {data.namespace}{f.id}</span><span className="tag caution">{f.kind === "source_prediction" ? "Source hypothesis" : "Illustrative fixture"}</span></div>
      <h1 id="stage-heading" tabIndex={-1}>{f.label}</h1>
      <p className="lead">{f.evidence_status}. These authored values come from the v1.1 interface reference. They are not experimental results and are never ingested as evidence. {f.id === "pattern_m" ? "" : "Executed cases are listed in the case selector."}</p>
      <div className="notice"><strong>Illustrative interface data · no RTL executed.</strong> {data.provenance}</div>
      {f.kind === "source_prediction" && f.predicted_active_acceptance_cycles ? (
        <section className="panel"><div className="panel-head"><div><h2>Source-predicted acceptance windows</h2><p>Unmeasured predictions recorded before execution. They never populate makespan or regret.</p></div><span className="stamp">SOURCE-DERIVED HYPOTHESIS</span></div>
          <div className="panel-body"><div className="calibration-grid">{Object.entries(f.predicted_active_acceptance_cycles).map(([k, v]) => (
            <div className="prediction-row" key={k}><div><strong>{k.replaceAll("_", " ")}</strong><p>active acceptance cycles · prediction only</p></div><div className="prediction-number">{v}<small>predicted</small></div></div>))}</div>
            <div className="actions"><button className="btn primary" onClick={() => onOpenCase("pattern-m")}>Open the executed Pattern M case <span aria-hidden="true">→</span></button></div>
            <p className="trace-note">Zero AI discovery credit. The executed case reports its own measured acceptance windows and makespans with their artifacts.</p></div></section>
      ) : (
        <section className="panel"><div className="panel-head"><div><h2>Prediction meets reference (illustrative)</h2><p>Authored example values.</p></div><span className="stamp">ILLUSTRATIVE VALUES</span></div>
          <div className="legend"><span className="legend-item"><span className="legend-line" />Example model · dashed</span><span className="legend-item"><span className="legend-line solid" />Example reference · solid</span></div>
          <CostChart order={["A", "B"]} labels={labels} model={f.model} reference={f.reference_valid ? f.reference : null} refUnavailable={f.failure ?? "Reference invalid"} caption="Illustrative model and reference values (no RTL executed)" />
          <ExactTable order={["A", "B"]} labels={labels} model={f.model} reference={f.reference_valid ? f.reference : null} caption="Illustrative values" refUnavailable="Invalid" />
          <div className={`result-line ${!t ? "error" : t.verdict === "VALID_NO_REVERSAL" ? "neutral" : ""}`}>
            <div><strong>{!t ? "Comparison unavailable: the example reference is invalid." : t.verdict === "VALID_COUNTEREXAMPLE" ? `Example: choosing ${t.mc} adds ${t.extra} cycles.` : t.verdict === "VALID_NO_REVERSAL" ? "Example: the orderings agree." : "Example: no decisive ordering under the margin."}</strong>
              <p>Teaching arithmetic for the specimen only. {data.tie_break}</p></div>
            <div className="result-value">{t && t.verdict === "VALID_COUNTEREXAMPLE" ? `${(t.regret * 100).toFixed(1)}%` : "—"}<small>illustrative</small></div>
          </div>
          {f.repair?.withheld_example ? <div className="panel-body"><div className="notice">Illustrative rejected repair: parent {JSON.stringify(f.repair.withheld_example.parent_model)}, candidate {JSON.stringify(f.repair.withheld_example.candidate_model)}, reference {JSON.stringify(f.repair.withheld_example.reference)}. {f.repair.withheld_example.scope}</div></div> : null}
        </section>
      )}
      <div className="section-foot">Specimen namespace {data.namespace}. Nothing on this page was executed.</div>
    </>
  );
}
