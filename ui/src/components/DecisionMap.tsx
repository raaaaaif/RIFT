import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { api } from "../api";
import type { CaseView, DecisionMapView, MapCell, MapLandmark, MapModel } from "../types";
import { cellOutline, isolines, smooth, type Pt } from "../contour";

let requested: MapModel | null = null;
/** Ask the next mounted map to open on a given model (used by the Repair stage link). */
export function requestMapModel(m: MapModel) { requested = m; }

const C = {
  teal: "#006D77", tealSoft: "#B4D8DB", ink: "#18343F", inkSoft: "#B3C2C7", tie: "#E6ECEA",
  red: "#A03432", amber: "#8A5B00", amberSoft: "#FFF1D2", sec: "#52636B", rule: "#CCD6D7", paper: "#FBFCFA",
};
const MODEL_LABEL: Record<MapModel, string> = { parent: "Bank-only model", repaired: "Repaired model" };
const T = 12, R = 12, CS = 26;

const thr = (a: number, b: number) => Math.max(2, 0.02 * Math.min(a, b));
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
const pctOf = (f: [number, number]) => Math.round((100 * f[0]) / Math.max(1, f[1]));
function mix(a: string, b: string, t: number) {
  const p = (h: string) => [1, 3, 5].map((k) => parseInt(h.slice(k, k + 2), 16));
  const [x, y] = [p(a), p(b)];
  return `#${x.map((v, i) => Math.round(lerp(v, y[i], t)).toString(16).padStart(2, "0")).join("")}`;
}
const ease = (t: number) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2);
const reducedMotion = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

function useMap() {
  const [map, setMap] = useState<DecisionMapView | null | undefined>(undefined);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => { let live = true; api.map().then((m) => live && setMap(m)); return () => { live = false; }; }, [attempt]);
  return { map, retry: () => { setMap(undefined); setAttempt(n => n + 1); } };
}

