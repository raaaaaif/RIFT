import type { BrowserManifest, ReplayRecord, RunResult, WorkerReply, Workload } from "./types";

/** One active worker, reusable compiled modules, fresh simulator instances per run. */
export class BrowserRunner {
  private worker: Worker | null = null;
  private sequence = 0;
  private reject: ((reason: Error) => void) | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  cancel() {
    ++this.sequence;
    this.worker?.terminate(); this.worker = null;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.reject?.(new DOMException("Execution cancelled.", "AbortError")); this.reject = null;
  }
  run(manifest: BrowserManifest, workload: Workload, progress: (message: string) => void, replay?: ReplayRecord): Promise<RunResult> {
    if (this.reject) this.cancel();
    const job_id = ++this.sequence;
    this.worker ??= new Worker(new URL("./engine.worker.ts", import.meta.url), { type: "module" });
    const worker = this.worker;
    return new Promise((resolve, reject) => {
      this.reject = reject;
      this.timer = setTimeout(() => {
        this.reject = null; this.cancel();
        reject(new Error("Loading or execution exceeded 60 seconds. Check your connection and retry, or try a smaller workload."));
      }, 60_000);
      worker.onmessage = (event: MessageEvent<WorkerReply>) => {
        const reply = event.data;
        if (reply.job_id !== this.sequence) return;
        if (reply.type === "progress") { progress(reply.message); return; }
        if (this.timer) clearTimeout(this.timer);
        this.timer = null; this.reject = null;
        if (reply.type === "result") resolve(reply.result);
        else reject(new Error(reply.error));
      };
      worker.onerror = (event) => {
        if (job_id !== this.sequence) return;
        if (this.timer) clearTimeout(this.timer);
        this.timer = null; this.reject = null; worker.terminate(); this.worker = null;
        reject(new Error(event.message || "The browser simulator stopped. Retry or use the recorded evidence."));
      };
      worker.postMessage({ type: "run", job_id, manifest, workload, replay });
    });
  }
}
