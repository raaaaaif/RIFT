import type { ReactElement } from "react";
import type { CaseView, WorkloadView } from "../types";
import { bflyRoute, wording } from "../logic";
import { Term, useUi } from "./common";
import { BankMap, ProgramStrips } from "./Charts";

export function opWord(w: WorkloadView, op: string | null): { master: number; index: number; word: number } | null {
  if (!op) return null;
  const m = /^m(\d+):op(\d+)$/.exec(op);
  if (!m) return null;
  const master = Number(m[1]), index = Number(m[2]);
  const run = w.initiators[master]?.runs.find((r) => index >= r.first_index && index <= r.last_index);
  return run ? { master, index, word: run.word } : null;
}

export function ProgramTable({ w, compact }: { w: WorkloadView; compact?: boolean }) {
  const { op, selectOp } = useUi();
  const designs = Object.keys(w.designs);
  const sel = opWord(w, op);
  return (
    <div className="table-wrap">
      <table className="program">
        <caption className="screenreader">Logical program by initiator. Repeated addresses are distinct operations with stable IDs.</caption>
        <thead><tr><th>Initiator</th><th>Operations (stable IDs)</th><th>Logical word · byte address</th><th>Release</th>{!compact && <th>Mapping</th>}</tr></thead>
        <tbody>
          {w.initiators.flatMap((init) => init.runs.length === 0
            ? [<tr key={`m${init.master}-idle`}><td className="mono">m{init.master}</td><td colSpan={compact ? 3 : 4} className="muted">no operations</td></tr>]
            : init.runs.map((r, i) => {
              const first = `m${init.master}:op${String(r.first_index).padStart(4, "0")}`;
              const last = `m${init.master}:op${String(r.last_index).padStart(4, "0")}`;
              const selected = sel && sel.master === init.master && sel.index >= r.first_index && sel.index <= r.last_index;
              return (
                <tr key={`m${init.master}-${i}`} className={selected ? "selected" : ""}>
                  <td className="mono">{i === 0 ? `m${init.master}` : ""}</td>
                  <td><button className="link" onClick={() => selectOp(first)} aria-pressed={!!selected}>{r.count > 1 ? `${first} … ${last.split(":")[1]}` : first}</button> <span className="muted">({r.count}×)</span></td>
                  <td className="mono">word {r.word} · 0x{r.byte_address.toString(16)}</td>
                  <td>{r.release === "after_accept" ? "after accept" : "after response"}{r.gap ? ` + ${r.gap}` : ""}</td>
                  {!compact && <td>{designs.map((d) => <span className="chip" key={d}>{d}: bank {r.mapping[d].bank} · row {r.mapping[d].row}</span>)}</td>}
                </tr>
              );
            }))}
        </tbody>
      </table>
    </div>
  );
}