/** Model tween 0 = audited bank-only model, 1 = repaired model. */
function useTween(target: number) {
  const [t, setT] = useState(target);
  const cur = useRef(target);
  useEffect(() => {
    if (reducedMotion()) { cur.current = target; setT(target); return; }
    const from = cur.current, start = performance.now(), dur = 560;
    let raf = 0;
    const step = (now: number) => {
      const k = Math.min(1, (now - start) / dur);
      cur.current = lerp(from, target, ease(k));
      setT(cur.current);
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target]);
  return t;
}

const path = (pts: readonly Pt[], px: (p: Pt) => [number, number]) => pts.map((p, k) => `${k ? "L" : "M"}${px(p).map((v) => v.toFixed(1)).join(" ")}`).join("");

function hwState(c: MapCell, a: string, b: string): "A" | "B" | "tie" {
  const ra = c.rtl[a], rb = c.rtl[b];
  if (ra == null || rb == null) return "tie";
  const d = ra - rb;
  return d <= -thr(ra, rb) ? "A" : d >= thr(ra, rb) ? "B" : "tie";
}

export function DecisionMap({ cv, onExplore }: { cv: CaseView; onExplore?: (id: string) => void }) {
  const { map, retry } = useMap();
  const [model, setModel] = useState<MapModel>(() => requested ?? "parent");
  const [view, setView] = useState<"wins" | "error">("wins");
  const [focus, setFocus] = useState<[number, number] | null>(null);
  const [landmarkFocus, setLandmarkFocus] = useState<string | null>(null);
  const [revealed, setRevealed] = useState(false);
  const ref = useRef<HTMLElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const [k, setK] = useState(1);
  const t = useTween(model === "repaired" ? 1 : 0);
  useLayoutEffect(() => {
    const el = boxRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([e]) => { const w = Math.min(600, e.contentRect.width); if (w > 0) setK(Math.round(Math.min(1.8, Math.max(1, 520 / w)) * 20) / 20); });
    ro.observe(el);
    return () => ro.disconnect();
  }, [map]);
  // Text, pins and margins keep their on-screen size when the square is drawn small.
  const L = Math.round(36 + 16 * k), B = Math.round(28 + 16 * k);

  useEffect(() => {
    if (requested && ref.current) { requested = null; window.setTimeout(() => ref.current?.scrollIntoView({ block: "start", behavior: reducedMotion() ? "auto" : "smooth" }), 60); }
  }, [map]);
  useEffect(() => {
    const el = ref.current;
    if (!el || revealed) return;
    if (reducedMotion() || typeof IntersectionObserver === "undefined") { setRevealed(true); return; }
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { setRevealed(true); io.disconnect(); } }, { threshold: 0.15 });
    io.observe(el);
    return () => io.disconnect();
  }, [map, revealed]);

  const geo = useMemo(() => {
    if (!map) return null;
    const nx = map.grid.x.length, ny = map.grid.y.length;
    const grid: (MapCell | null)[][] = Array.from({ length: nx }, () => Array(ny).fill(null));
    for (const c of map.cells) grid[c.i][c.j] = c;
    const W = L + nx * CS + R, H = T + ny * CS + B;
    const px = (p: Pt): [number, number] => [L + (p[0] + 0.5) * CS, T + (ny - 1 - p[1] + 0.5) * CS];
    const [a, b] = map.order;
    const edge = (p: Pt) => `${(L + p[0] * CS).toFixed(1)} ${(T + (ny - p[1]) * CS).toFixed(1)}`;
    const coast = cellOutline(grid.map((col) => col.map((c) => !!c && hwState(c, a, b) === "A"))).map(([p, q]) => `M${edge(p)}L${edge(q)}`).join("");
    const maxErr = Math.max(1, ...map.cells.flatMap((c) => (["parent", "repaired"] as const).map((m) => (c.model[m] == null || c.rtl[b] == null ? 0 : Math.abs(c.model[m]! - c.rtl[b]!)))));
    return { nx, ny, grid, W, H, px, a, b, coast, maxErr };
  }, [map, L, B]);

  const modelGeo = useMemo(() => {
    if (!geo) return null;
    const field = geo.grid.map((col) => col.map((c) => {
      const ma = c?.model.A, p = c?.model.parent, r = c?.model.repaired;
      if (ma == null || p == null || r == null) return Number.NaN;
      const mb = lerp(p, r, t);
      return (mb - ma) - thr(ma, mb);
    }));
    return { lines: isolines(field, 0).map((ln) => smooth(ln)), any: field.some((col) => col.some((v) => v > 0)) };
  }, [geo, t]);

  if (map === undefined) return <section className="panel dmap" ref={ref}><div className="loading">Loading the decision map…</div></section>;
  if (map === null) return <section className="panel dmap" ref={ref} aria-label="Decision map unavailable"><div className="panel-body"><p role="status">The recorded decision map could not load.</p><button className="btn compact" onClick={retry}>Retry decision map</button></div></section>;
  if (!map || !geo || !modelGeo) return null;
  if (map.integrity_error_count > 0) {
    return <section className="panel dmap" ref={ref}><div className="integrity" role="alert"><strong>Decision map blocked.</strong> {map.integrity_error_count} disagreements between the map record and its runs, for example: {map.integrity_errors[0]}</div></section>;
  }
  if (cv.comparison.models?.B?.model_id !== map.models.parent.model_id || !cv.comparison.rtl_costs) return null;

  const { nx, ny, grid, W, H, px, a, b } = geo;
  const s = map.summary;
  const cur = s[model];
  const here = map.landmarks.find((l) => l.case_id === cv.case_id) ?? null;
  const lmCell = (l: MapLandmark): [number, number] => [Math.round((l.x[0] / Math.max(1, l.x[1])) * (nx - 1)), Math.round((l.y[0] / Math.max(1, l.y[1])) * (ny - 1))];
  const worst = [...map.cells].filter((c) => c.verdict[model].verdict === "VALID_COUNTEREXAMPLE").sort((p, q) => (q.verdict[model].extra ?? 0) - (p.verdict[model].extra ?? 0))[0];
  const sel = focus ?? (here ? lmCell(here) : worst ? [worst.i, worst.j] as [number, number] : [Math.floor(nx / 2), Math.floor(ny / 2)] as [number, number]);
  const selCell = grid[sel[0]]?.[sel[1]] ?? null;
  const lmName = landmarkFocus ?? (focus ? null : here?.name ?? null);
  const selLandmark = lmName ? map.landmarks.find((l) => l.name === lmName) ?? null : null;
  const counter = (key: "strict_reversals" | "model_undecided_hardware_decisive") => Math.round(lerp(s.parent[key], s.repaired[key], t));
  const crossbarFaster = s.hardware.A_faster;
  const below = map.cells.filter((c) => c.x[0] * c.y[1] > c.y[0] * c.x[1]);
  const belowA = below.filter((c) => hwState(c, a, b) === "A").length;
  const maxYA = Math.max(0, ...map.cells.filter((c) => hwState(c, a, b) === "A").map((c) => pctOf(c.y)));
  const [aboveDiag, revTotal] = s.prediction_checks.parent_reversals_where_sharing_exceeds_collisions;
  const modelNeverCrossbar = !modelGeo.any;
  const parentCrossbar = map.cells.filter((c) => c.verdict.parent.model_margin_met && c.verdict.parent.choice === a).length;
  const pinLabel = (l: MapLandmark) => (l.case_id === cv.case_id ? "this case" : l.case_id.startsWith("pattern-") ? `pattern ${l.name}` : `${l.name} witness`);

  const fill = (c: MapCell) => {
    if (view === "error") {
      const p = c.model.parent, r = c.model.repaired, rb = c.rtl[b];
      if (p == null || r == null || rb == null) return C.tie;
      const e = Math.abs(lerp(p, r, t) - rb);
      return e < 0.5 ? C.paper : mix(C.amberSoft, C.amber, Math.min(1, e / geo.maxErr));
    }
    const st = hwState(c, a, b);
    if (st === "tie") return C.tie;
    const ra = c.rtl[a]!, rb = c.rtl[b]!;
    const rel = Math.min(1, Math.abs(ra - rb) / Math.min(ra, rb) / 0.35);
    return st === "A" ? mix(C.tealSoft, C.teal, 0.25 + 0.75 * rel) : mix(C.inkSoft, C.ink, 0.25 + 0.75 * rel);
  };
  const weight = (pred: (m: MapModel) => boolean) => (pred("parent") ? 1 - t : 0) + (pred("repaired") ? t : 0);
  const wrong = (c: MapCell) => weight((m) => c.verdict[m].verdict === "VALID_COUNTEREXAMPLE");
  const unsure = (c: MapCell) => weight((m) => c.verdict[m].verdict === "TIE_OR_SMALL_MARGIN" && !!c.verdict[m].rtl_margin_met);

  const fromPointer = (e: PointerEvent<SVGSVGElement>) => {
    const svg = e.currentTarget;
    const r = svg.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width) * W, y = ((e.clientY - r.top) / r.height) * H;
    const i = Math.floor((x - L) / CS), j = ny - 1 - Math.floor((y - T) / CS);
    if (i >= 0 && i < nx && j >= 0 && j < ny) { setFocus([i, j]); setLandmarkFocus(null); }
  };
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const d: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] };
    if (!d[e.key]) return;
    e.preventDefault();
    setLandmarkFocus(null);
    setFocus([Math.max(0, Math.min(nx - 1, sel[0] + d[e.key][0])), Math.max(0, Math.min(ny - 1, sel[1] + d[e.key][1]))]);
  };
  const openCase = (id: string) => { if (id !== cv.case_id) window.location.hash = `#/case/${id}/decision`; };

  const cellsSvg = [];
  for (let i = 0; i < nx; i++) {
    for (let j = 0; j < ny; j++) {
      const c = grid[i][j];
      if (!c) continue;
      const x = L + i * CS + 1, y = T + (ny - 1 - j) * CS + 1, w = wrong(c), u = unsure(c);
      cellsSvg.push(
        <g key={`${i}-${j}`} className="dm-cell" style={{ animationDelay: `${(i + (ny - 1 - j)) * 17}ms` }} data-i={i} data-j={j}
          data-state={c.verdict[model].verdict === "VALID_COUNTEREXAMPLE" ? "wrong" : c.verdict[model].verdict === "TIE_OR_SMALL_MARGIN" && c.verdict[model].rtl_margin_met ? "unsure" : "ok"}>
          <rect x={x} y={y} width={CS - 2} height={CS - 2} rx={3.5} fill={fill(c)} />
          {u > 0.01 ? <rect x={x} y={y} width={CS - 2} height={CS - 2} rx={3.5} fill="url(#dm-dots)" opacity={u} pointerEvents="none" /> : null}
          {w > 0.01 ? <g opacity={w} pointerEvents="none"><rect x={x} y={y} width={CS - 2} height={CS - 2} rx={3.5} fill="url(#dm-hatch)" /><rect x={x + 0.75} y={y + 0.75} width={CS - 3.5} height={CS - 3.5} rx={3} fill="none" stroke={C.red} strokeWidth={1.5} /></g> : null}
        </g>,
      );
    }
  }
  const [fx, fy] = px(sel as unknown as Pt);
  const ticks = [0, 0.25, 0.5, 0.75, 1];

  const readout = selLandmark ? <LandmarkReadout l={selLandmark} a={a} b={b} /> : selCell ? <><CellReadout c={selCell} a={a} b={b} model={model} />{onExplore ? <button className="text-button" onClick={() => onExplore(`map-${selCell.i}-${selCell.j}`)}>Experiment with this map workload →</button> : null}</> : null;
  const prediction = map.prediction_before_execution;

  return (
    <section className={`panel dmap${revealed ? " revealed" : ""}`} ref={ref} id="decision-map" aria-labelledby="dmap-h">
      <div className="panel-head">
        <div><h2 id="dmap-h">One workload is an anecdote. Here are {s.cells}.</h2>
          <p>Every square is a different workload, simulated on the real RTL for both chips. Colour shows which chip actually finished first.</p></div>
        <span className="stamp">MEASURED · {map.executor.distinct_rtl_executions} RTL RUNS</span>
      </div>
      <div className="panel-body dm-grid">
        <div className="dm-figure">
          <div className="dm-svg" ref={boxRef} tabIndex={0} role="group" onKeyDown={onKey}
            aria-label={`Decision map, ${s.cells} workloads. Arrow keys move between workloads; details are read out below the map.`}>
            <svg viewBox={`0 0 ${W} ${H}`} role="img" onPointerMove={fromPointer} onPointerDown={fromPointer}
              aria-label={`${MODEL_LABEL[model]}: wrong pick in ${cur.strict_reversals} of ${s.cells} workloads, undecided in ${cur.model_undecided_hardware_decisive} more where the hardware is decisive.`}>
              <defs>
                <pattern id="dm-hatch" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="2" height="5" fill={C.red} opacity=".85" /></pattern>
                <pattern id="dm-dots" width="5" height="5" patternUnits="userSpaceOnUse"><circle cx="2.5" cy="2.5" r="1.05" fill={C.amber} /></pattern>
              </defs>
              <rect x={L - 1} y={T - 1} width={nx * CS + 2} height={ny * CS + 2} rx={6} fill={C.paper} stroke={C.rule} />
              {cellsSvg}
              {view === "wins" && geo.coast ? <g className="dm-coast" pointerEvents="none"><path d={geo.coast} fill="none" stroke="#FFFFFF" strokeWidth={5} strokeLinecap="square" opacity={0.95} /><path d={geo.coast} fill="none" stroke={C.ink} strokeWidth={2} strokeLinecap="square" /></g> : null}
              {modelGeo.lines.map((ln, n) => <g key={`m${n}`} className="dm-model-line" pointerEvents="none"><path d={path(ln, px)} fill="none" stroke="#FFFFFF" strokeWidth={4.5} strokeLinejoin="round" opacity={0.85} /><path d={path(ln, px)} fill="none" stroke={C.amber} strokeWidth={2.2} strokeDasharray="6 4" strokeLinejoin="round" /></g>)}
              <line x1={L} x2={L + nx * CS} y1={fy} y2={fy} stroke={C.ink} strokeOpacity={0.22} pointerEvents="none" />
              <line x1={fx} x2={fx} y1={T} y2={T + ny * CS} stroke={C.ink} strokeOpacity={0.22} pointerEvents="none" />
              <rect x={fx - CS / 2 + 0.5} y={fy - CS / 2 + 0.5} width={CS - 1} height={CS - 1} rx={4} fill="none" stroke={C.ink} strokeWidth={2.2} pointerEvents="none" className="dm-focus" />
              {map.landmarks.map((l) => {
                const lx = L + ((l.x[0] / Math.max(1, l.x[1])) * (nx - 1) + 0.5) * CS, ly = T + (ny - 1 - (l.y[0] / Math.max(1, l.y[1])) * (ny - 1) + 0.5) * CS;
                const isHere = here?.name === l.name;
                const right = lx > L + (nx * CS) / 2;
                const r = 10 * Math.min(k, 1.35);
                return (
                  <g key={l.name} className={`dm-pin${isHere ? " here" : ""}${l.in_family === false ? " outside" : ""}`} role="button" tabIndex={0}
                    aria-label={`${l.name}: ${l.case_id}${isHere ? " (this case)" : ""}${l.in_family === false ? ", outside this workload family" : ""}. Open case.`}
                    onClick={() => openCase(l.case_id)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openCase(l.case_id); } }}
                    onPointerEnter={() => setLandmarkFocus(l.name)} onFocus={() => setLandmarkFocus(l.name)}>
                    {isHere ? <circle cx={lx} cy={ly} r={r * 1.5} className="dm-pulse" fill="none" stroke={C.amber} strokeWidth={2} /> : null}
                    <circle cx={lx} cy={ly} r={r} fill="#FFFFFF" stroke={isHere ? C.amber : C.ink} strokeWidth={isHere ? 3 : 2} strokeDasharray={l.in_family === false ? "3 2.5" : undefined} />
                    <text x={lx} y={ly + 3.6 * Math.min(k, 1.35)} textAnchor="middle" fontSize={(l.name.length > 1 ? 8.5 : 10.5) * Math.min(k, 1.35)} fontWeight={750} fill={C.ink}>{l.name}</text>
                    {k <= 1.3 || isHere ? <text x={right ? lx - r - 5 : lx + r + 5} y={ly + 3.5 * k} textAnchor={right ? "end" : "start"} fontSize={10.5 * k} fontWeight={700} fill={C.ink} className="dm-pin-label">{pinLabel(l)}</text> : null}
                  </g>
                );
              })}
              {ticks.map((v) => {
                const gx = L + (v * (nx - 1) + 0.5) * CS, gy = T + (ny - 1 - v * (ny - 1) + 0.5) * CS;
                return <g key={v}><text x={gx} y={T + ny * CS + 14 * k} textAnchor="middle" fontSize={10 * k} fill={C.sec}>{Math.round(v * 100)}%</text>
                  <text x={L - 6} y={gy + 3.5 * k} textAnchor="end" fontSize={10 * k} fill={C.sec}>{Math.round(v * 100)}%</text></g>;
              })}
              <text x={L + (nx * CS) / 2} y={H - 7} textAnchor="middle" fontSize={11.5 * k} fontWeight={650} fill={C.ink}>Route sharing on the butterfly →</text>
              <text transform={`translate(${11 * k} ${T + (ny * CS) / 2}) rotate(-90)`} textAnchor="middle" fontSize={11.5 * k} fontWeight={650} fill={C.ink}>Crossbar bank collisions →</text>
            </svg>
          </div>
          <div className="dm-legend" aria-label="Legend">
            {view === "wins" ? <>
              <span><i className="sw" style={{ background: C.teal }} />Crossbar faster</span>
              <span><i className="sw" style={{ background: C.ink }} />Butterfly faster</span>
              <span><i className="sw" style={{ background: C.tie }} />Too close to call</span>
            </> : <span><i className="sw grad" />Model error on the butterfly, 0 to {geo.maxErr} cycles</span>}
            <span><i className="sw hatch" />Model picks the wrong chip</span>
            <span><i className="sw dots" />Model can't tell, hardware can</span>
            {view === "wins" ? <span><i className="ln solid" />Crossbar really wins inside</span> : null}
            <span><i className="ln dashed" />Model says the crossbar wins inside</span>
          </div>
        </div>

        <div className="dm-side">
          <div className="seg dm-seg" role="group" aria-label="Fast model">
            {(["parent", "repaired"] as const).map((m) => <button key={m} aria-pressed={model === m} className={model === m ? "on" : ""} onClick={() => setModel(m)}>{MODEL_LABEL[m]}</button>)}
          </div>
          <div className="dm-count" aria-live="polite">
            <div><span className="dm-big">{counter("strict_reversals")}</span><span className="dm-big-l">wrong picks</span></div>
            <div><span className="dm-mid">{counter("model_undecided_hardware_decisive")}</span><span className="dm-big-l">can't tell, though the hardware can</span></div>
            <p>{cur.strict_reversals ? <>Worst: following the model costs <b>+{cur.max_extra_cycles_strict} cycles</b> ({Math.round(cur.max_regret_strict * 1000) / 10}%).</> : <>No workload on this map makes it pick the slower chip.</>}
              {" "}{model === "parent" && modelNeverCrossbar ? "It never recommends the crossbar anywhere on this map, so there is no dashed line." : null}</p>
          </div>
          <div className="seg dm-seg small" role="group" aria-label="Colour">
            <button aria-pressed={view === "wins"} className={view === "wins" ? "on" : ""} onClick={() => setView("wins")}>Who wins</button>
            <button aria-pressed={view === "error"} className={view === "error" ? "on" : ""} onClick={() => setView("error")}>How wrong the model is</button>
          </div>
          <p className="dm-note">{view === "wins"
            ? <>The crossbar wins in {crossbarFaster} of {s.cells} workloads, all with at most {maxYA}% crossbar collisions. Everywhere else the butterfly is faster or the two are too close to call.</>
            : <>The {MODEL_LABEL[model].toLowerCase()} misjudges the butterfly by up to {cur.max_abs_error_B} cycles, yet it picks the wrong chip in only {cur.strict_reversals} workloads. A large error matters only where it flips the decision.</>}</p>
          <div className="dm-readout" aria-live="polite">{readout}</div>
        </div>
      </div>
      <details className="dm-details">
        <summary>What we predicted before running, and what happened</summary>
        <ul className="dm-pred">
          <li><span>Predicted</span><p>{prediction.bank_only_model}</p><span>Measured</span><p>Butterfly cost {s.prediction_checks.parent_B_costs.join(", ")} cycles {s.prediction_checks.parent_B_costs.length === 1 ? "in every cell" : "across cells"}; the model is undecided in {s.parent.verdicts.TIE_OR_SMALL_MARGIN ?? 0} cells and {parentCrossbar ? `picks the crossbar in ${parentCrossbar}` : "never picks the crossbar"}.</p></li>
          <li><span>Predicted</span><p>{prediction.hardware}</p><span>Measured</span><p>Crossbar faster in {belowA} of the {below.length} cells below the diagonal, and never above {maxYA}% collisions: the switch-over sits far below the diagonal.</p></li>
          <li><span>Predicted</span><p>{prediction.wrong_region}</p><span>Measured</span><p>{aboveDiag} of {revTotal} wrong picks lie where route sharing exceeds collisions.</p></li>
          <li><span>Predicted</span><p>{prediction.repaired_model}</p><span>Measured</span><p>{s.repaired.strict_reversals} wrong picks and {s.repaired.model_undecided_hardware_decisive} undecided, against {s.parent.strict_reversals} and {s.parent.model_undecided_hardware_decisive} for the bank-only model.</p></li>
        </ul>
        <p className="axis-note">{map.axes.x.label}: {map.axes.x.definition}. {map.axes.y.label}: {map.axes.y.definition}. {map.features_note} Scope: {String(map.scope.acceptance)}. Evaluator: {map.evaluation}.</p>
      </details>
      <p className="dm-foot mono">{map.executor.distinct_rtl_executions} RTL simulations · {s.cells * 3} model predictions · study {map.map_study_id} · {map.reference_epoch} · prediction recorded before execution</p>
    </section>
  );
}

