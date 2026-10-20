import { useState } from "react";
import { compile, sequences } from "./contracts";
import type { Operation, Workload } from "./types";

interface Segment { address: string; count: string; release: "after_accept" | "after_response"; gap: string }
function rowsFor(workload: Workload): Segment[][] {
  return compile(workload).map(ops => {
    const rows: Segment[] = [];
    for (const o of ops) {
      const last = rows.at(-1);
      if (last && last.address === String(o.byte_address) && last.release === o.release && last.gap === String(o.gap)) last.count = String(Number(last.count) + 1);
      else rows.push({ address: String(o.byte_address), count: "1", release: o.release, gap: String(o.gap) });
    }
    return rows;
  });
}
export default function WorkloadEditor({ workload, onApply, onDirty }: { workload: Workload; onApply: (workload: Workload) => void; onDirty: (dirty: boolean) => void }) {
  const [rows, setRows] = useState(() => rowsFor(workload));
  const [error, setError] = useState("");
  const update = (m: number, next: Segment[]) => { setRows(all => all.map((r, i) => i === m ? next : r)); onDirty(true); setError(""); };
  const apply = () => {
    try {
      let total = 0;
      const per = rows.map((segments, master) => {
        const ops: Operation[] = [];
        for (const s of segments) {
          const count = Number(s.count), a = Number(s.address), gap = Number(s.gap);
          if (![s.count, s.address, s.gap].every(v => v.trim() !== "") || !Number.isInteger(count) || count < 1 || count > 1024) throw new Error("Enter an address, gap, and a read count from 1 to 1024 for every segment.");
          total += count;
          if (total > 4096 || ops.length + count > 1024) throw new Error("Use at most 1024 reads per initiator and 4096 total.");
          for (let k = 0; k < count; k++) ops.push({ master, index: ops.length, byte_address: a, release: s.release, gap });
        }
        return ops;
      });
      const next = sequences(per, "Visitor workload"); compile(next); onApply(next); onDirty(false); setError("");
    } catch (e) { setError((e as Error).message); }
  };
  return <div className="workload-editor">
    <p className="axis-note">Each row is a sequence of identical reads. Byte addresses map to bank <span className="mono">(address ÷ 4) mod 8</span> in A and <span className="mono">mod 16</span> in B. Removing every row makes that initiator idle.</p>
    <div className="initiator-editor-grid">{rows.map((segments, m) => <fieldset key={m}>
      <legend>Initiator {m}</legend>
      {segments.length ? segments.map((s, i) => <div className="read-segment" key={i}>
        <label>Byte address<input aria-label={`Initiator ${m} segment ${i + 1} byte address`} type="number" min={0} max={16380} step={4} value={s.address} onChange={e => update(m, segments.map((x, j) => j === i ? { ...x, address: e.target.value } : x))} /></label>
        <label>Reads<input aria-label={`Initiator ${m} segment ${i + 1} reads`} type="number" min={1} max={1024} value={s.count} onChange={e => update(m, segments.map((x, j) => j === i ? { ...x, count: e.target.value } : x))} /></label>
        <label>Release<select aria-label={`Initiator ${m} segment ${i + 1} release`} value={s.release} onChange={e => update(m, segments.map((x, j) => j === i ? { ...x, release: e.target.value as Segment["release"] } : x))}><option value="after_accept">After acceptance</option><option value="after_response">After response</option></select></label>
        <label>Gap<input aria-label={`Initiator ${m} segment ${i + 1} gap`} type="number" min={0} max={64} value={s.gap} onChange={e => update(m, segments.map((x, j) => j === i ? { ...x, gap: e.target.value } : x))} /></label>
        <button className="text-button" aria-label={`Remove initiator ${m} segment ${i + 1}`} onClick={() => update(m, segments.filter((_, j) => j !== i))}>Remove</button>
      </div>) : <p className="axis-note">Idle</p>}
      <button className="text-button" onClick={() => update(m, [...segments, { address: String(m * 4), count: "1", release: "after_accept", gap: "0" }])}>+ Add segment to {m}</button>
    </fieldset>)}</div>
    {error ? <p role="alert" className="err-box">{error}</p> : null}
    <div className="actions"><button className="btn compact" onClick={apply}>Apply workload</button><button className="text-button" onClick={() => { setRows(rowsFor(workload)); onDirty(false); setError(""); }}>Discard edits</button><span className="axis-note">Apply edits before running.</span></div>
  </div>;
}
