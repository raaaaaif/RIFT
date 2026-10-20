import { createContext, useContext, type ReactNode } from "react";
import type { CaseView } from "../types";
import type { Tone } from "../logic";

export const TERMS: Record<string, [string, string]> = {
  makespan: ["Completion cycles (makespan)", "Simulated cycles from the common first request-release cycle through the last valid response, counting both endpoints. Cycles are at a common abstract clock; they do not establish silicon speed, frequency or energy."],
  regret: ["Extra cost of the model's choice (selection regret)", "The reference cost of the design the model selected minus the best reference cost, divided by that best cost. It describes this decision on this workload, not a deployment-wide average."],
  margin: ["Reversal margin", "Each ordering difference must reach the larger of 2 cycles or 2% of that domain's smaller cost, independently for the model and for the reference. Opposite signs alone are not enough."],
  rtl: ["RTL reference", "The pinned pulp-platform tcdm_interconnect register-transfer-level design, simulated with Verilator through RIFT's wrapper and C++ driver. It is a reference implementation, not fabricated silicon."],
  route: ["Internal route contention", "In the radix-4 butterfly, initiators 2k and 2k+1 enter the same first-stage router. Two requests whose bank IDs share bits [3:2] compete for one router output even when their final banks differ. A bank-only model does not see that wait."],
  epoch: ["Reference epoch", "A digest of every reference-affecting identity: pinned RTL commits, wrapper, driver, memory oracle, sampling convention and toolchain lock. Changing any of them starts a new epoch and invalidates old comparisons."],
  prefix: ["History-preserving reduction", "Every reduction candidate is replayed from the 4-cycle reset, because removing earlier requests changes arbiter and LFSR history. A candidate is kept only if a fresh RTL replay is still a strict reversal."],
  withheld: ["Independent evaluation", "A separate verifier runs the candidate model against a sealed held-out basket and fresh RTL replays, under a frozen acceptance contract. The repair process never sees that basket."],
  tie: ["Frozen tie policy", "When a model predicts equal costs, it selects the first design in the admitted order (A). That choice can still carry regret, but a tie is never presented as a strict reversal."],
  credit: ["Discovery credit", "Supplied calibration programs (L, B, M) earn zero discovery credit. Credit counts only strict reversals found by a search arm within its budget."],
};

export interface UiCtx {
  openTerm: (key: string) => void;
  inspect: (tab: "overview" | "calculation" | "record") => void;
  gotoStage: (n: number, focusHeading?: boolean) => void;
  selectOp: (op: string | null) => void;
  op: string | null;
}
export const Ctx = createContext<UiCtx>({ openTerm: () => {}, inspect: () => {}, gotoStage: () => {}, selectOp: () => {}, op: null });
export const useUi = () => useContext(Ctx);

export function Term({ k, children }: { k: string; children?: ReactNode }) {
  const { openTerm } = useUi();
  const label = children ?? TERMS[k]?.[0] ?? k;
  return (
    <button type="button" className="term" onClick={() => openTerm(k)} aria-label={`Explain ${typeof label === "string" ? label : TERMS[k]?.[0] ?? k}`}>
      {label}
    </button>
  );
}

export function Badge({ tone = "neutral", children }: { tone?: Tone | "ok"; children: ReactNode }) {
  return <span className={`badge ${tone === "neutral" ? "" : tone}`}>{children}</span>;
}

const PROVENANCE_LABEL: Record<string, string> = {
  SUPPLIED_CALIBRATION: "Supplied calibration · zero discovery credit",
  AUTHORED_DEFECT: "Authored model defect",
  CLEAN_CONTROL: "Clean control",
  PERMITTED_APPROXIMATION: "Permitted approximation",
  INDEPENDENTLY_FOUND: "Independently found",
  RECONSTRUCTED_REGRESSION: "Reconstructed regression",
};
const SCOPE_LABEL: Record<string, string> = {
  STRESS_WITNESS: "Stress witness · 1 workload", INSTRUMENT_TEST: "Instrument test · 1 workload", REPRESENTATIVE_BASKET: "Representative basket",
  SEALED_FINAL: "Sealed final", TRAINING: "Training", ADAPTIVE_VALIDATION: "Adaptive validation",
};
export const provenanceLabel = (p: string) => PROVENANCE_LABEL[p] ?? p;
export const scopeLabel = (s: string) => SCOPE_LABEL[s] ?? s;

export function StageHead({ kicker, tag, tone, title, lead }: { kicker: string; tag: string; tone: Tone; title: string; lead: string }) {
  return (
    <>
      <div className="stage-meta">
        <span className="eyebrow">{kicker}</span>
        <span className={`tag ${tone === "neutral" ? "" : tone}`}>{tag} · executed</span>
      </div>
      <h1 id="stage-heading" tabIndex={-1}>{title}</h1>
      <p className="lead" dangerouslySetInnerHTML={{ __html: lead }} />
    </>
  );
}

export function ScopeBar({ cv }: { cv: CaseView }) {
  const c = cv.comparison;
  const patch = cv.repair ? cv.repair.lifecycle.replaceAll("_", " ").toLowerCase() : "no candidate";
  return (
    <div className="scope-bar" role="group" aria-label="Context that changes the meaning of this result">
      <span><strong>Scope</strong> {scopeLabel(cv.evaluation_scope)} · 2 designs · 16 KiB each</span>
      <span><strong>Metric</strong> <Term k="makespan">Completion cycles</Term> · lower is better</span>
      <span><strong>Evidence</strong> Executed: <Term k="rtl">RTL reference</Term> + fast model</span>
      <span><strong>Reference</strong> {cv.reference_validity === "VALIDATED_FOR_CONTRACT" ? "validated for contract" : cv.reference_validity.toLowerCase().replaceAll("_", " ")} · <Term k="epoch">{c.reference_epoch}</Term></span>
      <span><strong>Provenance</strong> {provenanceLabel(cv.case_provenance)}</span>
      <span><strong>Patch</strong> {patch}</span>
    </div>
  );
}

export function Section({ title, stamp, sub, children, id }: { title: string; stamp?: string; sub?: ReactNode; children: ReactNode; id?: string }) {
  return (
    <section className="panel" aria-labelledby={id ? `${id}-h` : undefined} id={id}>
      <div className="panel-head">
        <div>
          <h2 id={id ? `${id}-h` : undefined}>{title}</h2>
          {sub ? <p>{sub}</p> : null}
        </div>
        {stamp ? <span className="stamp">{stamp}</span> : null}
      </div>
      {children}
    </section>
  );
}
