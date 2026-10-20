import type { ReactElement } from "react";
import type { DiagOutput, HeldoutRow, WorkloadView } from "../types";
import type { Timeline } from "../replay";
import { bflyRoute } from "../logic";

const T = { ink: "#18343F", sec: "#52636B", teal: "#006D77", tealSoft: "#CFE6E8", amber: "#8A5B00", amberFill: "#F2C36B", amberSoft: "#FFF4DA",
  red: "#A03432", redSoft: "#FCEBE8", rule: "#CCD6D7", faint: "#EEF2F1", inset: "#F1F4F1" };

/** Initiator x cycle grid: accepted (teal), waiting (amber), idle (blank). */
export function ContentionGrid({ tl, masters, maxCycle, title, emphasize = [], onPick }: {
  tl: Timeline; masters: number; maxCycle: number; title: string; emphasize?: number[]; onPick?: (op: string) => void;
}) {
  const span = maxCycle - 4 + 1;
  const left = 34, top = 18, cell = Math.max(5, Math.min(13, 860 / span)), rowH = 18;
  const W = left + span * cell + 8, H = top + masters * rowH + 6;
  const cells: ReactElement[] = [];
  for (let c = 4; c <= maxCycle; c++) {
    const acc = new Map((tl.accepted.get(c) ?? []).map((a) => [a.m, a]));
    const wait = tl.waiting.get(c);
    for (let m = 0; m < masters; m++) {
      const x = left + (c - 4) * cell, y = top + m * rowH;
      const a = acc.get(m);
      if (a) cells.push(<rect key={`${c}-${m}`} x={x + 0.5} y={y + 2} width={cell - 1.5} height={rowH - 5} rx={2} fill={T.teal}
        onClick={onPick ? () => onPick(a.op) : undefined} style={onPick ? { cursor: "pointer" } : undefined}><title>{a.op} accepted at cycle {c - 3}</title></rect>);
      else if (wait?.has(m)) cells.push(<rect key={`${c}-${m}`} x={x + 0.5} y={y + 2} width={cell - 1.5} height={rowH - 5} rx={2} fill={T.amberFill} opacity={0.85} />);
    }
  }
  const ticks = [];
  for (let c = 0; c <= span; c += span > 100 ? 20 : 10) ticks.push(c);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="grid-chart" role="img" aria-label={`${title}: per-initiator acceptances and waits by cycle`}>
      {ticks.map((t) => <g key={t}><line x1={left + t * cell} y1={top - 2} x2={left + t * cell} y2={H} stroke={T.faint} /><text x={left + t * cell} y={11} fontSize={9.5} fill={T.sec} textAnchor="middle">{t}</text></g>)}
      {Array.from({ length: masters }, (_, m) => (
        <g key={m}>
          {emphasize.includes(m) ? <rect x={0} y={top + m * rowH} width={W} height={rowH} fill="#E8F0FB" /> : null}
          <text x={left - 6} y={top + m * rowH + 12} fontSize={10.5} textAnchor="end" fill={emphasize.includes(m) ? "#1255B8" : T.sec} fontWeight={emphasize.includes(m) ? 700 : 400}>m{m}</text>
        </g>
      ))}
      {cells}
    </svg>
  );
}

/** Measured stage-1 router outputs x cycles, from the diagnostic trace. */
export function RouterHeatmap({ outputs, window, emphasize }: { outputs: DiagOutput[]; window: [number, number]; emphasize?: string }) {
  const rows = outputs.filter((o) => o.cycles.length);
  const span = window[1] - window[0] + 1;
  const left = 190, right = 150, top = 20, rowH = 30, cell = Math.max(5, Math.min(12, 700 / span));
  const W = left + span * cell + right, H = top + rows.length * rowH + 8;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="grid-chart" role="img" aria-label={`Measured stage-1 router outputs: ${rows.map((o) => `${o.label} contended in ${o.conflict_cycles} cycles`).join("; ")}`}>
      {Array.from({ length: Math.floor(span / 10) + 1 }, (_, i) => i * 10).map((t) => (
        <g key={t}><line x1={left + t * cell} y1={top - 3} x2={left + t * cell} y2={H} stroke={T.faint} /><text x={left + t * cell} y={12} fontSize={9.5} fill={T.sec} textAnchor="middle">{t}</text></g>
      ))}
      {rows.map((o, i) => {
        const y = top + i * rowH;
        const em = emphasize === `${o.router}:${o.output}`;
        return (
          <g key={`${o.router}-${o.output}`}>
            {em ? <rect x={0} y={y} width={W} height={rowH} fill="#E8F0FB" /> : null}
            <text x={0} y={y + 13} fontSize={11.5} fontWeight={650} fill={T.ink}>Router {o.router} → output {o.output}</text>
            <text x={0} y={y + 25} fontSize={9.5} fill={T.sec}>banks {o.banks[0]}–{o.banks[o.banks.length - 1]} · inputs {o.inputs.map((m) => `m${m}`).join(", ")}</text>
            {o.cycles.map((c) => {
              const x = left + (c.c - window[0]) * cell;
              const n = c.requesters.length;
              const fill = n >= 2 ? T.amberFill : n === 1 ? T.tealSoft : "#EEE";
              return <rect key={c.c} x={x + 0.5} y={y + 5} width={cell - 1.5} height={rowH - 11} rx={2} fill={fill}><title>cycle {c.c - window[0] + 1}: {n} requester{n === 1 ? "" : "s"} ({c.requesters.map((m) => `m${m}`).join(", ")}); {c.winner !== null ? `m${c.winner} won` : "none passed"}</title></rect>;
            })}
            <text x={left + span * cell + 12} y={y + 13} fontSize={11.5} fontWeight={650} fill={o.conflict_cycles ? T.amber : T.teal}>{o.conflict_cycles} contended</text>
            <text x={left + span * cell + 12} y={y + 25} fontSize={9.5} fill={T.sec}>{o.requests_passed} requests passed</text>
          </g>
        );
      })}
    </svg>
  );
}

