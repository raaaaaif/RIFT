import { verifiedBytes } from "./assets";
import { canonical, classify, compile, compiledText, sha256, workloadDigest } from "./contracts";
import { checkEvents, type RawEvent } from "./checker";
import { buildTimeline } from "../replay";
import type { Execution, ModuleAsset, Receipt, RunOptions, RunResult, Summary, WorkerReply, WorkerRequest } from "./types";

interface Engine {
  FS: { writeFile(path: string, data: string): void; readFile(path: string): Uint8Array; readFile(path: string, options: { encoding: "utf8" }): string };
  callMain(args: string[]): number;
}
type Factory = (options: Record<string, unknown>) => Promise<Engine>;
const factories = new Map<string, Promise<{ factory: Factory; module: WebAssembly.Module }>>();
const send = (message: WorkerReply) => self.postMessage(message);

async function loadEngine(asset: ModuleAsset) {
  let ready = factories.get(asset.wasm_sha256 + asset.js_sha256);
  if (!ready) {
    ready = (async () => {
      const [js, wasm] = await Promise.all([
        verifiedBytes({ url: asset.js_url, sha256: asset.js_sha256 }),
        verifiedBytes({ url: asset.wasm_url, sha256: asset.wasm_sha256 }, true),
      ]);
      const url = URL.createObjectURL(new Blob([js as Uint8Array<ArrayBuffer>], { type: "text/javascript" }));
      try {
        const [imported, module] = await Promise.all([import(/* @vite-ignore */ url), WebAssembly.compile(wasm as Uint8Array<ArrayBuffer>)]);
        return { factory: imported.default as Factory, module };
      } finally { URL.revokeObjectURL(url); }
    })();
    factories.set(asset.wasm_sha256 + asset.js_sha256, ready);
    ready.catch(() => factories.delete(asset.wasm_sha256 + asset.js_sha256));
  }
  return ready;
}
const defaults: RunOptions = { timeout: 4096, stalls: [], inject: null, sv_inject: 0 };
export function rtlArgs(runId: string, options: RunOptions): string[] {
  return ["--run-id", runId, "--timeout", String(options.timeout), ...options.stalls.flatMap(s => ["--stall", s.join(":")]),
    ...(options.inject ? ["--inject", options.inject] : []), ...(options.sv_inject ? ["--sv-inject", String(options.sv_inject)] : [])];
}

