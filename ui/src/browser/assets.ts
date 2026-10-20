import { canonical, sha256 } from "./contracts";
import type { Asset, BrowserManifest, ReplayRecord } from "./types";

export async function verifiedBytes(asset: Asset, wasm = false): Promise<Uint8Array> {
  const url = new URL(asset.url, location.origin);
  if (url.origin !== location.origin || !url.pathname.startsWith("/browser/")) throw new Error("Unexpected browser artifact location.");
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Could not load the simulator (${response.status}). Retry when connected.`);
  if (wasm && !response.headers.get("content-type")?.includes("application/wasm")) throw new Error("The simulator file is missing or has the wrong content type. Reload this page.");
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.length > 25 * 1024 * 1024) throw new Error("Browser artifact exceeds the size limit.");
  if (wasm && [0, 97, 115, 109].some((v, i) => bytes[i] !== v)) throw new Error("The server did not return a WebAssembly module. Reload this page.");
  if (await sha256(bytes) !== asset.sha256) throw new Error("Browser artifact fingerprint differs from this release. Reload this page.");
  return bytes;
}
export async function loadManifest(expectedEpoch?: string): Promise<BrowserManifest> {
  const response = await fetch("/browser/manifest.json", { cache: "no-cache" });
  if (!response.ok) throw new Error("Browser execution is unavailable in this deployment. Recorded evidence remains available.");
  const manifest = await response.json() as BrowserManifest;
  if (import.meta.env.PROD && manifest.manifest_digest !== __RIFT_BROWSER_MANIFEST__) throw new Error("The page and browser runtime belong to different releases. Reload this page.");
  if (manifest.schema_version !== 1 || !manifest.build_id || !manifest.modules || !manifest.curated) throw new Error("Unsupported browser release manifest. Reload this page.");
  const { manifest_digest, ...body } = manifest;
  if (await sha256(new TextEncoder().encode(canonical(body))) !== manifest_digest) throw new Error("Browser release manifest failed its integrity check.");
  if (expectedEpoch && manifest.reference_epoch !== expectedEpoch) throw new Error("Browser simulator and recorded evidence belong to different reference epochs. Reload this page.");
  return manifest;
}
export async function loadRecords(manifest: BrowserManifest, kind: "curated" | "map"): Promise<ReplayRecord[]> {
  const data = JSON.parse(new TextDecoder().decode(await verifiedBytes(manifest[kind]))) as { schema_version: number; build_id: string; records: ReplayRecord[] };
  if (data.schema_version !== 1 || data.build_id !== manifest.build_id) throw new Error("Replay inputs and simulator belong to different builds. Reload this page.");
  return data.records;
}