export const ARM_STYLE: Record<string, { label: string; color: string; dash?: string; width: number }> = {
  RIFT_decision_directed: { label: "Decision-directed (RIFT)", color: T.teal, width: 3 },
  B2_evolutionary: { label: "Evolutionary", color: T.ink, width: 2 },
  B2_legal_random: { label: "Legal random", color: T.sec, dash: "5 3", width: 2 },
  B5_error_directed: { label: "Error-directed", color: "#8A5B00", dash: "2 3", width: 2 },
  B1_public_sweeps: { label: "Public sweeps", color: "#9AA8AD", dash: "1 3", width: 2 },
  B3_bounded_smt: { label: "Bounded SMT", color: "#A03432", dash: "6 2 1 2", width: 1.6 },
};

export function DiscoveryCurves({ curves, cases }: { curves: Record<string, Record<string, [number, number][]>>; cases: { id: string; title: string }[] }) {
  const ymax = Math.max(1, ...Object.values(curves).flatMap((a) => Object.values(a).map((pts) => pts[pts.length - 1][1])));
  const w = 250, h = 150, l = 30, b = 24, t = 26;
  return (
    <div className="curves">
      <div className="curve-legend">{Object.entries(ARM_STYLE).map(([k, s]) => (
        <span key={k}><svg width="26" height="10" aria-hidden="true"><line x1="0" y1="5" x2="26" y2="5" stroke={s.color} strokeWidth={s.width} strokeDasharray={s.dash} /></svg>{s.label}</span>
      ))}</div>
      <div className="curve-grid">
        {cases.map((cs) => {
          const arms = curves[cs.id] ?? {};
          const x = (v: number) => l + (v / 64) * (w - l - 8), y = (v: number) => h - b - (v / ymax) * (h - b - t);
          return (
            <figure key={cs.id} className="curve-fig">
              <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={`${cs.title}: ${Object.entries(arms).map(([a, p]) => `${ARM_STYLE[a]?.label ?? a} ${p[p.length - 1][1]}`).join(", ")}`}>
                <text x={0} y={13} fontSize={11.5} fontWeight={650} fill={T.ink}>{cs.title}</text>
                {[0, Math.round(ymax / 2), ymax].map((v) => <g key={v}><line x1={l} y1={y(v)} x2={w - 8} y2={y(v)} stroke={T.faint} /><text x={l - 5} y={y(v) + 3} fontSize={9} textAnchor="end" fill={T.sec}>{v}</text></g>)}
                {[0, 32, 64].map((v) => <text key={v} x={x(v)} y={h - 8} fontSize={9} textAnchor="middle" fill={T.sec}>{v}</text>)}
                {Object.entries(arms).map(([a, pts]) => {
                  const s = ARM_STYLE[a];
                  if (!s) return null;
                  const d = pts.map(([px, py], i) => `${i ? "L" : "M"}${x(px)} ${y(py)}`).join("");
                  return <path key={a} d={d} fill="none" stroke={s.color} strokeWidth={s.width} strokeDasharray={s.dash} strokeLinejoin="round" />;
                })}
              </svg>
            </figure>
          );
        })}
      </div>
      <p className="axis-note">x: RTL executions spent (budget 64) · y: credited strict reversals found</p>
    </div>
  );
}