/** Static schematic generated from the configuration wiring formula. */
export function Topology({ topology, numIn, numOut, master, bank, sharers, title }: {
  topology: string; numIn: number; numOut: number; master: number | null; bank: number | null; sharers: { master: number; bank: number }[]; title: string;
}) {
  const W = 620, rowH = 18, top = 34, H = top + numOut * rowH + 30;
  const bankY = (b: number) => top + b * rowH + rowH / 2;
  const inY = (m: number) => top + ((m + 0.5) * (numOut * rowH)) / numIn;
  const xIn = 52, xBank = 568;
  const elems: ReactElement[] = [];
  const route = master !== null && bank !== null;
  if (topology === "LIC") {
    const bx = 250, bw = 120;
    elems.push(<rect key="xbar" x={bx} y={top} width={bw} height={numOut * rowH} rx={5} fill="#F4F5F2" stroke="#CCD6D7" />);
    elems.push(<text key="xl" x={bx + bw / 2} y={top - 14} textAnchor="middle" fontSize={11} fontWeight={650}>full crossbar · one arbiter per bank</text>);
    for (let m = 0; m < numIn; m++) elems.push(<line key={`li${m}`} x1={xIn + 40} y1={inY(m)} x2={bx} y2={inY(m)} stroke="#D7DFDF" />);
    for (let b = 0; b < numOut; b++) elems.push(<line key={`lb${b}`} x1={bx + bw} y1={bankY(b)} x2={xBank - 40} y2={bankY(b)} stroke="#D7DFDF" />);
    if (route) elems.push(<path key="sel" d={`M${xIn + 40} ${inY(master!)}H${bx + 10}L${bx + bw - 10} ${bankY(bank!)}H${xBank - 40}`} fill="none" stroke="#006D77" strokeWidth={3} />);
  } else {
    const radix = topology === "BFLY4" ? 4 : 2;
    const levels = Math.ceil(Math.log2(numOut) / Math.log2(radix));
    const routers = numOut / radix;
    const rH = radix * rowH;
    const rx = (l: number) => (levels === 1 ? 300 : 150 + (l * 300) / (levels - 1));
    const portY = (r: number, p: number) => top + r * rH + (p + 0.5) * rowH;
    for (let l = 0; l < levels; l++) for (let r = 0; r < routers; r++) {
      elems.push(<rect key={`r${l}-${r}`} x={rx(l)} y={top + r * rH + 2} width={46} height={rH - 4} rx={4} fill="#F4F5F2" stroke="#CCD6D7" />);
      elems.push(<text key={`rt${l}-${r}`} x={rx(l) + 23} y={top + r * rH + rH / 2 + 3} textAnchor="middle" fontSize={8.5}>S{l + 1}·R{r}</text>);
    }
    for (let m = 0; m < numIn; m++) {
      const h = bflyRoute(numIn, numOut, radix, m, 0)[0];
      elems.push(<line key={`wi${m}`} x1={xIn + 40} y1={inY(m)} x2={rx(0)} y2={portY(h.router, h.inPort)} stroke="#D7DFDF" />);
    }
    for (let l = 0; l < levels - 1; l++) for (let r = 0; r < routers; r++) for (let s = 0; s < radix; s++) {
      const pw = radix ** (levels - l - 2);
      const k = pw * s + (r % pw) + Math.floor(Math.floor(r / pw) / radix) * pw * radix;
      const j = Math.floor(r / pw) % radix;
      elems.push(<line key={`w${l}-${r}-${s}`} x1={rx(l) + 46} y1={portY(r, s)} x2={rx(l + 1)} y2={portY(k, j)} stroke="#E3E9E8" />);
    }
    for (let b = 0; b < numOut; b++) elems.push(<line key={`wb${b}`} x1={rx(levels - 1) + 46} y1={bankY(b)} x2={xBank - 40} y2={bankY(b)} stroke="#E3E9E8" />);
    const drawRoute = (m: number, b: number, color: string, width: number, dash: string | undefined, key: string) => {
      const hops = bflyRoute(numIn, numOut, radix, m, b);
      let d = `M${xIn + 40} ${inY(m)}L${rx(0)} ${portY(hops[0].router, hops[0].inPort)}`;
      hops.forEach((h, i) => {
        d += `L${rx(h.level) + 46} ${portY(h.router, h.outPort)}`;
        if (i < hops.length - 1) d += `L${rx(h.level + 1)} ${portY(hops[i + 1].router, hops[i + 1].inPort)}`;
      });
      elems.push(<path key={`route${key}`} d={d + `L${xBank - 40} ${bankY(b)}`} fill="none" stroke={color} strokeWidth={width} strokeDasharray={dash} />);
      return hops;
    };
    if (route) {
      sharers.forEach((s, i) => s.master !== master && drawRoute(s.master, s.bank, "#8A5B00", 2, "5 4", `s${i}`));
      const h0 = drawRoute(master!, bank!, "#006D77", 3, undefined, "sel")[0];
      if (sharers.length) elems.push(<circle key="hot" cx={rx(0) + 46} cy={portY(h0.router, h0.outPort)} r={6} fill="#FFF4DA" stroke="#8A5B00" strokeWidth={1.8} />);
    }
  }
  for (let m = 0; m < numIn; m++) {
    const sel = m === master;
    elems.push(<rect key={`im${m}`} x={xIn - 40} y={inY(m) - 9} width={80} height={18} rx={4} fill={sel ? "#18343F" : "#F4F5F2"} stroke="#CCD6D7" />);
    elems.push(<text key={`it${m}`} x={xIn} y={inY(m) + 4} textAnchor="middle" fontSize={10} style={sel ? { fill: "white" } : undefined}>m{m}</text>);
  }
  for (let b = 0; b < numOut; b++) {
    const sel = b === bank;
    elems.push(<rect key={`bm${b}`} x={xBank - 40} y={bankY(b) - 8} width={80} height={16} rx={3} fill={sel ? "#006D77" : "#F4F5F2"} stroke="#CCD6D7" />);
    elems.push(<text key={`bt${b}`} x={xBank} y={bankY(b) + 4} textAnchor="middle" fontSize={9.5} style={sel ? { fill: "white" } : undefined}>bank {b}</text>);
  }
  return (
    <div className="topo-wrap">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`${title}. ${route ? `Selected route: m${master} to bank ${bank}.` : ""} Generated from the configuration wiring.`}>
        <text x={xIn} y={20} textAnchor="middle" fontSize={9.5}>INITIATORS</text>
        <text x={xBank} y={20} textAnchor="middle" fontSize={9.5}>BANKS</text>
        {elems}
      </svg>
    </div>
  );
}

