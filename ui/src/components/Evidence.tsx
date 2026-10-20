import { useEffect, useState } from "react";
import { api, type Job } from "../api";
import type { ArtifactLink, CaseView, ProjectRecord, StudySummary } from "../types";
import { digestShort, wording } from "../logic";
import { Term } from "./common";
import { ARM_STYLE, BenchBars, DiscoveryCurves } from "./Charts";
import { BrowserEntry } from "./BrowserEntry";

function Files({ a }: { a: ArtifactLink }) {
  return (
    <ul className="files">{a.files.slice(0, 12).map((f) => <li key={f.name}><a href={api.artifactUrl(a.artifact_id, f.name)} target="_blank" rel="noreferrer">{f.name}</a><span className="mono muted">{digestShort(f.sha256)}</span></li>)}
      {a.files.length > 12 ? <li className="muted">+{a.files.length - 12} more in the manifest</li> : null}</ul>
  );
}

function Pipeline({ cv, rec }: { cv: CaseView; rec: ProjectRecord | null }) {
  const c = cv.comparison;
  const [sel, setSel] = useState("verdict");
  const src = rec?.locks?.["sources.lock.json"] as { repositories?: { name: string; commit: string }[] } | undefined;
  const tool = rec?.locks?.["toolchain.lock.json"] as { bundle?: { release: string; sha256_downloaded: string }; expected_tool_versions?: Record<string, string> } | undefined;
  const link = (role: string) => cv.evidence.find((a) => a.role.startsWith(role));
  const nodes = [
    { id: "src", t: "Pinned RTL", s: "PULP interconnect", detail: <dl className="kv-wide">{src?.repositories?.map((r) => [<dt key={r.name}>{r.name}</dt>, <dd key={r.name + "v"} className="mono">{r.commit}</dd>])}</dl> },
    { id: "build", t: "Verilator build", s: tool?.expected_tool_versions?.verilator?.split(" ").slice(0, 2).join(" ") ?? "", detail: <dl className="kv-wide"><dt>Toolchain</dt><dd>OSS CAD Suite {tool?.bundle?.release} · sha256 {digestShort(tool?.bundle?.sha256_downloaded)}</dd><dt>Epoch</dt><dd className="mono">{cv.reference_epoch}</dd></dl> },
    { id: "rtl", t: "RTL runs", s: `A ${c.rtl_costs?.A ?? "—"} · B ${c.rtl_costs?.B ?? "—"} cycles`, detail: <>{["RTL reference run, design A", "RTL reference run, design B"].map((r) => { const a = link(r); return a ? <div key={r}><strong>{r}</strong> <span className="mono muted">{a.artifact_id}</span><Files a={a} /></div> : null; })}</> },
    { id: "model", t: "Fast-model runs", s: `A ${c.model_costs?.A ?? c.model_predictions?.A?.makespan ?? "—"} · B ${c.model_costs?.B ?? c.model_predictions?.B?.makespan ?? "—"}`, detail: <>{["fast-model prediction, design A", "fast-model prediction, design B"].map((r) => { const a = link(r); return a ? <div key={r}><strong>{r}</strong> <span className="mono muted">{a.artifact_id}</span><Files a={a} /></div> : null; })}</> },
    { id: "check", t: "Independent checker", s: "recomputes from raw events", detail: <p>Every run's validity and cost were recomputed from its raw event stream by <span className="mono">rift/evaluate/checker.py</span>: one offer/accept/complete per read, bank/row mapping, data against its own copy of the memory function, release rules, at most one acceptance per bank per cycle, and agreement with the runner's own summary.</p> },
    { id: "verdict", t: "Verdict", s: wording(cv).tag, detail: (() => { const a = link("independent comparison verdict"); return a ? <div><strong>{cv.claims[0]?.statement}</strong><p className="axis-note">Margin: <Term k="margin">max(2 cycles, 2% of the smaller cost)</Term> in each domain · tie policy: first design · run {a.artifact_id}</p><Files a={a} /></div> : null; })() },
  ];
  const cur = nodes.find((n) => n.id === sel)!;
  return (
    <section className="panel" aria-labelledby="pipe-h" id="pipeline">
      <div className="panel-head"><div><h2 id="pipe-h">How this result was produced</h2><p>Click a step to see exactly what it produced and its fingerprints.</p></div><span className="stamp">IMMUTABLE ARTIFACTS</span></div>
      <div className="panel-body">
        <div className="pipe">
          {nodes.map((n, i) => (
            <div key={n.id} className="pipe-step">
              <button className={`pipe-node${sel === n.id ? " on" : ""}`} onClick={() => setSel(n.id)} aria-pressed={sel === n.id}><strong>{n.t}</strong><span>{n.s}</span></button>
              {i < nodes.length - 1 ? <span className="pipe-arrow" aria-hidden="true">→</span> : null}
            </div>
          ))}
        </div>
        <div className="pipe-detail" role="region" aria-label={cur.t}>{cur.detail}</div>
      </div>
    </section>
  );
}

