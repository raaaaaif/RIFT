import type { TraceSelection } from "./types";

/** Per-cycle state derived only from recorded boundary events of one run. */
export interface Timeline {
  first: number;
  finish: number;            // last response cycle
  total: number;             // operations
  accepted: Map<number, { m: number; bank: number; op: string }[]>;
  waiting: Map<number, Set<number>>;   // initiators offering but not accepted in this cycle
  completedBy: number[];     // index = cycle, value = completed operations up to and including the cycle
  done: Map<number, number>; // initiator -> cycle of its last acceptance
}

export function buildTimeline(t: Pick<TraceSelection, "events">): Timeline {
  const offers = new Map<string, { m: number; offer?: number; accept?: number; bank: number }>();
  let finish = 0;
  const completes: number[] = [];
  for (const e of t.events) {
    if (e.master === null || e.operation_index === null) continue;
    const key = `${e.master}:${e.operation_index}`;
    const o = offers.get(key) ?? { m: e.master, bank: e.bank ?? 0 };
    if (e.event_kind === "offer") o.offer = e.cycle;
    if (e.event_kind === "accept") o.accept = e.cycle;
    if (e.event_kind === "complete") { completes.push(e.cycle); finish = Math.max(finish, e.cycle); }
    offers.set(key, o);
  }
  const accepted = new Map<number, { m: number; bank: number; op: string }[]>();
  const waiting = new Map<number, Set<number>>();
  const done = new Map<number, number>();
  for (const [key, o] of offers) {
    if (o.accept === undefined || o.offer === undefined) continue;
    const list = accepted.get(o.accept) ?? [];
    const [m, idx] = key.split(":");
    list.push({ m: o.m, bank: o.bank, op: `m${m}:op${String(idx).padStart(4, "0")}` });
    accepted.set(o.accept, list);
    for (let c = o.offer; c < o.accept; c++) {
      const s = waiting.get(c) ?? new Set<number>();
      s.add(o.m);
      waiting.set(c, s);
    }
    done.set(o.m, Math.max(done.get(o.m) ?? 0, o.accept));
  }
  const completedBy = new Array(finish + 2).fill(0);
  for (const c of completes) completedBy[c] += 1;
  for (let c = 1; c < completedBy.length; c++) completedBy[c] += completedBy[c - 1];
  return { first: 4, finish, total: completes.length, accepted, waiting, completedBy, done };
}

export const completedAt = (tl: Timeline, c: number) => tl.completedBy[Math.min(c, tl.completedBy.length - 1)] ?? 0;
