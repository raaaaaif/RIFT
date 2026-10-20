import { useEffect, useState } from "react";
import { ButterflyFlow, CrossbarFlow } from "../components/Diagrams";
import { FinishLine } from "../components/Race";
import { completedAt } from "../replay";
import type { RunResult } from "./types";

export default function LiveRace({ result }: { result: RunResult }) {
  const [cycle, setCycle] = useState(4), [playing, setPlaying] = useState(false);
  const max = Math.max(...["A", "B"].map(d => result.executions[`rtl-${d}`].timeline?.finish ?? 4));
  useEffect(() => { setCycle(4); setPlaying(false); }, [result]);
  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => setCycle(c => { if (c >= max) { setPlaying(false); return c; } return c + 1; }), 1000 / 14);
    return () => clearInterval(timer);
  }, [playing, max]);
  return <div className="live-race" aria-label="Browser-generated RTL playback">
    <div className="race-grid">{["A", "B"].map(d => {
      const run = result.executions[`rtl-${d}`], tl = run.timeline;
      const frame = { accepted: tl?.accepted.get(cycle) ?? [], waiting: tl?.waiting.get(cycle) ?? new Set<number>(), finished: new Set([...(tl?.done ?? [])].filter(([, last]) => last < cycle).map(([m]) => m)), label: `Live design ${d}` };
      return <figure key={d} className="race-fig"><figcaption><strong>Design {d}</strong><span>{d === "A" ? "Crossbar · 8 banks" : "Butterfly · 16 banks"}</span></figcaption>
        {run.check.functional_valid && tl ? <>{d === "A" ? <CrossbarFlow numIn={8} numOut={8} {...frame} /> : <ButterflyFlow numIn={8} numOut={16} {...frame} />}
          <div className="race-meter"><div className="race-bar"><span style={{ width: `${100 * completedAt(tl, cycle) / Math.max(1, tl.total)}%` }} /></div><span className="mono">{completedAt(tl, cycle)} / {tl.total} reads done</span></div></> : <div className="race-invalid">{run.check.status} · performance playback withheld</div>}
      </figure>;
    })}</div>
    <div className="race-controls">
      <button className="btn compact" onClick={() => { if (cycle >= max) setCycle(4); setPlaying(v => !v); }}>{playing ? "Pause live playback" : "Play live result"}</button>
      <button className="btn compact" aria-label="Previous live cycle" onClick={() => { setPlaying(false); setCycle(c => Math.max(4, c - 1)); }}>◀</button>
      <button className="btn compact" aria-label="Next live cycle" onClick={() => { setPlaying(false); setCycle(c => Math.min(max, c + 1)); }}>▶</button>
      <input className="scrub" aria-label="Live cycle" type="range" min={4} max={max} value={cycle} onChange={e => { setPlaying(false); setCycle(Number(e.target.value)); }} />
      <span className="mono">cycle {cycle - 3}</span>
    </div>
    <FinishLine rows={["A", "B"].map(d => ({ label: `Design ${d}`, model: result.executions[`model-${d === "A" ? "A" : "parent"}`].check.makespan ?? undefined, rtl: result.executions[`rtl-${d}`].check.makespan ?? undefined, rtlLabel: "RTL" }))} cycle={cycle - 3} max={Math.max(8, max + 3)} />
    <p className="axis-note">Playback comes from the boundary events generated on this device. Internal router signals are not collected by the browser build.</p>
  </div>;
}
