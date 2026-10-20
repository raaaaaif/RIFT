import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { CaseView, DiagnosticView, TraceSelection } from "../types";
import { bflyRoute } from "../logic";
import { buildTimeline, completedAt, type Timeline } from "../replay";
import { ButterflyFlow, CrossbarFlow } from "./Diagrams";

type View = "rtl" | "model";

function useRaceData(cv: CaseView) {
  const c = cv.comparison;
  const [data, setData] = useState<{ tl: Record<string, Timeline>; traces: Record<string, TraceSelection> } | null>(null);
  const [diag, setDiag] = useState<DiagnosticView | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setData(null);
    setErr(null);
    setDiag(null);
    const keys: [string, string][] = [];
    for (const d of c.admitted_order) {
      if (c.rtl_run_ids?.[d]) keys.push([`rtl-${d}`, c.rtl_run_ids[d]]);
      if (c.model_run_ids?.[d]) keys.push([`model-${d}`, c.model_run_ids[d]]);
    }
    Promise.all(keys.map(([k, id]) => api.trace(id).then((t) => [k, t] as const)))
      .then((pairs) => {
        if (!live) return;
        const traces = Object.fromEntries(pairs);
        setData({ traces, tl: Object.fromEntries(pairs.map(([k, t]) => [k, buildTimeline(t)])) });
      })
      .catch((e) => live && setErr(String(e.message ?? e)));
    if (cv.diagnostic_available) api.diagnostic(cv.case_id).then((d) => live && setDiag(d && d.valid ? d : null));
    else setDiag(null);
    return () => { live = false; };
  }, [c, cv.case_id, cv.diagnostic_available]);
  return { data, diag, err };
}

