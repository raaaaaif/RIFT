import type { Timeline } from "../replay";

export type Design = "A" | "B";
export interface ReadOp { byte_address: number; release?: "after_accept" | "after_response"; gap?: number }
export interface Workload {
  schema_version: 1; capacity_words: 4096; word_bytes: 4; masters: 8; label?: string;
  arrival_policy: "saturated_after_accept" | "per_operation_release";
  program: { kind: "repeat_read"; byte_addresses: number[]; reads_per_master: number }
    | { kind: "ordered_read_segments"; per_master: { master: number; segments: { byte_address: number; count: number }[] }[] }
    | { kind: "read_sequences"; per_master: { master: number; ops: ReadOp[] }[] };
}
export interface Operation extends Required<ReadOp> { master: number; index: number }
export interface RunOptions { timeout: number; stalls: number[][]; inject: string | null; sv_inject: number }
export interface Check {
  schema_version: number; checker: string; status: string; functional_valid: boolean;
  workload_digest: string; expected_operations: number; makespan: number | null;
  makespan_from_events_unvalidated: number | null; metric_id: string;
  accepted?: number; completed?: number; offered?: number; monitor_failures?: number;
  violation_counts: Record<string, number>; violations: { code: string; detail: string }[];
  summary_agreement: Record<string, boolean | string> | null;
}
export interface Summary { exit_status: string; makespan: number | null; accepted: number; completed: number; [k: string]: unknown }
export interface RecordedRun {
  config_id: string; run_id: string; options: RunOptions; reference_epoch: string;
  expected: { events_sha256: string; check: Check };
}
export interface ReplayRecord {
  id: string; title: string; kind: "published" | "reduced" | "map";
  workload: Workload; workload_digest: string; rtl: Record<Design, RecordedRun>;
  models: Record<string, string>; expected_models: Record<string, Check>;
}
export interface Asset { url: string; sha256: string; count?: number }
export interface ModuleAsset {
  js_url: string; wasm_url: string; js_sha256: string; wasm_sha256: string;
  native_reference: Record<string, string>; build_key: string; wasm_bytes: number; gzip_bytes: number;
}
export interface ModelSpec { model_id: string; model_digest: string; config_id: string; args: string[]; resp_lat: number }
export interface BrowserManifest {
  schema_version: number; build_id: string; manifest_digest: string; reference_epoch: string;
  toolchain: Record<string, unknown>; modules: Record<string, ModuleAsset>; models: Record<string, ModelSpec>;
  default_models: { A: string; parent: string; repaired: string }; curated: Asset; map: Asset;
  runtime_source: Asset;
}
export interface Verdict {
  verdict: string; model_choice?: Design; rtl_best?: Design; extra_cycles?: number;
  denominator_cycles?: number; model_margin_met?: boolean; rtl_margin_met?: boolean;
}
export interface Execution {
  config_id: string; model_id?: string; run_id: string; options: RunOptions;
  events_sha256: string; check: Check; summary: Summary;
  hash_match: boolean | null; check_match: boolean | null; timeline?: Timeline;
}
export interface Receipt {
  schema_version: 1; kind: "rift-browser-receipt"; build_id: string; manifest_digest: string;
  reference_epoch: string; workload: Workload; workload_digest: string; replay_id: string | null;
  modules: Record<string, { wasm_sha256: string; js_sha256: string; build_key: string }>;
  models: Record<string, { model_id: string; model_digest: string }>;
  executions: Record<string, Omit<Execution, "timeline">>; discovery_credit: 0;
}
export interface RunResult {
  job_id: number; build_id: string; workload_digest: string; workload: Workload;
  executions: Record<string, Execution>; verdicts: Record<string, Verdict>; receipt: Receipt;
  elapsed_ms: number; loading_ms: number; simulation_ms: number; checking_ms: number;
}
export type WorkerRequest = { type: "run"; job_id: number; manifest: BrowserManifest; workload: Workload; replay?: ReplayRecord };
export type WorkerReply = { type: "progress"; job_id: number; message: string } |
  { type: "result"; job_id: number; result: RunResult } | { type: "error"; job_id: number; error: string };