export function routeSharers(w: WorkloadView, topology: string, numOut: number, master: number, word: number): { master: number; bank: number }[] {
  if (topology !== "BFLY4") return [];
  const group = (word % numOut) >> 2, pair = master >> 1;
  const out: { master: number; bank: number }[] = [];
  w.initiators.forEach((init) => {
    if (init.master === master || init.master >> 1 !== pair) return;
    const r = init.runs.find((x) => (x.word % numOut) >> 2 === group);
    if (r) out.push({ master: init.master, bank: r.word % numOut });
  });
  return out;
}

function sharedBanks(w: WorkloadView, design: string): Set<number> {
  const who = new Map<number, Set<number>>();
  w.initiators.forEach((i) => i.runs.forEach((r) => { const b = r.mapping[design]?.bank; if (b !== undefined) who.set(b, (who.get(b) ?? new Set()).add(i.master)); }));
  return new Set([...who.entries()].filter(([, s]) => s.size >= 2).map(([b]) => b));
}

export function WorkloadView_({ cv }: { cv: CaseView }) {
  const { op, selectOp, gotoStage } = useUi();
  const wd = wording(cv);
  const w = cv.workload;
  if (!w) return <div className="empty-note">No workload recorded for this case.</div>;
  const firstInit = w.initiators.find((i) => i.runs.length)!;
  const sel = opWord(w, op) ?? { master: firstInit.master, index: 0, word: firstInit.runs[0].word };
  const B = Object.entries(w.designs).find(([, d]) => d.topology !== "LIC");
  const A = Object.entries(w.designs).find(([, d]) => d.topology === "LIC");
  const sh = B ? routeSharers(w, B[1].topology, B[1].banks, sel.master, sel.word) : [];
  const conflictsA = sharedBanks(w, "A");
  const red = cv.reduction;
  return (
    <>
      <div className="stage-meta"><span className="eyebrow">02 / Workload</span><span className={`tag ${wd.tone}`}>{wd.tag} · executed</span></div>
      <h1 id="stage-heading" tabIndex={-1} className="hero-title">Same program, two designs.</h1>
      <p className="hero-sub">{w.total_operations} reads from {w.initiators.length} initiators. Both designs run the identical program and accept requests at their own pace.</p>

      <section className="panel" aria-labelledby="prog-h" id="prog">
        <div className="panel-head"><div><h2 id="prog-h">The program</h2><p>Each bar is one initiator; each block is a run of reads to one word. Click a block to follow it.</p></div><span className="stamp">{w.program_kind}</span></div>
        <div className="panel-body">
          <ProgramStrips w={w} selected={op} onPick={selectOp} conflictsA={conflictsA} />
          <p className="axis-note"><span className="legend-dot" style={{ background: "#FFF4DA", border: "1px solid #D9A441" }} /> outlined blocks share a crossbar bank with another initiator</p>
        </div>
      </section>

      {A && B ? (
        <div className="two-col">
          <section className="panel" aria-labelledby="bank-a"><div className="panel-head"><div><h2 id="bank-a">Crossbar · 8 banks</h2><p>{conflictsA.size ? `${conflictsA.size} bank${conflictsA.size > 1 ? "s are" : " is"} shared by several initiators.` : "Every initiator has its own bank."}</p></div></div>
            <div className="panel-body"><BankMap w={w} design="A" banks={A[1].banks} /></div></section>
          <section className="panel" aria-labelledby="bank-b"><div className="panel-head"><div><h2 id="bank-b">Butterfly · 16 banks</h2><p>Grouped by the stage-1 output that reaches them (4 banks each).</p></div></div>
            <div className="panel-body"><BankMap w={w} design="B" banks={B[1].banks} group={4} /></div></section>
        </div>
      ) : null}

      {A && B ? (
        <section className="panel" aria-labelledby="topo-h" id="topo">
          <div className="panel-head"><div><h2 id="topo-h">Follow m{sel.master}:op{String(sel.index).padStart(4, "0")} (word {sel.word})</h2>
            <p>{sh.length ? <>On the butterfly it shares stage-1 router {sel.master >> 1}'s output with {sh.map((x) => `m${x.master}`).join(", ")}, even though the banks differ: <Term k="route">internal route contention</Term>.</> : "On the butterfly no other initiator in this program uses the same stage-1 output."}</p></div>
            <span className="stamp">FROM CONFIGURATION WIRING</span></div>
          <div className="panel-body two-col">
            <Topology topology="LIC" numIn={A[1].initiators} numOut={A[1].banks} master={sel.master} bank={sel.word % A[1].banks} sharers={[]} title="Design A crossbar" />
            <Topology topology={B[1].topology} numIn={B[1].initiators} numOut={B[1].banks} master={sel.master} bank={sel.word % B[1].banks} sharers={sh} title="Design B butterfly" />
          </div>
        </section>
      ) : null}

      {red ? (
        <section className="panel" aria-labelledby="red-h" id="red">
          <div className="panel-head"><div><h2 id="red-h">Shrunk to the essentials: {red.original.operations} → {red.reduced.operations} reads</h2>
            <p>Still a strict reversal after shrinking. Candidates were screened from reset with a validated surrogate; the original and final witnesses were <Term k="prefix">replayed from reset</Term> on the RTL, with additional neighbour checks within the recorded budget.</p></div><span className="stamp">WITNESS REDUCTION</span></div>
          <div className="panel-body">
            <div className="shrink">
              <div className="shrink-bar"><span style={{ width: "100%" }} /><em>{red.original.operations} original</em></div>
              <div className="shrink-bar"><span className="small" style={{ width: `${(100 * red.reduced.operations) / red.original.operations}%` }} /><em>{red.reduced.operations} reduced</em></div>
            </div>
            <div className="fact-row">
              <div className="fact"><span>model</span><strong>{red.reduced.verdict.model_costs.A} vs {red.reduced.verdict.model_costs.B}</strong></div>
              <div className="fact"><span>hardware</span><strong>{red.reduced.verdict.rtl_costs.A} vs {red.reduced.verdict.rtl_costs.B}</strong></div>
              <div className="fact"><span>RTL replays</span><strong>{red.rtl_executions_used}/{red.rtl_budget}</strong></div>
              <div className={`fact wide ${red.minimality_established ? "ok" : ""}`}><span>minimality</span><strong className="small">{red.minimality_established ? `1-minimal: all ${red.neighbours?.total} one-edit variants break the reversal (${red.neighbours?.rtl_rechecked} re-checked on RTL)` : red.minimality}</strong></div>
            </div>
            <ProgramStrips w={red.reduced_workload} selected={null} onPick={() => {}} conflictsA={sharedBanks(red.reduced_workload, "A")} />
            <details className="table-details" style={{ borderTop: 0 }}><summary style={{ padding: "8px 0" }}>Accepted edits ({red.accepted_edits.length}) and edit set</summary>
              <ol className="edit-list">{red.accepted_edits.map((e, i) => <li key={i}>{e}</li>)}</ol>
              <ul className="checklist">{red.edit_set.map((e) => <li key={e}>{e}</li>)}</ul></details>
          </div>
        </section>
      ) : null}

      <details className="table-details panel" style={{ padding: "0 4px" }}><summary>Exact operations ({w.total_operations}) with IDs and bank/row mapping</summary><div className="panel-body"><ProgramTable w={w} /></div></details>
      <div className="actions"><button className="btn primary" onClick={() => gotoStage(2)}>See where the time goes →</button></div>
    </>
  );
}
