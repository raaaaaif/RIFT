import type { CaseView, PatchReview } from "../types";
import { pct, wording } from "../logic";
import { Term, useUi } from "./common";
import { DotPlot, ModelDiagram } from "./Charts";
import { MapLink } from "./DecisionMap";

const RULES: Record<string, string> = {
  R1: "Runs everywhere", R2: "Fewer wrong decisions", R3: "No new mistakes", R4: "Still fast", R5: "Fixes every witness", R6: "Edits only the model",
};
const RULE_TEXT: Record<string, string> = {
  R1: "No model error or timeout on any held-out workload",
  R2: "Fewer strict ranking reversals than the original model across the basket",
  R3: "No held-out workload where the original was right and the candidate is wrong",
  R4: "Warm runtime at most 3× the original's",
  R5: "Every discovery witness resolved on fresh RTL replays",
  R6: "Only the editable model specification changed; no workload-specific rules",
};

export function specDiff(p: PatchReview): string[] {
  const parent = JSON.stringify({ family: p.patch.parent.family, params: p.patch.parent.params }, null, 2).split("\n");
  const cand = JSON.stringify({ family: p.patch.candidate.family, params: p.patch.candidate.params }, null, 2).split("\n");
  return [...parent.map((l) => `- ${l}`), ...cand.map((l) => `+ ${l}`)];
}

function semantic(p: PatchReview): string {
  const params = p.patch.candidate.params as { links?: number[][] };
  if (p.patch.candidate.family === "shared_link" && params.links) return `each pair of initiators shares one link per group of ${1 << params.links[0][1]} banks`;
  return p.semantic_change;
}

