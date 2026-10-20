import { lazy, Suspense, useEffect, useRef, useState } from "react";
import type { BrowserIntent } from "../components/BrowserEntry";
import { loadManifest, loadRecords } from "./assets";
import { BrowserRunner } from "./client";
import { canonical, compile, spreadTraffic } from "./contracts";
import LiveRace from "./LiveRace";
import type { BrowserManifest, ReplayRecord, RunResult, Workload } from "./types";
import "./browser.css";

const WorkloadEditor = lazy(() => import("./WorkloadEditor"));
const cycles = (r: RunResult, key: string) => r.executions[key].check.makespan ?? "withheld";
const verdict = (v: string) => ({ VALID_COUNTEREXAMPLE: "chooses the slower design", VALID_NO_REVERSAL: "agrees with RTL", TIE_OR_SMALL_MARGIN: "no decisive ordering" }[v] ?? v.replaceAll("_", " ").toLowerCase());

function ResultTable({ before, result }: { before: RunResult | null; result: RunResult }) {
  const rows = before && before.workload_digest !== result.workload_digest ? [["Original Pattern M", before], ["Current workload", result]] as const : [["Current workload", result]] as const;
  return <div className="table-wrap"><table className="live-values">
    <caption>Measured on this device · cycles, lower is better</caption>
    <thead><tr><th>Workload</th><th>Crossbar RTL</th><th>Butterfly RTL</th><th>Original B prediction</th><th>Repaired B prediction</th></tr></thead>
    <tbody>{rows.map(([label, r]) => <tr key={label}><th>{label}</th>{["rtl-A", "rtl-B", "model-parent", "model-repaired"].map(k => <td key={k}>{cycles(r, k)}</td>)}</tr>)}</tbody>
  </table></div>;
}

function Provenance({ result, manifest }: { result: RunResult; manifest: BrowserManifest }) {
  return <details className="lab-details"><summary>Execution details & portable verification</summary>
    <p>Event hashes test reproduction of this site's published artifact. They are not independent authentication of the website. The browser checker separately validates read lifecycles, data, timing, bank mapping, and monitor outcomes.</p>
    <div className="table-wrap"><table><thead><tr><th>Execution</th><th>Checker</th><th>Published events</th><th>Published checker</th></tr></thead>
      <tbody>{Object.entries(result.executions).map(([key, r]) => <tr key={key}><th>{key}</th><td>{r.check.status}</td><td>{r.hash_match === null ? "New execution" : r.hash_match ? "Exact SHA-256 match" : "MISMATCH"}</td><td>{r.check_match === null ? "—" : r.check_match ? "Matches" : "MISMATCH"}</td></tr>)}</tbody></table></div>
    <dl className="lab-fingerprints"><dt>Browser build</dt><dd>{result.build_id}</dd><dt>Reference epoch</dt><dd>{manifest.reference_epoch}</dd><dt>Workload</dt><dd>{result.workload_digest}</dd><dt>Models</dt><dd>{Object.entries(result.receipt.models).map(([role, m]) => <div key={role}>{role}: {m.model_id}</div>)}</dd></dl>
    <p className="axis-note">Loading / fresh instance setup {result.loading_ms.toFixed(1)} ms · simulation {result.simulation_ms.toFixed(1)} ms · checking / timelines {result.checking_ms.toFixed(1)} ms. Total Worker time {result.elapsed_ms.toFixed(1)} ms.</p>
    <p><a href={manifest.runtime_source.url} download>Adapted Verilator runtime source & third-party licenses</a> · The browser runtime forces one context thread and uses Verilator's existing non-affinity branches. Native RTL and driver sources are unchanged.</p>
    <p>The receipt includes the exact workload, options, module and model fingerprints, event digests, and checker outcomes. With the matching RIFT checkout, independently reproduce it using the native runners and original Python checker:</p>
    <pre className="lab-command">python3.12 -m rift browser-verify --receipt receipt.json</pre>
    <details><summary>Raw receipt</summary><pre className="lab-receipt">{JSON.stringify(result.receipt, null, 2)}</pre></details>
  </details>;
}

