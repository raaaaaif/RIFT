import type { ReactElement } from "react";
import { bflyRoute } from "../logic";

export interface FlowProps {
  numIn: number;
  numOut: number;
  accepted: { m: number; bank: number }[];
  waiting: Set<number>;
  finished: Set<number>;
  hot?: Map<string, number[]>;     // "router:output" -> requesting initiators (measured)
  emphasize?: number[];            // initiators to emphasize (explanation steps)
  label: string;
}

const C = { ink: "#18343F", sec: "#52636B", teal: "#006D77", tealSoft: "#D6ECEE", amber: "#8A5B00", amberSoft: "#FFF4DA", amberLine: "#D9A441",
  rule: "#CCD6D7", faint: "#E7ECEB", inset: "#F1F4F1", white: "#FFFFFF", done: "#E3E8E6" };

function Initiator({ x, y, m, state, emph }: { x: number; y: number; m: number; state: "accept" | "wait" | "done" | "idle"; emph: boolean }) {
  const fill = state === "accept" ? C.teal : state === "wait" ? C.amberSoft : state === "done" ? C.done : C.white;
  const stroke = state === "accept" ? C.teal : state === "wait" ? C.amberLine : C.rule;
  const text = state === "accept" ? C.white : state === "wait" ? C.amber : state === "done" ? "#8A9A9F" : C.ink;
  return (
    <g className="flow-node">
      {emph ? <rect x={x - 33} y={y - 15} width={66} height={30} rx={9} fill="none" stroke="#1255B8" strokeWidth={2} strokeDasharray="3 3" /> : null}
      <rect x={x - 28} y={y - 11} width={56} height={22} rx={6} fill={fill} stroke={stroke} strokeWidth={1.5} />
      <text x={x} y={y + 4} textAnchor="middle" fontSize={11.5} fontWeight={650} fill={text}>m{m}</text>
      {state === "wait" ? <text x={x + 34} y={y + 4} fontSize={9} fill={C.amber}>waits</text> : null}
    </g>
  );
}

function Bank({ x, y, b, w, h, on }: { x: number; y: number; b: number; w: number; h: number; on: boolean }) {
  return (
    <g>
      <rect x={x} y={y - h / 2} width={w} height={h} rx={3.5} fill={on ? C.teal : C.inset} stroke={on ? C.teal : C.rule} />
      <text x={x + w / 2} y={y + 3.5} textAnchor="middle" fontSize={9.5} fill={on ? C.white : C.sec}>{b}</text>
    </g>
  );
}

export function CrossbarFlow({ numIn, numOut, accepted, waiting, finished, emphasize = [], label }: FlowProps) {
  const W = 520, H = 360, top = 40, bottom = H - 26;
  const inY = (m: number) => top + ((m + 0.5) * (bottom - top)) / numIn;
  const bankY = (b: number) => top + ((b + 0.5) * (bottom - top)) / numOut;
  const xIn = 46, boxL = 130, boxR = 380, xBank = 430;
  const acceptedBy = new Map(accepted.map((a) => [a.m, a.bank]));
  const banksOn = new Set(accepted.map((a) => a.bank));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="flow" role="img" aria-label={`${label}: ${accepted.length} accepted, ${waiting.size} waiting this cycle`}>
      <text x={xIn} y={22} textAnchor="middle" className="flow-cap">INITIATORS</text>
      <text x={(boxL + boxR) / 2} y={22} textAnchor="middle" className="flow-cap">FULL CROSSBAR · ONE ARBITER PER BANK</text>
      <text x={xBank + 26} y={22} textAnchor="middle" className="flow-cap">BANKS</text>
      <rect x={boxL} y={top - 6} width={boxR - boxL} height={bottom - top + 12} rx={12} fill="#FAFBFA" stroke={C.rule} />
      {Array.from({ length: numIn }, (_, m) => Array.from({ length: numOut }, (_, b) => (
        <line key={`${m}-${b}`} x1={boxL} y1={inY(m)} x2={boxR} y2={bankY(b)} stroke={C.faint} strokeWidth={0.8} />
      )))}
      {Array.from({ length: numIn }, (_, m) => <line key={`i${m}`} x1={xIn + 28} y1={inY(m)} x2={boxL} y2={inY(m)} stroke={C.rule} />)}
      {Array.from({ length: numOut }, (_, b) => <line key={`o${b}`} x1={boxR} y1={bankY(b)} x2={xBank} y2={bankY(b)} stroke={C.rule} />)}
      {accepted.map((a) => (
        <path key={`a${a.m}`} d={`M${xIn + 28} ${inY(a.m)}H${boxL}L${boxR} ${bankY(a.bank)}H${xBank}`} fill="none" stroke={C.teal} strokeWidth={3} strokeLinecap="round" />
      ))}
      {[...waiting].map((m) => <line key={`w${m}`} x1={xIn + 28} y1={inY(m)} x2={boxL} y2={inY(m)} stroke={C.amberLine} strokeWidth={2.5} strokeDasharray="4 3" />)}
      {Array.from({ length: numIn }, (_, m) => (
        <Initiator key={m} x={xIn} y={inY(m)} m={m} emph={emphasize.includes(m)}
          state={acceptedBy.has(m) ? "accept" : waiting.has(m) ? "wait" : finished.has(m) ? "done" : "idle"} />
      ))}
      {Array.from({ length: numOut }, (_, b) => <Bank key={b} x={xBank} y={bankY(b)} b={b} w={52} h={Math.min(26, (bottom - top) / numOut - 6)} on={banksOn.has(b)} />)}
    </svg>
  );
}

