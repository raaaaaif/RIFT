import type { Check, Operation, Verdict, Workload } from "./types";

/** Same integer-only UTF-8 canonical form as rift.contracts.canonical. */
export function canonical(value: unknown): string {
  if (value === null || typeof value === "boolean" || typeof value === "string") return JSON.stringify(value);
  if (typeof value === "number" && Number.isSafeInteger(value)) return String(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (typeof value === "object" && value) return `{${Object.keys(value).sort().map(k => `${JSON.stringify(k)}:${canonical((value as Record<string, unknown>)[k])}`).join(",")}}`;
  throw new Error("Contracts must contain only JSON values and safe integers.");
}
export async function sha256(bytes: Uint8Array): Promise<string> {
  const hash = await crypto.subtle.digest("SHA-256", bytes as Uint8Array<ArrayBuffer>);
  return "sha256:" + Array.from(new Uint8Array(hash), x => x.toString(16).padStart(2, "0")).join("");
}
export const workloadDigest = (workload: Workload) => sha256(new TextEncoder().encode(canonical(workload)));
const object = (v: unknown): Record<string, unknown> => {
  if (!v || typeof v !== "object" || Array.isArray(v)) throw new Error("Expected an object.");
  return v as Record<string, unknown>;
};
function keys(v: Record<string, unknown>, allowed: string[], required = allowed) {
  if (Object.keys(v).some(k => !allowed.includes(k)) || required.some(k => !(k in v))) throw new Error("Missing or unsupported workload fields.");
}
function integer(v: unknown, name: string, lo: number, hi: number): number {
  if (typeof v !== "number" || !Number.isSafeInteger(v) || v < lo || v > hi) throw new Error(`${name} must be an integer from ${lo} to ${hi}.`);
  return v;
}
function address(v: unknown): number {
  const a = integer(v, "Byte address", 0, 16380);
  if (a % 4) throw new Error("Byte addresses must be aligned to 4 bytes.");
  return a;
}

export function compile(workload: Workload): Operation[][] {
  const w = object(workload);
  keys(w, ["schema_version", "capacity_words", "word_bytes", "masters", "arrival_policy", "program", "label"], ["schema_version", "capacity_words", "word_bytes", "masters", "arrival_policy", "program"]);
  if (w.schema_version !== 1 || w.capacity_words !== 4096 || w.word_bytes !== 4 || w.masters !== 8) throw new Error("Use schema 1, eight initiators, and 4096 four-byte words.");
  if (w.label !== undefined && (typeof w.label !== "string" || w.label.length > 200)) throw new Error("Use a workload label of at most 200 characters.");
  const p = object(w.program), per: Operation[][] = Array.from({ length: 8 }, () => []);
  const add = (master: number, a: unknown, release: unknown = "after_accept", gap: unknown = 0) => {
    if (release !== "after_accept" && release !== "after_response") throw new Error("Release must follow acceptance or response.");
    if (per[master].length >= 1024) throw new Error("At most 1024 reads per initiator.");
    per[master].push({ master, index: per[master].length, byte_address: address(a), release, gap: integer(gap, "Gap", 0, 64) });
  };
  if (p.kind === "repeat_read") {
    keys(p, ["kind", "byte_addresses", "reads_per_master"]);
    if (w.arrival_policy !== "saturated_after_accept" || !Array.isArray(p.byte_addresses) || p.byte_addresses.length !== 8) throw new Error("Repeated reads require eight addresses and saturated_after_accept.");
    const count = integer(p.reads_per_master, "Reads per initiator", 1, 1024);
    p.byte_addresses.forEach((a, m) => { for (let k = 0; k < count; k++) add(m, a); });
  } else if (p.kind === "ordered_read_segments" || p.kind === "read_sequences") {
    keys(p, ["kind", "per_master"]);
    const segments = p.kind === "ordered_read_segments";
    if (w.arrival_policy !== (segments ? "saturated_after_accept" : "per_operation_release") || !Array.isArray(p.per_master)) throw new Error("Program and arrival policy disagree.");
    const seen = new Set<number>();
    for (const entry of p.per_master) {
      const e = object(entry); keys(e, ["master", segments ? "segments" : "ops"]);
      const m = integer(e.master, "Initiator", 0, 7);
      if (seen.has(m)) throw new Error("Each initiator must appear exactly once.");
      seen.add(m);
      const ops = e[segments ? "segments" : "ops"];
      if (!Array.isArray(ops) || (segments && !ops.length)) throw new Error("Provide an operations list (segments cannot be empty).");
      for (const item of ops) {
        const o = object(item);
        if (segments) {
          keys(o, ["byte_address", "count"]);
          const count = integer(o.count, "Segment count", 1, 1024);
          for (let k = 0; k < count; k++) add(m, o.byte_address);
        } else {
          keys(o, ["byte_address", "release", "gap"], ["byte_address"]);
          add(m, o.byte_address, o.release, o.gap);
        }
      }
    }
    if (seen.size !== 8) throw new Error("List all eight initiators; read-sequence lists may be empty.");
  } else throw new Error("Unsupported program kind.");
  const count = per.reduce((n, p) => n + p.length, 0);
  if (!count || count > 4096) throw new Error("A workload must contain 1–4096 reads in total.");
  return per;
}
export function compiledText(per: Operation[][], digest: string): string {
  return ["RIFT_COMPILED_WORKLOAD 1", `digest ${digest}`, "masters 8", ...per.flatMap(ops => ops.map(o => `op ${o.master} ${o.index} ${o.byte_address} ${o.release === "after_accept" ? "A" : "R"} ${o.gap}`)), "end", ""].join("\n");
}
export function sequences(per: Operation[][], label?: string): Workload {
  return { schema_version: 1, capacity_words: 4096, word_bytes: 4, masters: 8, arrival_policy: "per_operation_release",
    program: { kind: "read_sequences", per_master: per.map((ops, master) => ({ master, ops: ops.map(({ byte_address, release, gap }) => ({ byte_address, release, gap })) })) }, ...(label ? { label } : {}) };
}
export function spreadTraffic(workload: Workload): Workload {
  const per = compile(workload);
  return sequences([0, 4, 1, 5, 2, 6, 3, 7].map(i => per[i]), "Pattern M · same streams, reassigned initiators");
}
export function classify(model: { A: Check; B: Check }, rtl: { A: Check; B: Check }): Verdict {
  for (const status of ["TOOL_ERROR", "TIMEOUT", "HARNESS_INVALID", "FUNCTIONAL_MISMATCH"]) {
    if (rtl.A.status === status || rtl.B.status === status) return { verdict: status };
  }
  if (model.A.status !== "COMPLETED" || model.B.status !== "COMPLETED") return { verdict: "MODEL_ERROR" };
  if ([model.A, model.B, rtl.A, rtl.B].some(c => c.makespan === null || c.status !== "COMPLETED")) return { verdict: "TOOL_ERROR" };
  const ma = model.A.makespan!, mb = model.B.makespan!, ra = rtl.A.makespan!, rb = rtl.B.makespan!;
  const margin = (a: number, b: number) => Math.abs(a - b) >= 2 && 50 * Math.abs(a - b) >= Math.min(a, b);
  const mm = margin(ma, mb), rm = margin(ra, rb), chosen = ma <= mb ? "A" : "B";
  return { verdict: mm && rm ? (ma - mb) * (ra - rb) < 0 ? "VALID_COUNTEREXAMPLE" : "VALID_NO_REVERSAL" : "TIE_OR_SMALL_MARGIN",
    model_choice: chosen, rtl_best: ra <= rb ? "A" : "B", extra_cycles: (chosen === "A" ? ra : rb) - Math.min(ra, rb),
    denominator_cycles: Math.max(1, Math.min(ra, rb)), model_margin_met: mm, rtl_margin_met: rm };
}