/** Repair-stage link: opens the Decision stage's map with the repaired model selected. */
export function MapLink({ cv }: { cv: CaseView }) {
  const { map } = useMap();
  if (!map || map.integrity_error_count || cv.comparison.models?.B?.model_id !== map.models.parent.model_id) return null;
  const s = map.summary;
  return (
    <button className="btn dm-link" onClick={() => { requestMapModel("repaired"); window.location.hash = `#/case/${cv.case_id}/decision`; }}>
      See the fix across {s.cells} workloads on the decision map: wrong picks {s.parent.strict_reversals} → {s.repaired.strict_reversals} →
    </button>
  );
}

function verdictWord(v: { verdict: string; choice: string | null; rtl_margin_met: boolean | null }, label: (d: string) => string) {
  if (v.verdict === "VALID_COUNTEREXAMPLE") return <b className="bad">picks the {label(v.choice ?? "")}: wrong</b>;
  if (v.verdict === "VALID_NO_REVERSAL") return <b className="good">picks the {label(v.choice ?? "")}: right</b>;
  if (v.verdict === "TIE_OR_SMALL_MARGIN") return v.rtl_margin_met ? <b className="warn">can't tell</b> : <span>too close to call either way</span>;
  return <span>{v.verdict.replaceAll("_", " ").toLowerCase()}</span>;
}