export function ButterflyFlow({ numIn, numOut, accepted, waiting, finished, hot, emphasize = [], label }: FlowProps) {
  const radix = 4;
  const W = 520, H = 360, top = 40, bottom = H - 26;
  const levels = Math.ceil(Math.log2(numOut) / Math.log2(radix));
  const routers = numOut / radix;
  const rH = (bottom - top) / routers;
  const xIn = 46, xR = [150, 300], rw = 52, xBank = 430;
  const portY = (r: number, p: number) => top + r * rH + ((p + 0.5) * rH) / radix;
  const inY = (m: number) => {
    const h = bflyRoute(numIn, numOut, radix, m, 0)[0];
    return portY(h.router, h.inPort);
  };
  const bankY = (b: number) => top + ((b + 0.5) * (bottom - top)) / numOut;
  const acceptedBy = new Map(accepted.map((a) => [a.m, a.bank]));
  const banksOn = new Set(accepted.map((a) => a.bank));
  const routePath = (m: number, b: number) => {
    const hops = bflyRoute(numIn, numOut, radix, m, b);
    let d = `M${xIn + 28} ${inY(m)}L${xR[0]} ${portY(hops[0].router, hops[0].inPort)}`;
    hops.forEach((h, i) => {
      d += `L${xR[h.level] + rw} ${portY(h.router, h.outPort)}`;
      if (i < hops.length - 1) d += `L${xR[h.level + 1]} ${portY(hops[i + 1].router, hops[i + 1].inPort)}`;
    });
    return d + `L${xBank} ${bankY(b)}`;
  };
  const wires: ReactElement[] = [];
  for (let r = 0; r < routers; r++) for (let s = 0; s < radix; s++) {
    const pw = radix ** (levels - 2);
    const k = pw * s + (r % pw) + Math.floor(Math.floor(r / pw) / radix) * pw * radix;
    const j = Math.floor(r / pw) % radix;
    wires.push(<line key={`w${r}${s}`} x1={xR[0] + rw} y1={portY(r, s)} x2={xR[1]} y2={portY(k, j)} stroke={C.faint} strokeWidth={1.2} />);
  }
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="flow" role="img" aria-label={`${label}: ${accepted.length} accepted, ${waiting.size} waiting this cycle`}>
      <text x={xIn} y={22} textAnchor="middle" className="flow-cap">INITIATORS</text>
      <text x={xR[0] + rw / 2} y={22} textAnchor="middle" className="flow-cap">STAGE 1</text>
      <text x={xR[1] + rw / 2} y={22} textAnchor="middle" className="flow-cap">STAGE 2</text>
      <text x={xBank + 26} y={22} textAnchor="middle" className="flow-cap">BANKS</text>
      {wires}
      {Array.from({ length: numIn }, (_, m) => {
        const h = bflyRoute(numIn, numOut, radix, m, 0)[0];
        return <line key={`in${m}`} x1={xIn + 28} y1={inY(m)} x2={xR[0]} y2={portY(h.router, h.inPort)} stroke={C.rule} />;
      })}
      {Array.from({ length: numOut }, (_, b) => <line key={`ob${b}`} x1={xR[1] + rw} y1={bankY(b)} x2={xBank} y2={bankY(b)} stroke={C.faint} />)}
      {[0, 1].map((l) => Array.from({ length: routers }, (_, r) => (
        <g key={`r${l}${r}`}>
          <rect x={xR[l]} y={top + r * rH + 4} width={rw} height={rH - 8} rx={8} fill="#FAFBFA" stroke={C.rule} />
          <text x={xR[l] + rw / 2} y={top + r * rH + rH / 2 + 4} textAnchor="middle" fontSize={10} fill={C.sec}>R{r}</text>
        </g>
      )))}
      {accepted.map((a) => <path key={`a${a.m}`} d={routePath(a.m, a.bank)} fill="none" stroke={C.teal} strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" />)}
      {[...waiting].map((m) => {
        const h = bflyRoute(numIn, numOut, radix, m, 0)[0];
        return <line key={`wt${m}`} x1={xIn + 28} y1={inY(m)} x2={xR[0]} y2={portY(h.router, h.inPort)} stroke={C.amberLine} strokeWidth={2.5} strokeDasharray="4 3" />;
      })}
      {hot ? [...hot.entries()].filter(([, reqs]) => reqs.length >= 2).map(([key, reqs]) => {
        const [r, s] = key.split(":").map(Number);
        const x = xR[0] + rw, y = portY(r, s);
        return (
          <g key={`hot${key}`}>
            <circle cx={x} cy={y} r={10} fill={C.amberSoft} stroke={C.amber} strokeWidth={1.8} />
            <text x={x} y={y + 3.5} textAnchor="middle" fontSize={10} fontWeight={700} fill={C.amber}>{reqs.length}</text>
          </g>
        );
      }) : null}
      {Array.from({ length: numIn }, (_, m) => (
        <Initiator key={m} x={xIn} y={inY(m)} m={m} emph={emphasize.includes(m)}
          state={acceptedBy.has(m) ? "accept" : waiting.has(m) ? "wait" : finished.has(m) ? "done" : "idle"} />
      ))}
      {Array.from({ length: numOut }, (_, b) => <Bank key={b} x={xBank} y={bankY(b)} b={b} w={52} h={(bottom - top) / numOut - 3} on={banksOn.has(b)} />)}
    </svg>
  );
}
