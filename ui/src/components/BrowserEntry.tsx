import { Component, lazy, Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import type { CaseView } from "../types";

const BrowserLab = lazy(() => import("../browser/BrowserLab"));
export interface BrowserIntent { mode: "replay" | "sandbox"; preset?: string; case_id?: string }
class LoadBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? <p className="err-box" role="alert">The browser lab could not load. Reload to retry; the recorded evidence is still available.</p> : this.props.children; }
}

export function BrowserEntry({ cv, request }: { cv: CaseView; request?: BrowserIntent | null }) {
  const [intent, setIntent] = useState<BrowserIntent | null>(null);
  const region = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (request && request.case_id === cv.case_id) setIntent(request);
  }, [request, cv.case_id]);
  useEffect(() => {
    if (intent) { region.current?.focus({ preventScroll: true }); if (request === intent) region.current?.scrollIntoView({ behavior: "auto", block: "start" }); }
  }, [intent, request]);
  return <section className="browser-entry" aria-label="Execute the hardware in your browser">
    <div className="browser-entry-bar">
      <div><strong>Check it yourself.</strong><span> Execute the same RTL here, or change the traffic.</span></div>
      <div className="actions">
        <button className="btn compact" onClick={() => setIntent({ mode: "replay", preset: cv.case_id })}>Re-run in your browser</button>
        <button className="text-button" onClick={() => setIntent({ mode: "sandbox", preset: "pattern-m" })}>Can you change the winner? →</button>
      </div>
    </div>
    {intent ? <div ref={region} tabIndex={-1} className="browser-region" aria-label="Browser execution lab">
      <div className="browser-close"><span className="eyebrow">LIVE · ON YOUR DEVICE</span><button className="text-button" onClick={() => setIntent(null)}>Close browser lab</button></div>
      <LoadBoundary><Suspense fallback={<p role="status">Loading the browser lab…</p>}>
        <BrowserLab key={`${intent.mode}:${intent.preset}`} epoch={cv.reference_epoch} intent={intent} onSandbox={(preset) => setIntent({ mode: "sandbox", preset })} />
      </Suspense></LoadBoundary>
    </div> : null}
  </section>;
}