async function execute(request: WorkerRequest): Promise<RunResult> {
  const start = performance.now(), { manifest, workload, replay, job_id } = request;
  if (manifest.schema_version !== 1) throw new Error("Unsupported browser build.");
  const per = compile(workload), digest = await workloadDigest(workload), text = compiledText(per, digest);
  if (replay && (replay.workload_digest !== digest || canonical(replay.workload) !== canonical(workload))) throw new Error("Replay workload differs from its recorded input.");
  const ids = { A: replay?.models.A ?? manifest.default_models.A,
    parent: replay?.models.B ?? replay?.models.parent ?? manifest.default_models.parent,
    repaired: manifest.default_models.repaired };
  const executions: Record<string, Execution> = {};
  let loading = 0, simulation = 0, checking = 0;
  const jobs = [
    ...(["A", "B"] as const).map(d => ({ key: `rtl-${d}`, config: d === "A" ? "lic8x8" : "bfly4_8x16", model: null, recorded: replay?.rtl[d] })),
    ...Object.entries(ids).map(([key, id]) => ({ key: `model-${key}`, config: manifest.models[id]?.config_id, model: id, recorded: undefined })),
  ];
  for (const job of jobs) {
    if (!job.config) throw new Error("Unsupported model in this replay.");
    const spec = job.model ? manifest.models[job.model] : null;
    const asset = manifest.modules[job.model ? "fastmodel" : job.config];
    if (!asset) throw new Error("Simulator is absent from this release.");
    send({ type: "progress", job_id, message: `Loading ${job.model ? "fast model" : job.config === "lic8x8" ? "crossbar RTL" : "butterfly RTL"}…` });
    const loadStart = performance.now();
    const { factory, module } = await loadEngine(asset);
    const logs: string[] = [];
    const engine = await factory({
      noInitialRun: true, print: (s: string) => logs.push(s), printErr: (s: string) => logs.push(s),
      instantiateWasm(imports: WebAssembly.Imports, receive: (instance: WebAssembly.Instance, module: WebAssembly.Module) => void) {
        // A compiled Module instantiates synchronously; errors reject the factory
        // immediately instead of leaving its startup promise pending.
        receive(new WebAssembly.Instance(module, imports), module);
        return {};
      },
    });
    loading += performance.now() - loadStart;
    const options = job.recorded?.options ?? defaults;
    const runId = job.recorded?.run_id ?? (job.model ? "fastmodel-0" : `browser-${digest.slice(7, 23)}-${job.config}`);
    engine.FS.writeFile("/workload.txt", text);
    const paths = ["--workload", "/workload.txt", "--summary", "/summary.json", "--events", "/events.jsonl"];
    engine.FS.writeFile("/batch.txt", "/workload.txt /summary.json /events.jsonl\n");
    send({ type: "progress", job_id, message: `Executing ${job.key}…` });
    const simStart = performance.now();
    const code = engine.callMain(spec ? [...spec.args, "--batch", "/batch.txt"] : [...paths, ...rtlArgs(runId, options)]);
    simulation += performance.now() - simStart;
    if (code !== 0) throw new Error(`${job.key} stopped with exit ${code}: ${logs.slice(-2).join(" ")}`);
    const checkStart = performance.now();
    const bytes = engine.FS.readFile("/events.jsonl"), eventsHash = await sha256(bytes);
    const events = new TextDecoder().decode(bytes).trim().split("\n").filter(Boolean).map(line => JSON.parse(line)) as RawEvent[];
    const summary = JSON.parse(engine.FS.readFile("/summary.json", { encoding: "utf8" })) as Summary;
    const check = checkEvents(per, digest, job.config === "lic8x8" ? 8 : 16, events, summary, spec ? "model" : "rtl", options.timeout, spec?.resp_lat ?? 1);
    const expected = job.recorded?.expected;
    executions[job.key] = { config_id: job.config, ...(job.model ? { model_id: job.model } : {}), run_id: runId,
      options, events_sha256: eventsHash, check, summary,
      hash_match: expected ? expected.events_sha256 === eventsHash : null,
      check_match: expected ? expected.check.status === check.status && expected.check.makespan === check.makespan && canonical(expected.check.violation_counts) === canonical(check.violation_counts) : null,
      ...(check.functional_valid ? { timeline: buildTimeline({ events }) } : {}) };
    checking += performance.now() - checkStart;
  }
  const rtl = { A: executions["rtl-A"].check, B: executions["rtl-B"].check };
  const verdicts = Object.fromEntries(["parent", "repaired"].map(k => [k, classify({ A: executions["model-A"].check, B: executions[`model-${k}`].check }, rtl)]));
  const receipt: Receipt = { schema_version: 1, kind: "rift-browser-receipt", build_id: manifest.build_id, manifest_digest: manifest.manifest_digest,
    reference_epoch: manifest.reference_epoch, workload, workload_digest: digest, replay_id: replay?.id ?? null, discovery_credit: 0,
    modules: Object.fromEntries(Object.entries(manifest.modules).map(([k, m]) => [k, { wasm_sha256: m.wasm_sha256, js_sha256: m.js_sha256, build_key: m.build_key }])),
    models: Object.fromEntries(Object.entries(ids).map(([k, id]) => [k, { model_id: id, model_digest: manifest.models[id].model_digest }])),
    executions: Object.fromEntries(Object.entries(executions).map(([k, { timeline: _timeline, ...r }]) => [k, r])) };
  return { job_id, build_id: manifest.build_id, workload_digest: digest, workload, executions, verdicts, receipt,
    elapsed_ms: performance.now() - start, loading_ms: loading, simulation_ms: simulation, checking_ms: checking };
}

self.onmessage = async (event: MessageEvent<WorkerRequest>) => {
  const request = event.data;
  if (request.type !== "run") return;
  try { send({ type: "result", job_id: request.job_id, result: await execute(request) }); }
  catch (error) { send({ type: "error", job_id: request.job_id, error: error instanceof Error ? error.message : String(error) }); }
};