function CellReadout({ c, a, b, model }: { c: MapCell; a: string; b: string; model: MapModel }) {
  const label = (d: string) => (d === a ? "crossbar" : d === b ? "butterfly" : d);
  const ra = c.rtl[a], rb = c.rtl[b];
  const st = hwState(c, a, b);
  return (
    <>
      <div className="dm-r-head"><strong>Route sharing {pctOf(c.x)}% · collisions {pctOf(c.y)}%</strong></div>
      <dl>
        <dt>Hardware (RTL)</dt><dd>crossbar <b>{ra}</b> · butterfly <b>{rb}</b> cycles → {st === "tie" ? "too close to call" : `${label(st)} faster`}</dd>
        {(["parent", "repaired"] as const).map((m) => (
          <div key={m} className={m === model ? "cur" : ""}><dt>{MODEL_LABEL[m]}</dt><dd>crossbar {c.model.A} · butterfly {c.model[m]} → {verdictWord(c.verdict[m], label)}
            {c.verdict[m].verdict === "VALID_COUNTEREXAMPLE" && c.verdict[m].extra != null ? <> (+{c.verdict[m].extra} cycles)</> : null}</dd></div>
        ))}
      </dl>
      <p className="mono dm-runs">RTL {c.runs.rtl_A.slice(-6)} / {c.runs.rtl_B.slice(-6)} · models {c.runs.model_A.slice(-6)} / {c.runs.model_parent.slice(-6)} / {c.runs.model_repaired.slice(-6)}</p>
    </>
  );
}