export function DotPlot({ rows }: { rows: HeldoutRow[] }) {
  const fams = [...new Set(rows.map((r) => r.family_id))];
  const dot = (v: string, reg: number) => (v === "VALID_COUNTEREXAMPLE" ? { fill: T.red, stroke: T.red, r: 6.5 } : reg > 0 ? { fill: T.amberFill, stroke: T.amber, r: 5.5 } : { fill: "#fff", stroke: T.teal, r: 5 });
  return (
    <div className="dotplot">
      {fams.map((f) => {
        const fr = rows.filter((r) => r.family_id === f);
        return (
          <div className="dot-fam" key={f}>
            <div className="dot-label"><strong>{f.replace(/^H\d_/, "").replaceAll("_", " ")}</strong><span>{fr[0]?.config_B}</span></div>
            {(["parent", "candidate"] as const).map((who) => (
              <div className="dot-row" key={who}>
                <span className="dot-who">{who === "parent" ? "before" : "after"}</span>
                <svg viewBox={`0 0 ${fr.length * 18 + 6} 16`} width={fr.length * 18 + 6} height={16} role="img" aria-label={`${f} ${who}: ${fr.filter((r) => r[who].verdict === "VALID_COUNTEREXAMPLE").length} reversals`}>
                  {fr.map((r, i) => { const s = dot(r[who].verdict, r[who].regret?.decimal ?? 0); return <circle key={i} cx={9 + i * 18} cy={8} r={s.r} fill={s.fill} stroke={s.stroke} strokeWidth={1.6}><title>seed {r.seed}: {r[who].verdict}</title></circle>; })}
                </svg>
              </div>
            ))}
          </div>
        );
      })}
      <div className="dot-legend"><span><i className="d ok" />right choice</span><span><i className="d amber" />wrong under tie/small margin</span><span><i className="d red" />strict reversal</span></div>
    </div>
  );
}

