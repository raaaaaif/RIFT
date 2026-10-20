/** Independent of simulator/model code. Port of rift.evaluate.checker/v1. */
import type { TraceEvent } from "../types";
import type { Check, Operation, Summary } from "./types";
export interface RawEvent extends TraceEvent { schema_version: number; run_id: string; sample_phase: string }

const required = ["schema_version", "run_id", "cycle", "sample_phase", "event_kind", "master", "operation_index", "byte_address"];
const kinds = ["offer", "accept", "complete", "reset", "monitor_failure"];
export const expectedWord = (q: number) => (Math.imul(q, 0x9e3779b1) ^ 0xa5a55a5a) >>> 0;

export function checkEvents(per: Operation[][], digest: string, banks: number, events: RawEvent[], summary: Summary,
  runner: "rtl" | "model", timeout = 4096, respLat = 1): Check {
  const violations: Check["violations"] = [], counts: Record<string, number> = {};
  const bad = (code: string, detail: string) => {
    counts[code] = (counts[code] ?? 0) + 1;
    if (violations.length < 40) violations.push({ code, detail });
  };
  const result = (status: string, raw: number | null, extra: Partial<Check> = {}): Check => ({
    schema_version: 1, checker: "rift.evaluate.checker/v1", status, functional_valid: status === "COMPLETED",
    workload_digest: digest, expected_operations: per.reduce((n, ops) => n + ops.length, 0),
    makespan: status === "COMPLETED" ? raw : null, makespan_from_events_unvalidated: raw,
    metric_id: "inclusive_cycle_makespan_v1", violation_counts: counts, violations, summary_agreement: null, ...extra,
  });
  if (!events.length) { bad("NO_EVENTS", "No events recorded."); return result("TOOL_ERROR", null); }
  if (new Set(events.map(e => e?.run_id)).size !== 1) bad("MIXED_RUN_IDS", "Multiple run identities in one event stream.");
  const ops = new Map<string, Operation>(per.flatMap(p => p.map(o => [`${o.master}:${o.index}`, o] as const)));
  const seen = { offer: new Map<string, TraceEvent>(), accept: new Map<string, TraceEvent>(), complete: new Map<string, TraceEvent>() };
  const resets: number[] = [], bankCycle = new Map<string, number>();
  let lastCycle = -1, monitorFailures = 0;
  for (const [i, e] of events.entries()) {
    if (!e || required.some(k => !(k in e)) || e.schema_version !== 1 || !kinds.includes(e.event_kind)) {
      bad("MALFORMED_EVENT", `Event ${i} malformed.`); continue;
    }
    const c = e.cycle;
    if (!Number.isSafeInteger(c) || c < lastCycle) { bad("NON_MONOTONIC_CYCLE", `Event ${i} cycle ${c} after ${lastCycle}.`); continue; }
    lastCycle = c;
    const kind = e.event_kind;
    if (kind === "reset") { resets.push(c); continue; }
    if (kind === "monitor_failure") { monitorFailures++; bad("MONITOR_FAILURE", `${e.monitor_id} at cycle ${c}: ${e.detail}`); continue; }
    if (kind !== "offer" && kind !== "accept" && kind !== "complete") continue;
    const key = `${e.master}:${e.operation_index}`, op = ops.get(key);
    if (!op) { bad("UNKNOWN_OPERATION", `Event for nonexistent operation ${key}.`); continue; }
    if (seen[kind].has(key)) { bad("DUPLICATE_EVENT", `Second ${kind} for ${key}.`); continue; }
    seen[kind].set(key, e);
    if (e.byte_address !== op.byte_address) bad("ADDRESS_MISMATCH", `${key} has a different address.`);
    const q = op.byte_address >>> 2;
    if (e.bank != null && e.bank !== q % banks) bad("BANK_MAPPING", `${key} bank ${e.bank} differs from ${q % banks}.`);
    if (e.row != null && e.row !== Math.floor(q / banks)) bad("ROW_MAPPING", `${key} row is inconsistent with the address.`);
    if (kind === "accept") { const b = `${c}:${q % banks}`; bankCycle.set(b, (bankCycle.get(b) ?? 0) + 1); }
    if (kind === "complete" && e.read_data !== expectedWord(q)) bad("DATA_MISMATCH", `${key} read data differs from the independent memory oracle.`);
  }
  if (resets.join(",") !== "0,1,2,3") bad("RESET_SEQUENCE", "Expected exactly reset cycles 0, 1, 2, 3.");
  for (const [key, n] of bankCycle) if (n > 1) bad("BANK_DOUBLE_ACCEPT", `${key}: ${n} reads accepted at one bank in one cycle.`);
  let incomplete = 0;
  const acceptedCycles: number[] = [];
  for (const masterOps of per) {
    let prev: [number, number, number] | null = null;
    for (const op of masterOps) {
      const key = `${op.master}:${op.index}`, o = seen.offer.get(key), a = seen.accept.get(key), r = seen.complete.get(key);
      if (!o || !a || !r) {
        incomplete++;
        if (incomplete <= 3) bad("INCOMPLETE_OPERATION", `${key} is missing offer, acceptance, or completion.`);
        prev = null; continue;
      }
      const oc = o.cycle, ac = a.cycle, rc = r.cycle;
      acceptedCycles.push(ac);
      if (ac < oc) bad("ACCEPT_BEFORE_OFFER", `${key} accepted before offer.`);
      if (rc !== ac + respLat) bad("RESPONSE_LATENCY", `${key} response latency differs from ${respLat}.`);
      const expected: number | null = op.index === 0 ? 4 + op.gap : prev ? prev[op.release === "after_accept" ? 1 : 2] + 1 + op.gap : null;
      if (expected !== null && oc !== expected) bad("RELEASE_RULE", `${key} offered at ${oc}; contract releases it at ${expected}.`);
      prev = [oc, ac, rc];
    }
    if (incomplete > 3) counts.INCOMPLETE_OPERATION = incomplete;
  }
  const completes = [...seen.complete.values()].map(e => e.cycle);
  const last = completes.length ? Math.max(...completes) : null, raw = last === null ? null : last - 3;
  let status = "COMPLETED";
  if (summary.exit_status === "TIMEOUT" || (raw !== null && raw > timeout)) status = "TIMEOUT";
  else if (Object.keys(counts).some(k => k !== "DATA_MISMATCH")) status = runner === "rtl" ? "HARNESS_INVALID" : "MODEL_ERROR";
  else if (counts.DATA_MISMATCH) status = runner === "rtl" ? "FUNCTIONAL_MISMATCH" : "MODEL_ERROR";
  const agreement = { makespan: status !== "COMPLETED" || summary.makespan === raw,
    accepted: summary.accepted === seen.accept.size, completed: summary.completed === seen.complete.size, runner_exit_status: summary.exit_status };
  if (status === "COMPLETED" && (!agreement.makespan || !agreement.accepted || !agreement.completed)) {
    bad("SUMMARY_DISAGREES", "Runner summary disagrees with independent event recomputation.");
    status = runner === "rtl" ? "HARNESS_INVALID" : "MODEL_ERROR";
  }
  if (status === "COMPLETED" && summary.exit_status !== "COMPLETED") {
    bad("RUNNER_STATUS", `Runner reported ${summary.exit_status} but events are clean.`);
    status = runner === "rtl" ? "HARNESS_INVALID" : "MODEL_ERROR";
  }
  return { ...result(status, raw), first_release_cycle: 4, last_response_cycle: last,
    acceptance_cycles_distinct: new Set(acceptedCycles).size,
    acceptance_window: acceptedCycles.length ? Math.max(...acceptedCycles) - 3 : null,
    accepted: seen.accept.size, completed: seen.complete.size, offered: seen.offer.size,
    monitor_failures: monitorFailures, summary_agreement: agreement } as Check;
}