export function RepairView({ cv, controls }: { cv: CaseView; controls: { label: string; status: string; failed: string[] }[] }) {
  const { gotoStage, openTerm } = useUi();
  const wd = wording(cv);
  const p = cv.repair;
  if (!p) {
    return (
      <>
        <div className="stage-meta"><span className="eyebrow">04 / Repair</span><span className={`tag ${wd.tone}`}>{wd.tag} · executed</span></div>
        <h1 id="stage-heading" tabIndex={-1} className="hero-title">No repair needed for this case.</h1>
        <p className="hero-sub">There is no strict reversal here, so no model change was proposed. The original model stays in use.</p>
        <section className="panel"><div className="empty-state"><span className="badge-outline">NO CANDIDATE</span><h3>Independent evaluation has not run</h3><p>Repairs are proposed only for validated reversals. Study results are in Evidence.</p><button className="btn" onClick={() => gotoStage(4)}>Open the evidence</button></div></section>
      </>
    );
  }
  const v = p.verification;
  const accepted = p.lifecycle === "ACCEPTED_UNDER_CONTRACT";
  const rejected = p.lifecycle === "REJECTED";
  const links = (p.patch.candidate.params as { links?: number[][] }).links ?? [];
  const v2 = p.verification_v2;
  const fams = [...(v ? Object.values(v.families) : []), ...(v2 ? Object.values(v2.families) : [])];
  const tot = fams.reduce((a, f) => ({ pr: a.pr + f.parent_reversals, cr: a.cr + f.candidate_reversals, n: a.n + f.workloads }), { pr: 0, cr: 0, n: 0 });
  const passed = v ? Object.values(v.rules).filter((r) => r.passed).length : 0;
  const famCount = (pred: (f: (typeof fams)[number]) => boolean) => fams.filter(pred).length;
  const worse = famCount((f) => f.candidate_mean_regret > f.parent_mean_regret);
  const silent = famCount((f) => f.parent_reversals === 0 && f.parent_wrong_choices === 0);
  const regressions = [v, v2].every((x) => !x || x.rules.R3?.passed);
  const strength = [
    `${tot.pr} of ${tot.n} held-out workloads tripped the original model; after the fix ${tot.cr} do${regressions ? ", with no new reversals" : ""}.`,
    silent ? `${silent} of ${fams.length} families never confused the original model, so they test only for regressions.` : "",
    worse ? `${worse} ${worse === 1 ? "family shows" : "families show"} higher mean regret after the fix.` : "",
    v2 ? "Basket v2 was defined after v1's result; the candidate was frozen before either ran." : "",
  ].filter(Boolean).join(" ");
  const dev = p.development_result;
  return (
    <>
      <div className="stage-meta"><span className="eyebrow">04 / Repair</span><span className={`tag ${accepted ? "teal" : rejected ? "error" : "caution"}`}>{accepted ? "Accepted under contract" : rejected ? "Rejected" : "Pending"} · executed</span></div>
      <h1 id="stage-heading" tabIndex={-1} className="hero-title">{accepted ? "The fix: model the shared routes. It passed an independent test." : rejected ? "The proposed fix failed the independent test." : "A fix is proposed; independent evaluation pending."}</h1>
      <p className="hero-sub">Proposed change to the butterfly model: <b>{semantic(p)}</b>. Chosen by a deterministic search over allowed model edits, then judged by a separate verifier on a sealed set of new workloads the search never saw.</p>

      <div className="model-pair">
        <ModelDiagram links={[]} title={`Before · ${p.parent_models.B}`} added={false} />
        <div className="model-arrow" aria-hidden="true">→</div>
        <ModelDiagram links={links} title={`After · ${p.candidate_model_id}`} added={true} />
      </div>
      <MapLink cv={cv} />

      <div className="big-row">
        {dev ? <div className="big"><span>Discovery witnesses still wrong</span><strong>{dev.parent.unresolved_witnesses} → {dev.candidate.unresolved_witnesses}</strong><em>development data</em></div> : null}
        {v ? <div className="big"><span>Held-out strict reversals</span><strong>{tot.pr} → {tot.cr}</strong><em>{tot.n} never-seen workloads{v2 ? ", 2 baskets" : ""}</em></div> : null}
        {v && v.runtime.parent_seconds ? <div className="big"><span>Runtime vs original</span><strong>{((v.runtime.candidate_seconds ?? 0) / v.runtime.parent_seconds).toFixed(2)}×</strong><em>limit 3×</em></div> : null}
        {v ? <div className={`big ${accepted ? "ok" : "bad"}`}><span>Acceptance gates</span><strong>{passed}/6</strong><em>{accepted ? "accepted" : "rejected"}</em></div> : null}
      </div>

      {v ? (
        <section className="panel" aria-labelledby="gates-h">
          <div className="panel-head"><div><h2 id="gates-h">Independent verification</h2><p>Contract {v.contract_id} on basket {v.basket_id}. <Term k="withheld">How this works</Term></p></div><span className="stamp">SEALED · SEPARATE PROCESS</span></div>
          <div className="panel-body">
            <div className="gates">{Object.keys(RULES).map((r) => { const rule = v.rules[r]; return (
              <div key={r} className={`gate-pill ${rule?.passed ? "ok" : "bad"}`} title={`${RULE_TEXT[r]}: ${typeof rule?.detail === "string" ? rule.detail : JSON.stringify(rule?.detail)}`}>
                <span className="gp-mark">{rule?.passed ? "✓" : "✗"}</span><strong>{RULES[r]}</strong><span className="gp-detail">{typeof rule?.detail === "string" ? rule.detail : ""}</span></div>); })}</div>
            {v.heldout_rows?.length ? (<><h3 className="sub-h">Held-out basket v1 · {v.status === "ACCEPTED_UNDER_CONTRACT" ? "accepted" : "rejected"} · every workload, before and after</h3><DotPlot rows={v.heldout_rows} /></>) : null}
            {v2?.heldout_rows?.length ? (<><h3 className="sub-h">Held-out basket v2 (stress families, fresh seeds) · {v2.status === "ACCEPTED_UNDER_CONTRACT" ? "accepted" : "rejected"}</h3><DotPlot rows={v2.heldout_rows} /></>) : null}
            <div className="notice" style={{ marginTop: 14 }}><strong>How strong is this?</strong> {strength}</div>
          </div>
        </section>
      ) : <section className="panel"><div className="empty-state"><h3>Independent evaluation has not run</h3><p>Required next step: <span className="mono">rift verify --submission</span></p></div></section>}

      {controls.length ? (
        <section className="panel" aria-labelledby="ctl-h">
          <div className="panel-head"><div><h2 id="ctl-h">The same verifier rejected these</h2><p>Proof that passing is not automatic.</p></div></div>
          <div className="panel-body control-cards">{controls.map((c) => (
            <div key={c.label} className="control-card"><span className={`badge ${c.status === "ACCEPTED_UNDER_CONTRACT" ? "ok" : "error"}`}>{c.status === "ACCEPTED_UNDER_CONTRACT" ? "accepted" : "rejected"}</span>
              <strong>{c.label.replace(/^(negative control|conventional baseline): /, "")}</strong>
              <span>{c.label.startsWith("conventional") ? "conventional baseline" : "negative control"} · failed {c.failed.map((r) => RULES[r] ?? r).join(", ")}</span></div>))}</div>
        </section>
      ) : null}

      <details className="table-details panel" style={{ padding: "0 4px" }}><summary>The exact model change (diff, digests) and all {p.candidate_table.length} candidates tried</summary>
        <div className="panel-body">
          <pre className="code" aria-label="Specification diff">{specDiff(p).map((l, i) => <span key={i} className={l.startsWith("-") ? "del" : "add"}>{l + "\n"}</span>)}</pre>
          <dl className="kv-wide"><dt>Parent digest</dt><dd className="mono">{p.parent_model_digest}</dd><dt>Candidate digest</dt><dd className="mono">{p.candidate_model_digest}</dd><dt>Patch digest</dt><dd className="mono">{p.patch_digest}</dd><dt>Unchanged</dt><dd>RTL, driver, oracle, metric and epoch {cv.reference_epoch}</dd></dl>
          <div className="table-wrap"><table className="program"><thead><tr><th>Edit</th><th className="numeric">Witnesses still wrong</th><th className="numeric">Reversals</th><th className="numeric">MAE B</th></tr></thead>
            <tbody>{p.candidate_table.map((t) => <tr key={t.edit} className={t.edit === p.semantic_change ? "selected" : ""}><td>{t.edit}</td><td className="numeric">{t.unresolved_witnesses ?? "—"}</td><td className="numeric">{t.strict_reversals ?? "—"}</td><td className="numeric">{t.mae_B !== undefined ? t.mae_B.toFixed(2) : "invalid"}</td></tr>)}</tbody></table></div>
          {dev ? <p className="axis-note">Development: mean regret {pct(dev.parent.mean_regret, 2)} → {pct(dev.candidate.mean_regret, 2)}; butterfly MAE {dev.parent.mae_B.toFixed(2)} → {dev.candidate.mae_B.toFixed(2)} cycles.</p> : null}
        </div></details>
      <div className="actions"><button className="btn primary" onClick={() => gotoStage(4)}>Inspect the evidence →</button><button className="btn" onClick={() => openTerm("withheld")}>What independent evaluation means</button></div>
    </>
  );
}