function Replay({ cv, enabled }: { cv: CaseView; enabled: boolean }) {
  const [job, setJob] = useState<Job | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!job || job.state === "COMPLETED" || job.state === "FAILED") return;
    const t = setInterval(async () => { const j = (await api.jobs()).jobs?.find((x) => x.job_id === job.job_id); if (j) setJob(j); }, 600);
    return () => clearInterval(t);
  }, [job]);
  return (
    <div>
      <button className="btn" disabled={!enabled || !cv.workload || (job !== null && (job.state === "QUEUED" || job.state === "RUNNING"))}
        onClick={async () => { setErr(null); try { setJob(await api.replay(cv.case_id, 2)); } catch (e) { setErr(String((e as Error).message)); } }}>
        Replay the reference locally · budget 2 RTL executions
      </button>
      {!enabled ? <p className="axis-note">Native replay uses the local server (<span className="mono">rift serve --allow-run</span>). For execution on this site, use “Re-run in your browser” above.</p> : null}
      {err ? <div className="err-box" style={{ marginTop: 8 }}>{err}</div> : null}
      {job ? <div className="job" role="status"><strong>Live execution · job {job.job_id}</strong> · {job.state.toLowerCase()} · {job.used_rtl_executions}/{job.budget_rtl_executions} RTL executions
        {job.result ? <p style={{ margin: "6px 0 0" }}>RTL {JSON.stringify(job.result.rtl_costs)} · {job.result.matches_recorded_reference ? "identical to the recorded reference" : "DIFFERS from the recorded reference"}</p> : null}
        {job.error ? <p style={{ margin: "6px 0 0", color: "var(--error)" }}>{job.error}</p> : null}</div> : null}
    </div>
  );
}

