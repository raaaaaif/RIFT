import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { api } from "./api";
import type { CaseSummary, CaseView, ProjectRecord, Specimens } from "./types";
import { epochState, verdictLabel, wording } from "./logic";
import { Ctx, type UiCtx } from "./components/common";
import { DecisionView } from "./components/Decision";
import { WorkloadView_ } from "./components/Workload";
import { DifferenceView } from "./components/Difference";
import { RepairView } from "./components/Repair";
import { EvidenceView } from "./components/Evidence";
import { Inspector, type InspectorTab } from "./components/Inspector";
import { SpecimenView } from "./components/Specimen";

const STAGES = ["Decision", "Workload", "Difference", "Repair", "Evidence"] as const;
const SLUG = STAGES.map((s) => s.toLowerCase());

interface Route { kind: "case" | "specimen"; id: string | null; stage: number; op: string | null; epoch: string | null }

function parseHash(): Route {
  const h = window.location.hash.replace(/^#\/?/, "");
  const [path, query] = h.split("?");
  const parts = path.split("/").filter(Boolean);
  const q = new URLSearchParams(query ?? "");
  if (parts[0] === "specimen") return { kind: "specimen", id: parts[1] ?? null, stage: 0, op: null, epoch: null };
  const stage = Math.max(0, SLUG.indexOf(parts[2] ?? "decision"));
  return { kind: "case", id: parts[1] ?? null, stage, op: q.get("op"), epoch: q.get("epoch") };
}

function hashFor(r: Route): string {
  if (r.kind === "specimen") return `#/specimen/${r.id ?? ""}`;
  const q = new URLSearchParams();
  if (r.op) q.set("op", r.op);
  if (r.epoch) q.set("epoch", r.epoch);
  const qs = q.toString();
  return `#/case/${r.id ?? ""}/${SLUG[r.stage]}${qs ? `?${qs}` : ""}`;
}

export default function App() {
  const [route, setRoute] = useState<Route>(parseHash);
  const [cases, setCases] = useState<CaseSummary[] | null>(null);
  const [runEnabled, setRunEnabled] = useState(false);
  const [cv, setCv] = useState<CaseView | null>(null);
  const [rec, setRec] = useState<ProjectRecord | null>(null);
  const [specimens, setSpecimens] = useState<Specimens | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<InspectorTab>("overview");
  const [term, setTerm] = useState<string | null>(null);
  const [help, setHelp] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [transport, setTransport] = useState<"live" | "static">("static");
  const [announce, setAnnounce] = useState("");
  const navRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const requestSeq = useRef(0);

  useEffect(() => {
    const on = () => setRoute(parseHash());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  useEffect(() => {
    api.mode().then(setTransport);
    api.cases().then((r) => { setCases(r.cases); setRunEnabled(r.run_controls_enabled); }).catch((e) => setErr(String(e.message)));
    api.project().then(setRec).catch(() => setRec(null));
    api.specimens().then(setSpecimens).catch(() => setSpecimens(null));
  }, []);
  // default case
  useEffect(() => {
    if (route.kind === "case" && !route.id && cases?.length) {
      window.location.replace(hashFor({ ...route, id: cases[0].case_id }));
    }
  }, [route, cases]);
  // load case view; discard stale responses from rapid case changes
  useEffect(() => {
    if (route.kind !== "case" || !route.id) return;
    const seq = ++requestSeq.current;
    setCv((prev) => (prev && prev.case_id === route.id ? prev : null));
    api.caseView(route.id).then((v) => { if (seq === requestSeq.current) { setCv(v); setErr(null); } })
      .catch((e) => { if (seq === requestSeq.current) setErr(String(e.message)); });
  }, [route.kind, route.id]);

  const navigate = useCallback((patch: Partial<Route>) => {
    const next = { ...route, ...patch };
    window.location.hash = hashFor(next);
  }, [route]);

  const gotoStage = useCallback((n: number, focusHeading = true) => {
    setTerm(null);
    navigate({ stage: n });
    setAnnounce(`${STAGES[n]} view.`);
    if (focusHeading) window.setTimeout(() => document.getElementById("stage-heading")?.focus(), 30);
  }, [navigate]);

  const ui: UiCtx = useMemo(() => ({
    openTerm: (k) => { setTerm(k); setDrawer(true); setAnnounce("Explanation opened in the evidence inspector."); window.setTimeout(() => document.getElementById("inspector")?.focus(), 20); },
    inspect: (t) => { setTab(t); setTerm(null); setDrawer(true); window.setTimeout(() => document.getElementById("inspector")?.focus(), 20); setAnnounce(`Inspector: ${t}.`); },
    gotoStage,
    selectOp: (op) => { navigate({ op }); if (op) setAnnounce(`Selected ${op}.`); },
    op: route.op,
  }), [gotoStage, navigate, route.op]);

  const onNavKey = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    let n = i;
    if (e.key === "ArrowRight") n = (i + 1) % STAGES.length; else if (e.key === "ArrowLeft") n = (i + STAGES.length - 1) % STAGES.length;
    else if (e.key === "Home") n = 0; else if (e.key === "End") n = STAGES.length - 1; else return;
    e.preventDefault();
    gotoStage(n, false);
    navRefs.current[n]?.focus();
  };

  const changeCase = (value: string) => {
    setTerm(null); setTab("overview"); setHelp(false);
    if (value.startsWith("specimen:")) window.location.hash = hashFor({ kind: "specimen", id: value.slice(9), stage: 0, op: null, epoch: null });
    else window.location.hash = hashFor({ kind: "case", id: value, stage: 0, op: null, epoch: null });
  };

  const isSpecimen = route.kind === "specimen";
  const historical = !!(cv && route.epoch && route.epoch !== cv.reference_epoch);
  const groups = useMemo(() => {
    const g: Record<string, CaseSummary[]> = {};
    for (const c of cases ?? []) (g[c.group] = g[c.group] ?? []).push(c);
    return g;
  }, [cases]);

  const wd = cv ? wording(cv) : null;
  return (
    <Ctx.Provider value={ui}>
      <a className="skip" href="#stage-heading">Skip to investigation</a>
      {isSpecimen ? (
        <div className="evidence-band specimen"><strong>Interface specimen · Illustrative data · No RTL executed</strong><span className="mono">example/ namespace</span></div>
      ) : historical ? (
        <div className="evidence-band historical" role="alert"><strong>Historical link: reference epoch {route.epoch} differs from this case's epoch {cv?.reference_epoch}.</strong><span className="mono">no acceptance transferred</span></div>
      ) : (
        <div className="evidence-band"><strong>Executed evidence · pinned RTL reference (Verilator) · independent evaluator</strong><span className="mono">{cv ? `reference epoch ${cv.reference_epoch} · ${epochState(cv)}` : "loading"}</span></div>
      )}
      <div className="shell">
        <header className="topbar">
          <div className="brand">
            <svg viewBox="0 0 30 32" width="27" height="29" aria-hidden="true"><path d="M2 29V3h12l7 7-7 7H7m6 0 14 12" fill="none" stroke="#006D77" strokeWidth="3" /><path d="M23 3v9" fill="none" stroke="#18343F" strokeWidth="2" /></svg>
            <div className="wordmark">RIFT</div><div className="brand-line" /><div className="brand-sub">Chip-design decisions<br />you can inspect.</div>
          </div>
          <div className="case-picker">
            <label htmlFor="case-select">INVESTIGATION</label>
            <select id="case-select" value={isSpecimen ? `specimen:${route.id}` : route.id ?? ""} onChange={(e) => changeCase(e.target.value)}>
              {Object.entries(groups).map(([g, cs]) => (
                <optgroup key={g} label={g}>{cs.map((c) => <option key={c.case_id} value={c.case_id}>{c.short} — {verdictLabel(c.verdict)}</option>)}</optgroup>
              ))}
              {specimens ? <optgroup label="Illustrative specimens (example data, not executed)">{specimens.fixtures.map((f) => <option key={f.id} value={`specimen:${f.id}`}>{f.label}</option>)}</optgroup> : null}
            </select>
          </div>
        </header>
        {err ? <div className="err-box" role="alert">{err}</div> : null}
        {isSpecimen ? (
          specimens ? <main className="main" id="main"><SpecimenView data={specimens} id={route.id ?? specimens.fixtures[0].id} onOpenCase={(id) => changeCase(id)} /></main> : <div className="loading">Loading specimens…</div>
        ) : (
          <>
            <div className="run-line">
              <div className="context">
                <span className="context-title">Interconnect / architecture comparison</span><span className="dot-separator">·</span>
                <span className="mono">{cv?.case_id ?? route.id}</span>
                {wd ? <span className={`tag ${wd.tone === "neutral" ? "" : wd.tone}`}>{wd.tag}</span> : null}
                {cv ? <span className="tag">{cv.case_provenance === "SUPPLIED_CALIBRATION" ? "Supplied calibration" : cv.case_provenance === "AUTHORED_DEFECT" ? "Authored defect" : cv.case_provenance}</span> : null}
              </div>
              <div className="run-actions">
                <button className="text-button" onClick={() => setHelp((h) => !h)} aria-expanded={help}>How to read this</button>
                <button className="text-button" onClick={() => (drawer ? setDrawer(false) : ui.inspect("overview"))} aria-expanded={drawer} aria-controls="inspector">{drawer ? "Close inspector" : "Open inspector"} <span aria-hidden="true">{drawer ? "×" : "↗"}</span></button>
              </div>
            </div>
            <nav className="nav" aria-label="Investigation stages">
              {STAGES.map((s, i) => (
                <button key={s} ref={(el) => { navRefs.current[i] = el; }} aria-current={i === route.stage ? "step" : undefined} onClick={() => gotoStage(i)} onKeyDown={(e) => onNavKey(e, i)} aria-label={`${i + 1}. ${s}`}>
                  <span className="step-no" aria-hidden="true">{String(i + 1).padStart(2, "0")}</span><span>{s}</span>
                </button>
              ))}
            </nav>
            <div className="nav-select"><label className="screenreader" htmlFor="stage-select">Stage</label>
              <select id="stage-select" value={route.stage} onChange={(e) => gotoStage(Number(e.target.value))}>{STAGES.map((s, i) => <option key={s} value={i}>{i + 1}. {s}</option>)}</select></div>
            <div className={`workspace ${drawer ? "drawer-open" : "drawer-closed"}`}>
              <main className="main" id="main" aria-labelledby="stage-heading">
                {help ? (
                  <div className="help-panel" role="note">
                    <strong>How to read this investigation</strong>
                    <p>An interconnect moves requests from computing units to memory. RIFT checks whether a fast performance model chooses the right design by simulating the hardware description (RTL).</p>
                    <ol>
                      <li><b>Decision</b>: what the fast model recommends (dashed bars) and what the RTL reference simulation shows (solid bars), on the same scale.</li>
                      <li><b>Workload</b>: the exact logical program both designs ran, and where a request travels.</li>
                      <li><b>Difference</b>: recorded cycles for every operation, and the mechanism notes with their evidence.</li>
                      <li><b>Repair</b>: the proposed model change, and whether a separate verifier accepted it on held-out data.</li>
                      <li><b>Evidence</b>: every artifact, check, lock and command needed to reproduce the result.</li>
                    </ol>
                    <button className="text-button" onClick={() => setHelp(false)}>Dismiss</button>
                  </div>
                ) : null}
                {!cv ? <div className="loading" role="status">Loading case {route.id ?? ""}…</div> :
                  route.stage === 0 ? <DecisionView cv={cv} /> :
                  route.stage === 1 ? <WorkloadView_ cv={cv} /> :
                  route.stage === 2 ? <DifferenceView cv={cv} /> :
                  route.stage === 3 ? <RepairView cv={cv} controls={cv.repair_controls ?? []} /> :
                  <EvidenceView cv={cv} rec={rec} runEnabled={runEnabled} />}
              </main>
              {drawer ? <Inspector cv={cv} tab={tab} setTab={setTab} term={term} clearTerm={() => setTerm(null)} onClose={() => setDrawer(false)} /> : null}
            </div>
          </>
        )}
        <footer className="footer"><span>RIFT · inspect the decision, its assumptions, and its evidence</span><span>{isSpecimen ? "Illustrative fixtures. No execution." : transport === "static" ? "Recorded evidence · optional browser execution" : `Local server · native replay ${runEnabled ? "enabled" : "off"}`}</span></footer>
      </div>
      <div className="screenreader" role="status" aria-live="polite">{announce}</div>
    </Ctx.Provider>
  );
}