const VERDICT_WORDS: Record<string, string> = {
  VALID_COUNTEREXAMPLE: "picks the slower chip (strict reversal)",
  VALID_NO_REVERSAL: "picks the faster chip",
  TIE_OR_SMALL_MARGIN: "no decisive ordering",
};

function LandmarkReadout({ l, a, b }: { l: MapLandmark; a: string; b: string }) {
  return (
    <>
      <div className="dm-r-head"><strong>{l.name} · {l.case_id}</strong><span>route sharing {pctOf(l.x)}% · collisions {pctOf(l.y)}%</span></div>
      <dl>
        <dt>Hardware (RTL), its own run</dt><dd>crossbar <b>{l.rtl_costs?.[a] ?? "—"}</b> · butterfly <b>{l.rtl_costs?.[b] ?? "—"}</b> cycles</dd>
        <dt>Bank-only model</dt><dd>crossbar {l.model_costs?.[a] ?? "—"} · butterfly {l.model_costs?.[b] ?? "—"} → {VERDICT_WORDS[l.verdict] ?? l.verdict.replaceAll("_", " ").toLowerCase()}</dd>
      </dl>
      {l.in_family === false ? <p className="dm-out">Outside this map's family ({l.outside_family_because.join(", ")}), so its square on the map is a different workload. RIFT's search still found it.</p> : <p className="dm-out">Placed by the same feature formula as every square. Click to open the case.</p>}
    </>
  );
}