function exportCase(cv: CaseView) {
  const blob = new Blob([JSON.stringify({
    exported_by: "RIFT evidence viewer", exported_at: new Date().toISOString(), case_id: cv.case_id, reference_epoch: cv.reference_epoch,
    evidence_basis: cv.evidence_basis, scope: cv.evaluation_scope, provenance: cv.case_provenance, metric: cv.metric,
    claims: cv.claims, comparison: cv.comparison, model_patch: cv.repair ? { candidate: cv.repair.candidate_model_id, lifecycle: cv.repair.lifecycle, patch_digest: cv.repair.patch_digest } : null,
    limitations: cv.limitations, artifacts: cv.evidence.map((a) => ({ id: a.artifact_id, role: a.role, manifest_digest: a.manifest_digest })), view_digest: cv.view_digest, subset: "complete case view",
  }, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `rift-${cv.case_id}-${cv.reference_epoch}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
}

const CASE_TITLES: Record<string, string> = {
  C1_bank_only_omission: "C1 · bank-only model", C2_topology_rr_control: "C2 · approximate arbitration", C3_lfsr_every_cycle: "C3 · priority advance bug",
  C4_bank_mapping_width: "C4 · wrong bank mapping", C5_lic_unfair_arbitration: "C5 · unfair crossbar arbiter", C6_response_latency_offset: "C6 · latency off by one",
};

function kernelRange(results: { kernel_speedup?: number | null }[]): string {
  const k = results.map((r) => r.kernel_speedup).filter((x): x is number => typeof x === "number");
  return k.length ? ` Simulation kernel alone: ${Math.min(...k).toFixed(1)}–${Math.max(...k).toFixed(1)}×; process start-up and workload I/O take the rest.` : "";
}

function screenSentence(scr: StudySummary): string {
  const label = (a: string) => ARM_STYLE[a]?.label ?? a;
  const won = new Map<string, string[]>();
  const none: string[] = [];
  for (const [cid, cs] of Object.entries(scr.cases)) {
    const ranked = Object.entries(cs.arms).filter(([, s]) => s.status === "COMPLETED")
      .map(([a, s]) => [a, s.credited_counterexamples ?? 0] as const).sort((p, q) => q[1] - p[1]);
    const short = cid.split("_")[0];
    if (!ranked.length || ranked[0][1] === 0) { none.push(short); continue; }
    const best = ranked[0][1];
    const winners = ranked.filter((r) => r[1] === best).map((r) => label(r[0])).join(" and ");
    const next = ranked.find((r) => r[1] < best);
    won.set(winners, [...(won.get(winners) ?? []), `${short} (${best}${next ? ` vs ${next[1]}` : ""})`]);
  }
  const parts = [...won.entries()].map(([who, cases]) => `${who} on ${cases.join(", ")}`);
  return `Most credited reversals: ${parts.join("; ")}.${none.length ? ` No method found one for ${none.join(", ")}.` : ""}`;
}

export function EvidenceView({ cv, rec, runEnabled }: { cv: CaseView; rec: ProjectRecord | null; runEnabled: boolean }) {
  const wd = wording(cv);
  const scr = rec?.screen;
  const formal = rec?.formal;
  return (
    <>
      <div className="stage-meta"><span className="eyebrow">05 / Evidence</span><span className={`tag ${wd.tone}`}>{wd.tag} · executed</span></div>
      <h1 id="stage-heading" tabIndex={-1} className="hero-title">Every number traces back to a recorded run.</h1>
      <p className="hero-sub">Fingerprinted artifacts, independent checks, and the commands to reproduce everything without any special service.</p>
      <Pipeline cv={cv} rec={rec} />
      <BrowserEntry key={cv.case_id} cv={cv} />

      {scr ? (
        <section className="panel" aria-labelledby="study-h" id="study">
          <div className="panel-head"><div><h2 id="study-h">How each search method performed</h2><p>Six model defects, the same 64-run hardware budget for every method. Higher and earlier is better.</p></div><span className="stamp">DISCOVERY SCREEN</span></div>
          <div className="panel-body">
            <DiscoveryCurves curves={scr.curves} cases={scr.case_definitions.map((c) => ({ id: c.case_id, title: CASE_TITLES[c.case_id] ?? c.case_id }))} />
            <div className="callout neutral">{screenSentence(scr)} Supplied patterns L/B/M earn no credit.</div>
          </div>
        </section>
      ) : null}

      <div className="two-col">
        {rec?.benchmark ? (
          <section className="panel" aria-labelledby="bench-h" id="bench">
            <div className="panel-head"><div><h2 id="bench-h">Model speed vs hardware simulation</h2><p>{rec.benchmark.basket.size} workloads, warm, same machine. Target {rec.benchmark.target_speedup}×.</p></div></div>
            <div className="panel-body"><BenchBars target={rec.benchmark.target_speedup} rows={rec.benchmark.results.map((r) => ({ label: r.model_id.replace(/_v\d+$/, "").replaceAll("_", " "), rtl: r.median_seconds.rtl_batched_summary_only ?? r.median_seconds.rtl_batched, model: r.median_seconds.compiled_model_summary_only ?? r.median_seconds.model_cost_only }))} />
              <p className="axis-note">Compiled C++ model vs batched Verilator, summary-only on both sides (what the search loop consumes).{kernelRange(rec.benchmark.results)} Every timing mode is in the benchmark artifact.</p></div>
          </section>
        ) : null}
        {rec?.gate0a ? (
          <section className="panel" aria-labelledby="gate-h" id="checks">
            <div className="panel-head"><div><h2 id="gate-h">Harness validation · {rec.gate0a.checks.filter((x) => x.passed).length}/{rec.gate0a.checks.length}</h2><p>Each tile is a real run on the 2×2 harness, including deliberately injected faults that must be caught.</p></div></div>
            <div className="panel-body"><div className="tiles">{rec.gate0a.checks.map((g) => <span key={g.check} className={`tile ${g.passed ? "ok" : "bad"}`} title={g.expectation}>{g.passed ? "✓" : "✗"} {g.check.replace("injected_fault_detected:", "catches ").replaceAll("_", " ").toLowerCase()}</span>)}</div></div>
          </section>
        ) : null}
      </div>

      {formal ? (
        <section className="panel" aria-labelledby="formal-h" id="formal">
          <div className="panel-head"><div><h2 id="formal-h">Formal proofs on the 2×2 harness</h2><p>{formal.scope_note}</p></div><span className="stamp">SBY · {String(formal.inventory.asserts)} ASSERTS</span></div>
          <div className="panel-body">
            <div className="tiles">{formal.properties.map((p) => <span key={p.id} className="tile ok" title={p.statement}>{p.id} {p.statement}</span>)}</div>
            <div className="fact-row">{Object.entries(formal.tasks).map(([k, t]) => <div key={k} className={`fact ${/PROVED|NO_COUNTER|REACHED/.test(t.outcome) || (k === "negative_control" && t.outcome === "COUNTEREXAMPLE") ? "ok" : "warn"}`}><span>{k.replaceAll("_", " ")}</span><strong className="small">{t.outcome.replaceAll("_", " ").toLowerCase()}</strong></div>)}</div>
          </div>
        </section>
      ) : null}

      <section className="panel" aria-labelledby="repro-h" id="repro">
        <div className="panel-head"><div><h2 id="repro-h">Reproduce it</h2><p>Deterministic, offline, no accounts or API keys.</p></div></div>
        <div className="panel-body">
          {(rec?.reproduce ?? []).map((cmd) => <div className="copy-row" key={cmd}><code>{cmd}</code><button className="btn compact" onClick={() => navigator.clipboard?.writeText(cmd)} aria-label={`Copy command ${cmd}`}>Copy</button></div>)}
          <div className="actions" style={{ margin: "14px 0 0" }}><Replay cv={cv} enabled={runEnabled} /><button className="btn" onClick={() => exportCase(cv)}>Export this case (JSON with provenance)</button></div>
        </div>
      </section>

      {rec ? (
        <section className="panel" aria-labelledby="record-h" id="record">
          <div className="panel-head"><div><h2 id="record-h">Record, provenance & status</h2></div></div>
          <div className="panel-body two-col">
            <div><h3 className="sub-h">Done and verified</h3><ul className="checklist">{rec.status.implemented.map((x) => <li key={x}><span className="status-mark">✓</span>{x}</li>)}</ul></div>
            <div><h3 className="sub-h">Scope boundaries</h3><ul className="checklist">{rec.status.not_done.map((x) => <li key={x}><span className="status-mark">○</span>{x}</li>)}</ul></div>
          </div>
        </section>
      ) : null}

      <details className="table-details panel" style={{ padding: "0 4px" }} id="claims"><summary>Claim index: every artifact behind this case ({cv.evidence.length})</summary>
        <div className="panel-body"><ul className="record-list">{cv.evidence.map((a) => (
          <li key={a.artifact_id + a.role}><span className="icon" aria-hidden="true">{a.kind === "rtl" ? "R" : a.kind === "model" ? "M" : "S"}</span>
            <div><strong>{a.role}</strong><p><span className="mono">{a.artifact_id}</span> · manifest {digestShort(a.manifest_digest)}</p></div><span className="tag">{a.status ?? "—"}</span></li>))}</ul></div></details>
    </>
  );
}