export function BenchBars({ rows, target }: { rows: { label: string; rtl: number; model: number }[]; target: number }) {
  const max = Math.max(...rows.flatMap((r) => [r.rtl, r.model]));
  return (
    <div className="bench">
      {rows.map((r) => {
        const sp = r.rtl / r.model;
        return (
          <div className="bench-row" key={r.label}>
            <div className="bench-label"><strong>{r.label}</strong><span className={sp >= target ? "ok" : "bad"}>{sp.toFixed(1)}× {sp >= target ? "≥" : "<"} {target}×</span></div>
            <div className="bench-bars">
              <div><span style={{ width: `${(100 * r.rtl) / max}%` }} className="b-rtl" /><em>Verilator {(r.rtl * 1000).toFixed(1)} ms</em></div>
              <div><span style={{ width: `${(100 * r.model) / max}%` }} className="b-model" /><em>model {(r.model * 1000).toFixed(1)} ms</em></div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** Program as horizontal strips: one segment per run of identical reads. */
export function ProgramStrips({ w, selected, onPick, conflictsA }: { w: WorkloadView; selected?: string | null; onPick: (op: string) => void; conflictsA: Set<number> }) {
  const maxOps = Math.max(...w.initiators.map((i) => i.operations), 1);
  return (
    <div className="strips" role="list" aria-label="Logical program per initiator">
      {w.initiators.map((init) => (
        <div className="strip" role="listitem" key={init.master}>
          <span className="strip-m mono">m{init.master}</span>
          <div className="strip-bar">
            {init.runs.length === 0 ? <span className="strip-empty">no operations</span> : init.runs.map((r, i) => {
              const op = `m${init.master}:op${String(r.first_index).padStart(4, "0")}`;
              const sel = selected && selected.startsWith(`m${init.master}:`) && Number(selected.split("op")[1]) >= r.first_index && Number(selected.split("op")[1]) <= r.last_index;
              const conflict = conflictsA.has(r.mapping.A?.bank ?? -1);
              return (
                <button key={i} className={`seg-run${sel ? " sel" : ""}${conflict ? " conflict" : ""}`} style={{ flexGrow: r.count, flexBasis: 0, maxWidth: `${(100 * r.count) / maxOps}%` }}
                  onClick={() => onPick(op)} aria-label={`m${init.master}: ${r.count} reads of word ${r.word}`} title={`${r.count}× word ${r.word} · A bank ${r.mapping.A?.bank} · B bank ${r.mapping.B?.bank}${r.release !== "after_accept" ? " · after response" : ""}`}>
                  <span>{r.count}× w{r.word}</span>
                </button>
              );
            })}
          </div>
          <span className="strip-n mono">{init.operations}</span>
        </div>
      ))}
    </div>
  );
}

/** Which initiators target each bank, per design; shared banks highlighted. */
export function BankMap({ w, design, banks, group }: { w: WorkloadView; design: string; banks: number; group?: number }) {
  const who: number[][] = Array.from({ length: banks }, () => []);
  w.initiators.forEach((init) => init.runs.forEach((r) => { const b = r.mapping[design]?.bank; if (b !== undefined && !who[b].includes(init.master)) who[b].push(init.master); }));
  const cols = group ? banks / group : banks;
  return (
    <div className="bankmap" style={{ gridTemplateColumns: `repeat(${Math.min(banks, group ? group : 8)}, minmax(0,1fr))` }} aria-label={`Design ${design} bank usage`}>
      {who.map((ms, b) => (
        <div key={b} className={`bank-cell${ms.length >= 2 ? " shared" : ms.length ? " used" : ""}`} title={`bank ${b}: ${ms.map((m) => `m${m}`).join(", ") || "unused"}`}>
          <span className="bank-id">bank {b}</span>
          <span className="bank-who">{ms.length ? ms.map((m) => `m${m}`).join(" ") : "—"}</span>
        </div>
      ))}
      {void cols}
    </div>
  );
}

/** Bank-only model vs repaired shared-link model, drawn from the specifications. */
export function ModelDiagram({ links, title, added }: { links: number[][]; title: string; added: boolean }) {
  const W = 470, H = 300, top = 30, bottom = H - 16;
  const n = 8, banks = 16;
  const inY = (m: number) => top + ((m + 0.5) * (bottom - top)) / n;
  const bankY = (b: number) => top + ((b + 0.5) * (bottom - top)) / banks;
  const xIn = 34, xL = 200, xB = 400;
  const els: ReactElement[] = [];
  if (!links.length) {
    for (let m = 0; m < n; m++) for (let b = 0; b < banks; b += 3) els.push(<line key={`${m}-${b}`} x1={xIn + 22} y1={inY(m)} x2={xB} y2={bankY(b)} stroke={T.faint} />);
    els.push(<text key="lbl" x={(xIn + xB) / 2 + 10} y={H / 2} textAnchor="middle" fontSize={12} fill={T.sec}>only bank conflicts modelled</text>);
  } else {
    const [g, s] = links[0];
    const groups = n / g, classes = banks >> s;
    const boxH = (bottom - top) / groups;
    for (let gi = 0; gi < groups; gi++) {
      els.push(<rect key={`g${gi}`} x={xL - 40} y={top + gi * boxH + 3} width={80} height={boxH - 6} rx={8} fill={added ? "#EEF6F6" : "#FAFBFA"} stroke={added ? T.teal : T.rule} strokeWidth={added ? 1.6 : 1} />);
      for (let k = 0; k < Math.min(classes, 4); k++) {
        const ly = top + gi * boxH + 10 + (k * (boxH - 20)) / Math.max(1, Math.min(classes, 4) - 1);
        els.push(<circle key={`l${gi}${k}`} cx={xL + 40} cy={ly} r={3.5} fill={T.teal} />);
        for (let bb = k * (1 << s); bb < (k + 1) * (1 << s) && bb < banks; bb++) els.push(<line key={`lb${gi}${k}${bb}`} x1={xL + 40} y1={ly} x2={xB} y2={bankY(bb)} stroke="#D9E7E8" />);
      }
      for (let m = gi * g; m < (gi + 1) * g; m++) els.push(<line key={`im${m}`} x1={xIn + 22} y1={inY(m)} x2={xL - 40} y2={top + gi * boxH + boxH / 2} stroke={T.rule} />);
      els.push(<text key={`gt${gi}`} x={xL} y={top + gi * boxH + boxH / 2 + 4} textAnchor="middle" fontSize={10.5} fill={T.teal} fontWeight={650}>shared links</text>);
    }
  }
  return (
    <figure className="model-fig">
      <figcaption>{title}</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={title}>
        {els}
        {Array.from({ length: n }, (_, m) => <g key={m}><rect x={xIn - 22} y={inY(m) - 10} width={44} height={20} rx={5} fill="#fff" stroke={T.rule} /><text x={xIn} y={inY(m) + 4} textAnchor="middle" fontSize={10.5}>m{m}</text></g>)}
        {Array.from({ length: banks }, (_, b) => <g key={b}><rect x={xB} y={bankY(b) - 7} width={44} height={14} rx={3} fill={T.inset} stroke={T.rule} /><text x={xB + 22} y={bankY(b) + 3.5} textAnchor="middle" fontSize={9}>{b}</text></g>)}
      </svg>
    </figure>
  );
}

/** Butterfly first-stage sharing for one initiator pair (used in explanations). */
export function pairOf(m: number) { return bflyRoute(8, 16, 4, m, 0)[0].router; }