export default function BrowserLab({ epoch, intent, onSandbox }: { epoch: string; intent: BrowserIntent; onSandbox: (preset: string) => void }) {
  const [runner] = useState(() => new BrowserRunner());
  const [manifest, setManifest] = useState<BrowserManifest | null>(null);
  const [records, setRecords] = useState<ReplayRecord[]>([]), [selected, setSelected] = useState(intent.preset ?? "pattern-m");
  const [workload, setWorkload] = useState<Workload | null>(null), [revision, setRevision] = useState(0);
  const [result, setResult] = useState<RunResult | null>(null), [before, setBefore] = useState<RunResult | null>(null);
  const [busy, setBusy] = useState(true), [status, setStatus] = useState("Loading verified execution inputs…"), [error, setError] = useState("");
  const [editing, setEditing] = useState(false), [dirty, setDirty] = useState(false), [spread, setSpread] = useState(false);
  const token = useRef(0), mounted = useRef(true);
  const sandbox = intent.mode === "sandbox";
  async function run(m: BrowserManifest, w: Workload, record?: ReplayRecord, baseline = false) {
    const current = ++token.current;
    setBusy(true); setError(""); setResult(null); setStatus("Preparing execution…");
    try {
      const next = await runner.run(m, w, message => { if (mounted.current && token.current === current) setStatus(message); }, record);
      if (!mounted.current || token.current !== current) return;
      setResult(next); if (baseline) setBefore(next);
      const mismatch = Object.values(next.executions).some(e => e.hash_match === false || e.check_match === false);
      const invalid = ["rtl-A", "rtl-B"].some(k => !next.executions[k].check.functional_valid);
      setStatus(mismatch ? "Replay differs from the published evidence. Inspect the details." : invalid ? "Execution finished. Reference validation failed; comparative performance is withheld." : "Execution complete. Both RTL event streams passed the browser checker.");
    } catch (e) {
      if (!mounted.current || token.current !== current) return;
      if ((e as Error).name === "AbortError") setStatus("Execution cancelled. Ready to run again.");
      else { setError((e as Error).message); setStatus("Execution could not complete."); }
    } finally { if (mounted.current && token.current === current) setBusy(false); }
  }
  useEffect(() => {
    mounted.current = true;
    let active = true;
    (async () => {
      const m = await loadManifest(epoch), curated = await loadRecords(m, "curated");
      const grid = intent.preset?.startsWith("map-") ? await loadRecords(m, "map") : [];
      if (!active) return;
      const all = [...curated, ...grid], r = all.find(x => x.id === (intent.preset ?? "pattern-m"));
      if (!r) throw new Error("This workload is unavailable in the current browser release.");
      setManifest(m); setRecords(all); setSelected(r.id); setWorkload(r.workload);
      await run(m, r.workload, sandbox ? undefined : r, sandbox && r.id === "pattern-m");
    })().catch(e => { if (active) { setError((e as Error).message); setBusy(false); setStatus("Browser execution unavailable."); } });
    return () => { active = false; mounted.current = false; ++token.current; runner.cancel(); };
    // A new intent mounts a new lab; each owns and disposes its Worker.
  }, [epoch, intent.preset, runner, sandbox]);
  const cancel = () => { ++token.current; runner.cancel(); setBusy(false); setStatus("Execution cancelled. Ready to run again."); };
  const change = (w: Workload) => { setWorkload(w); setRevision(v => v + 1); setDirty(false); setResult(null); setStatus("Workload changed. Run to measure it."); setError(""); };
  const choose = (id: string) => {
    const r = records.find(x => x.id === id); if (!r) return;
    setSelected(id); setSpread(false); setBefore(null); change(r.workload);
  };
  const reset = () => { const r = records.find(x => x.id === (sandbox ? "pattern-m" : intent.preset)); if (!r) return; choose(r.id); setEditing(false); };
  const download = () => {
    if (!result) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(result.receipt, null, 2) + "\n"], { type: "application/json" }));
    const a = document.createElement("a"); a.href = url; a.download = `rift-receipt-${result.workload_digest.slice(7, 19)}.json`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const valid = result && ["rtl-A", "rtl-B"].every(k => result.executions[k].check.functional_valid);
  const count = workload ? compile(workload).reduce((n, ops) => n + ops.length, 0) : 0;
  return <div className="browser-lab">
    <h2>{sandbox ? "Can you change the winner?" : "Reproduce the published result"}</h2>
    <p className="lab-intro">{sandbox ? "Keep every read. Move the streams between initiators. Run both hardware designs and see whether the faster one changes." : "The same RTL and driver execute on your device. Published event matching and functional validity are checked separately."}</p>
    {workload ? <>
      <div className="lab-toolbar">
        <label>Starting workload<select aria-label="Starting workload" disabled={busy} value={selected} onChange={e => choose(e.target.value)}>{records.map(r => <option key={r.id} value={r.id}>{r.title}</option>)}</select></label>
        <span className="lab-work-count">{count} reads · 8 initiators · 16 KiB memory</span>
      </div>
      <div className="actions lab-actions">
        {sandbox && selected === "pattern-m" ? <button className="btn" disabled={busy || spread || dirty || editing} onClick={() => { change(spreadTraffic(records.find(r => r.id === "pattern-m")!.workload)); setSpread(true); }}>Spread the same traffic</button> : null}
        <button className="btn primary" disabled={busy || dirty || !manifest} onClick={() => { if (manifest) void run(manifest, workload, sandbox ? undefined : records.find(r => r.id === selected), sandbox && canonical(workload) === canonical(records.find(r => r.id === "pattern-m")?.workload)); }}>{busy ? "Running…" : "Run"}</button>
        {busy ? <button className="btn" onClick={cancel}>Cancel</button> : null}
        <button className="text-button" disabled={busy} onClick={reset}>Reset</button>
        {!sandbox ? <button className="text-button" onClick={() => onSandbox(selected)}>Experiment with this workload →</button> : null}
      </div>
      {sandbox ? <>
        <details className="lab-details"><summary>What changes, and what stays constant?</summary><p>The guided permutation assigns original streams 0, 4, 1, 5, 2, 6, 3, 7 to destination initiators 0 through 7. Each complete stream keeps its addresses, operation order, release dependencies, and gaps. The memory contents and total work stay fixed. Shared routes change because the initiator assignments change.</p><p>The advanced editor changes the workload itself. All sandbox runs use the clean reference with a 4,096-cycle simulation limit. Published negative controls retain their original fault options in replay mode.</p></details>
        <details className="lab-details" open={editing} onToggle={e => setEditing(e.currentTarget.open)}><summary>Edit workload</summary>
          {editing || dirty ? <Suspense fallback={<p>Loading editor…</p>}><fieldset className="editor-boundary" disabled={busy}><WorkloadEditor key={revision} workload={workload} onApply={w => { change(w); setSpread(false); setBefore(null); }} onDirty={setDirty} /></fieldset></Suspense> : null}
        </details>
      </> : null}
    </> : null}
    <p className={`lab-status${busy ? " busy" : ""}`} role="status" aria-live="polite">{status}{dirty ? " Apply or discard the pending edits first." : ""}</p>
    {error ? <p className="err-box" role="alert">{error} The recorded investigation remains available above and in the other stages.</p> : null}
    {result && manifest ? <div className="lab-result">
      {valid ? <div className="lab-outcome"><span className="eyebrow">MEASURED RESULT</span><h3>{result.verdicts.parent.rtl_margin_met ? `${result.verdicts.parent.rtl_best === "A" ? "Crossbar" : "Butterfly"} finishes first` : "The designs are too close to call"}</h3><p>Original model {verdict(result.verdicts.parent.verdict)}. Repaired model {verdict(result.verdicts.repaired.verdict)}.</p></div> : <div className="integrity">Reference validation failed. Matching a published invalid event stream does not make it valid.</div>}
      <ResultTable before={before} result={result} />
      <LiveRace result={result} />
      <div className="actions"><button className="btn compact" onClick={download}>Download experiment receipt</button><span className="axis-note">Verify this exact experiment locally.</span></div>
      <Provenance result={result} manifest={manifest} />
    </div> : null}
    <p className="lab-scope">Live exploration is separate from the frozen map, discovery budget, and repair acceptance. The repaired model still has documented failures; explore them in Repair.</p>
  </div>;
}
