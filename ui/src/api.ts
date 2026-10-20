import type { CaseSummary, CaseView, DecisionMapView, DiagnosticView, ProjectRecord, Specimens, TraceSelection } from "./types";

/**
 * Two transports with one contract:
 *  - live: the local `rift serve` read API under /api (supports budgeted replay)
 *  - static: published JSON snapshots under /data (Cloudflare Pages, any static host)
 * `rift serve` marks index.html with <meta name="rift-transport" content="live">;
 * a static host serves the file unchanged, so no API request is ever made there.
 */
const resolved: "live" | "static" =
  import.meta.env.DEV || document.querySelector<HTMLMetaElement>('meta[name="rift-transport"]')?.content === "live" ? "live" : "static";
const mode = Promise.resolve(resolved);

function detect(): Promise<"live" | "static"> {
  return mode;
}

async function get<T>(livePath: string, staticPath: string): Promise<T> {
  const m = await detect();
  const path = m === "live" ? livePath : staticPath;
  // One bounded retry for a dropped connection; HTTP and JSON errors remain visible.
  const request = () => fetch(path, { headers: { Accept: "application/json" } });
  const r = await request().catch(async () => {
    await new Promise(resolve => setTimeout(resolve, 100));
    return request();
  });
  if (!r.ok) {
    let msg = `${r.status}`;
    try { msg = (await r.json()).error ?? msg; } catch { /* keep status */ }
    throw new Error(`${path}: ${msg}`);
  }
  return (await r.json()) as T;
}

const traceCache = new Map<string, Promise<TraceSelection>>();
let mapCache: Promise<DecisionMapView | null> | null = null;
const enc = encodeURIComponent;

export const api = {
  mode: detect,
  cases: () => get<{ cases: CaseSummary[]; run_controls_enabled: boolean; mode?: string }>("/api/cases", "/data/cases.json"),
  caseView: (id: string) => get<CaseView>(`/api/cases/${enc(id)}`, `/data/case/${enc(id)}.json`),
  project: () => get<ProjectRecord>("/api/project", "/data/project.json"),
  specimens: () => get<Specimens>("/api/specimens", "/data/specimens.json"),
  diagnostic: (id: string) => get<DiagnosticView | null>(`/api/diag/${enc(id)}`, `/data/diag/${enc(id)}.json`).catch(() => null),
  map: () => (mapCache ??= get<DecisionMapView>("/api/map", "/data/map.json").catch(() => {
    // Do not permanently cache a failed transfer as an absent investigation.
    mapCache = null;
    return null;
  })),
  trace: (runId: string) => {
    if (!traceCache.has(runId)) traceCache.set(runId, get<TraceSelection>(`/api/trace/${enc(runId)}`, `/data/trace/${enc(runId)}.json`).catch(error => { traceCache.delete(runId); throw error; }));
    return traceCache.get(runId)!;
  },
  artifactUrl: (runId: string, file: string) => {
    const m = resolved;
    return m === "live" ? `/api/artifacts/${enc(runId)}/${file.split("/").map(enc).join("/")}` : `/data/artifacts/${enc(runId)}/${file.split("/").map(enc).join("/")}`;
  },
  replay: async (caseId: string, budget: number) => {
    const r = await fetch("/api/replay", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ case_id: caseId, budget_rtl_executions: budget }) });
    const body = await r.json();
    if (!r.ok) throw new Error(body.error ?? String(r.status));
    return body as Job;
  },
  jobs: () => get<{ run_controls_enabled: boolean; jobs: Job[] }>("/api/jobs", "/data/cases.json"),
};

export interface Job {
  job_id: string; case_id: string; state: "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED"; budget_rtl_executions: number; used_rtl_executions: number;
  result: null | { rtl_run_ids: Record<string, string>; rtl_costs: Record<string, number | null>; rtl_status: Record<string, string>; verdict_against_recorded_model: string | null; matches_recorded_reference: boolean };
  error: string | null;
}