export function FinishLine({ rows, cycle, max }: { rows: { label: string; model?: number; rtl?: number; rtlLabel: string }[]; cycle: number; max: number }) {
  const ref = useRef<SVGSVGElement>(null);
  const [W, setW] = useState(1000);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(280, Math.round(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const left = W < 560 ? 76 : 150, right = 40, x = (c: number) => left + (c / Math.max(1, max)) * (W - left - right);
  const H = 34 + rows.length * 58;
  const ticks: number[] = [];
  const step = max > 120 ? 40 : max > 60 ? 20 : 10;
  for (let t = 0; t <= max; t += step) ticks.push(t);
  return (
    <svg ref={ref} viewBox={`0 0 ${W} ${H}`} className="finish" role="img" aria-label={rows.map((r) => `${r.label}: model predicts ${r.model ?? "n/a"}, RTL finishes at ${r.rtl ?? "n/a"}`).join(". ")}>
      {ticks.map((t) => <g key={t}><line x1={x(t)} y1={14} x2={x(t)} y2={H - 6} stroke="#EEF2F1" /><text x={x(t)} y={10} textAnchor="middle" fontSize={11} fill="#52636B">{t}</text></g>)}
      <line x1={x(cycle)} y1={14} x2={x(cycle)} y2={H - 4} stroke="#1255B8" strokeWidth={2} />
      {rows.map((r, i) => {
        const y = 44 + i * 58;
        return (
          <g key={r.label}>
            <text x={0} y={y + 5} fontSize={13} fontWeight={650} fill="#18343F">{r.label}</text>
            <line x1={x(0)} y1={y} x2={x(max)} y2={y} stroke="#DDE4E3" strokeWidth={6} strokeLinecap="round" />
            {r.rtl !== undefined ? <line x1={x(0)} y1={y} x2={x(Math.max(0, Math.min(cycle, r.rtl)))} y2={y} stroke="#006D77" strokeWidth={6} strokeLinecap="round" /> : null}
            {r.model !== undefined ? (
              <g><rect x={x(r.model) - 34} y={y - 24} width={68} height={17} rx={8.5} fill="#FFFFFF" stroke="#18343F" strokeDasharray="3 2" />
                <text x={x(r.model)} y={y - 12} textAnchor="middle" fontSize={11} fill="#18343F">model {r.model}</text>
                <line x1={x(r.model)} y1={y - 7} x2={x(r.model)} y2={y + 7} stroke="#18343F" strokeWidth={2} strokeDasharray="2 2" /></g>
            ) : null}
            {r.rtl !== undefined ? (
              <g><rect x={x(r.rtl) - 34} y={y + 8} width={68} height={17} rx={8.5} fill="#006D77" />
                <text x={x(r.rtl)} y={y + 20} textAnchor="middle" fontSize={11} fontWeight={650} fill="#FFFFFF">{r.rtlLabel} {r.rtl}</text></g>
            ) : <text x={x(0) + 8} y={y + 22} fontSize={11} fill="#A03432">reference invalid</text>}
          </g>
        );
      })}
    </svg>
  );
}

export function Race({ cv }: { cv: CaseView }) {
  const c = cv.comparison;
  const { data, diag, err } = useRaceData(cv);
  const [view, setView] = useState<View>("rtl");
  const [cycle, setCycle] = useState(4);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(6);
  const timer = useRef<number | null>(null);
  const cfgA = c.designs?.A?.config_id ?? "lic8x8";
  const cfgB = c.designs?.B?.config_id ?? "bfly4_8x16";
  const numA = cfgA.includes("2x2") ? 2 : 8;
  const banksA = cfgA === "lic8x8" ? 8 : 2, banksB = 16;
  const max = useMemo(() => {
    if (!data) return 40;
    return Math.max(...Object.values(data.tl).map((t) => t.finish), 8) + 1;
  }, [data]);

  useEffect(() => { setCycle(4); setPlaying(false); }, [cv.case_id]);
  useEffect(() => {
    if (!playing) return;
    timer.current = window.setInterval(() => {
      setCycle((x) => {
        if (x >= max) { setPlaying(false); return x; }
        return x + 1;
      });
    }, 1000 / speed);
    return () => { if (timer.current) window.clearInterval(timer.current); };
  }, [playing, speed, max]);

  const hot = useMemo(() => {
    const m = new Map<string, number[]>();
    if (!diag || view !== "rtl") return m;
    for (const o of diag.first_stage_outputs) {
      const cyc = o.cycles.find((x) => x.c === cycle);
      if (cyc && cyc.requesters.length) m.set(`${o.router}:${o.output}`, cyc.requesters);
    }
    return m;
  }, [diag, cycle, view]);

  if (err) return <div className="err-box">Replay unavailable: {err}</div>;
  if (!data) return <div className="race loading-panel" role="status">Loading recorded events…</div>;
  const tA = data.tl[`${view}-A`], tB = data.tl[`${view}-B`];
  const frame = (t: Timeline | undefined) => ({
    accepted: t?.accepted.get(cycle) ?? [],
    waiting: t?.waiting.get(cycle) ?? new Set<number>(),
    finished: new Set([...(t?.done.entries() ?? [])].filter(([, last]) => last < cycle).map(([m]) => m)),
  });
  const fA = frame(tA), fB = frame(tB);
  // In model view, show where the model lets two requests through one first-stage output.
  const impossible = new Map<string, number[]>();
  if (view === "model" && cfgB === "bfly4_8x16") {
    for (const a of fB.accepted) {
      const h = bflyRoute(8, 16, 4, a.m, a.bank)[0];
      const k = `${h.router}:${h.outPort}`;
      impossible.set(k, [...(impossible.get(k) ?? []), a.m]);
    }
  }
  const invalidB = c.rtl_status?.B && c.rtl_status.B !== "COMPLETED";
  const rows = c.admitted_order.map((d) => ({
    label: `Design ${d}`,
    model: data.tl[`model-${d}`]?.finish ? data.tl[`model-${d}`].finish - 3 : undefined,
    rtl: c.rtl_observations?.[d]?.status === "COMPLETED" || c.rtl_status?.[d] === "COMPLETED" ? (data.tl[`rtl-${d}`]?.finish ?? 0) - 3 : undefined,
    rtlLabel: "RTL",
  }));
  const activeCycle = cycle - 3;
  return (
    <section className="race" aria-labelledby="race-title">
      <div className="race-head">
        <div>
          <h2 id="race-title">Watch the recorded run</h2>
          <p>Every frame is one clock cycle of the actual {view === "rtl" ? "RTL simulation" : "fast-model execution"}. Teal routes were accepted this cycle; amber initiators are waiting.</p>
        </div>
        <div className="seg" role="group" aria-label="Which execution to replay">
          <button aria-pressed={view === "rtl"} onClick={() => setView("rtl")}>Hardware (RTL)</button>
          <button aria-pressed={view === "model"} onClick={() => setView("model")}>Model prediction</button>
        </div>
      </div>
      <div className="race-grid">
        {[{ d: "A", t: tA, f: fA }, { d: "B", t: tB, f: fB }].map(({ d, t, f }) => (
          <figure key={d} className="race-fig">
            <figcaption><strong>Design {d}</strong> <span>{d === "A" ? "Full crossbar · 8 banks" : "Radix-4 butterfly · 16 banks"}</span></figcaption>
            {d === "A" ? (
              <CrossbarFlow numIn={numA} numOut={banksA} accepted={f.accepted} waiting={f.waiting} finished={f.finished} label={`Design A ${view}`} />
            ) : invalidB && view === "rtl" ? (
              <div className="race-invalid">Reference run invalid · replay withheld</div>
            ) : (
              <ButterflyFlow numIn={8} numOut={banksB} accepted={f.accepted} waiting={f.waiting} finished={f.finished}
                hot={view === "rtl" ? hot : impossible} label={`Design B ${view}`} />
            )}
            <div className="race-meter">
              <div className="race-bar"><span style={{ width: `${t ? (100 * completedAt(t, cycle)) / Math.max(1, t.total) : 0}%` }} /></div>
              <span className="mono">{t ? completedAt(t, cycle) : 0} / {t?.total ?? 0} reads done</span>
            </div>
          </figure>
        ))}
      </div>
      <div className="race-controls">
        <button className="btn primary play" onClick={() => { if (cycle >= max) setCycle(4); setPlaying((p) => !p); }} aria-label={playing ? "Pause replay" : "Play recorded replay"}>
          {playing ? "❚❚ Pause" : cycle >= max ? "↺ Replay" : "▶ Replay recorded run"}
        </button>
        <button className="btn compact" onClick={() => { setPlaying(false); setCycle((x) => Math.max(4, x - 1)); }} aria-label="Previous cycle">◀</button>
        <button className="btn compact" onClick={() => { setPlaying(false); setCycle((x) => Math.min(max, x + 1)); }} aria-label="Next cycle">▶</button>
        <input type="range" min={4} max={max} value={cycle} onChange={(e) => { setPlaying(false); setCycle(Number(e.target.value)); }} aria-label="Cycle" className="scrub" />
        <span className="cycle-readout mono">cycle {activeCycle}</span>
        <label className="speed">speed <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}><option value={3}>slow</option><option value={6}>normal</option><option value={14}>fast</option></select></label>
      </div>
      <FinishLine rows={rows} cycle={activeCycle} max={max - 3 + 6} />
      <p className="race-note">
        {view === "rtl" ? <>Recorded execution replay of RTL runs {c.rtl_run_ids?.A?.slice(-6)} / {c.rtl_run_ids?.B?.slice(-6)} (boundary events).{diag ? <> Amber numbers on stage 1 are <b>measured</b> internal router conflicts from a diagnostic trace of the same RTL ({diag.diagnostic_run_id.slice(-6)}, same epoch, mapping validated).</> : null}</>
          : <>Model prediction rendered on the real topology. Amber numbers mark where the model let two or more requests through a single stage-1 router output in the same cycle, which the hardware cannot do.</>}
        {" "}Cycle numbers count from the first request release.
      </p>
    </section>
  );
}
