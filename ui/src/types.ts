// Frozen presentation contracts (schema_version 1), mirroring rift/presentation/adapter.py.

export type Design = "A" | "B";
export type Costs = Record<string, number>;

export interface Fraction { numerator: number; denominator: number; decimal: number }

export interface Margin {
  absolute_cycles: number; relative: string; min_cost: number; relative_term: string;
  threshold: string; threshold_decimal: number; met: boolean;
}

export interface ComparisonView {
  schema_version: 1;
  comparison_run_id: string;
  verdict: string;
  blocking_reason?: string | null;
  admitted_order: Design[];
  tie_policy: string;
  metric_id: string;
  model_costs: Costs | null;
  rtl_costs: Costs | null;
  model_status: Record<string, string> | null;
  rtl_status: Record<string, string> | null;
  dM: number | null; dR: number | null;
  model_margin: Margin | null; rtl_margin: Margin | null;
  model_choice: Design | null; rtl_best: Design | null;
  selection: { chosen: Design; reference_best: Design; extra_cycles: number; denominator_cycles: number; regret: Fraction } | null;
  designs: Record<string, { config_id: string; config_digest: string; descriptive_name: string }>;
  models: Record<string, { model_id: string; model_digest: string; contract: { promise: string; scope: string; declared_omissions?: string[] } }>;
  rtl_run_ids: Record<string, string>; model_run_ids: Record<string, string>;
  reference_epoch: string; epochs_consistent: boolean; workload_digest: string;
  provenance: string; scope: string; discovery_credit: number;
  integrity_errors: string[]; display_blocked?: boolean;
  model_predictions?: Record<string, { status: string; makespan: number | null }>;
  rtl_observations?: Record<string, { status: string; makespan: number | null; violations: string[] }>;
}

export interface ClaimView {
  schema_version: 1; claim_id: string; case_id: string; reference_epoch: string; claim_kind: string; statement: string;
  evidence_basis: string; observation_role: string; scope: string; metric_id: string; direction: string;
  display_eligibility: string; artifact_ids: string[]; limitations: string[];
}

export interface Run { byte_address: number; word: number; release: string; gap: number; count: number; first_index: number; last_index: number;
  mapping: Record<string, { bank: number; row: number }> }

export interface WorkloadView {
  schema_version: 1; workload_digest: string; label: string | null; program_kind: string; arrival_policy: string; total_operations: number;
  initiators: { master: number; operations: number; runs: Run[]; op_ids: string[] }[];
  capacity_words: number; held_constant: string[];
  designs: Record<string, { config_id: string; topology: string; banks: number; initiators: number; rows_per_bank: number; descriptive_name: string }>;
  workload: unknown;
}

export interface ArtifactLink {
  schema_version: 1; artifact_id: string; kind: string; role: string; observation_role?: string; evidence_basis: string; status?: string;
  manifest_digest: string; path: string; files: { name: string; sha256: string; bytes: number }[]; supports: string[];
}

export interface Mechanism {
  role: string; hypothesis: string;
  prediction_before_execution: { source: string; evidence_basis: string; predicted_active_acceptance_windows: Record<string, number> };
  observations: { statement: string; artifact: string | null }[];
  alternatives: { explanation: string; status: string; why: string }[];
  internal_activity: string;
}

export interface Rule { passed: boolean; detail: unknown; regressed_workloads?: unknown[]; ratio?: number | null }

export interface PatchReview {
  schema_version: 1; repair_id: string; case_id: string; candidate_model_id: string; candidate_model_digest: string;
  parent_models: Record<string, string>; parent_model_digest: string;
  patch: { editable_design: string; allowed_surface: string; parent: { model_id: string; family: string; params: unknown }; candidate: { model_id: string; family: string; params: unknown; resp_lat?: number }; semantic_change: string };
  patch_digest: string; semantic_change: string;
  development_result: { parent: Record<string, number>; candidate: Record<string, number> } | null;
  training_evidence: Record<string, unknown>;
  candidate_table: { edit: string; family: string; complexity: number; valid?: boolean; strict_reversals?: number; wrong_choices?: number; mean_regret?: number; mae_B?: number; unresolved_witnesses?: number }[];
  candidate_spec: Record<string, unknown>;
  lifecycle: string;
  verification: null | {
    verification_id: string; status: string; failed_rules: string[]; rules: Record<string, Rule>;
    families: Record<string, { workloads: number; parent_reversals: number; candidate_reversals: number; parent_mean_regret: number; candidate_mean_regret: number; parent_wrong_choices: number; candidate_wrong_choices: number; config_B: string }>;
    retained_model: string; runtime: { parent_seconds?: number; candidate_seconds?: number }; contract_id: string; basket_id: string; scope: string;
    development_replay: { workload_digest: string; verdict_with_candidate: string; rtl_costs: Costs; candidate_costs: Costs }[];
    heldout_rows: HeldoutRow[];
  };
  integrity_errors?: string[];
  verification_v2?: PatchReview["verification"];
}

export interface Reduction {
  reduction_id: string; status: string; reduction_ratio_operations: string; edit_set: string[]; attempts: number; surrogate_rejected: number;
  rtl_rejected: number; rtl_executions_used: number; rtl_budget: number; minimality: string; history: string;
  surrogate_models: Record<string, string>; orientation: { model_choice: Design; rtl_best: Design };
  original: { workload_digest: string; operations: number; verdict: { verdict: string; model_costs: Costs; rtl_costs: Costs } };
  reduced: { workload_digest: string; operations: number; verdict: { verdict: string; model_costs: Costs; rtl_costs: Costs; selection?: { regret: Fraction; extra_cycles: number } };
    final_rtl_run_ids: Record<string, string>; final_model_run_ids: Record<string, string>; reference_epoch: string };
  reduced_workload: WorkloadView; accepted_edits: string[];
  minimality_established?: boolean; neighbours?: { total: number; rtl_rechecked: number; rtl_rechecked_rejected: number };
}

export interface CaseView {
  schema_version: 1; case_id: string; title: string; question: string; summary: string | null; group: string | null;
  evidence_basis: string; presentation_mode: string; case_provenance: string; evaluation_scope: string; discovery_credit: number;
  diagnostic_available?: boolean;
  reference_epoch: string; current_reference_epoch: string; reference_validity: string;
  metric: { id: string; label: string; unit: string; direction: string; definition: string };
  designs: { design: Design; config: string }[];
  comparison: ComparisonView; claims: ClaimView[]; workload: WorkloadView | null; mechanism: Mechanism | null;
  reduction: Reduction | null; repair: PatchReview | null; limitations: string[]; evidence: ArtifactLink[]; view_digest: string;
  repair_controls?: { label: string; status: string; failed: string[]; verification_id: string }[];
}

export interface CaseSummary { case_id: string; title: string; short: string; verdict: string; provenance: string; scope: string; evidence_basis: string; group: string }

export interface TraceEvent { cycle: number; event_kind: string; master: number | null; operation_index: number | null; byte_address: number | null; bank?: number; row?: number; read_data?: number; monitor_id?: string; detail?: string }
export interface TraceSelection {
  schema_version: 1; run_id: string; runner: string; observation_role: string; config_id: string; model_id?: string; reference_epoch?: string;
  full_run_extent: { first_cycle: number | null; last_cycle: number | null; events: number };
  returned: number; truncated: boolean; events: TraceEvent[]; check: { status: string; makespan: number | null; violation_counts: Record<string, number>; violations: { code: string; detail: string }[] };
}

export interface ProjectRecord {
  question: string;
  status: { implemented: string[]; not_done: string[] };
  global_limitations: string[];
  gate0a?: { study_id: string; passed: boolean; checks: { check: string; passed: boolean; expectation: string; observed: unknown }[] };
  formal?: { study_id: string; properties: { id: string; statement: string }[]; covers: { id: string; statement: string }[]; assumptions: string[];
    inventory: Record<string, number | boolean>; claims: Record<string, string | number>; harness_valid: boolean; harness_problems: string[];
    tasks: Record<string, { outcome: string; depth: number; elapsed_seconds: number }>; configuration: string; frontend: string; scope_note: string };
  benchmark?: { study_id: string; target_speedup: number; useful_loop_target_met: boolean; basket: { size: number; composition: string }; host: Record<string, string>;
    repetitions: number; results: { config_id: string; model_id: string; median_seconds: Record<string, number>; speedup_per_invocation: number; speedup_batched: number;
      speedup_batched_vs_model_in_memory: number; speedup_summary_only_vs_cost_only: number; target_met: boolean; primary_comparison: string;
      kernel_speedup?: number | null; compiled_speedup_summary_only?: number | null }[] };
  screen?: StudySummary;
  locks: Record<string, Record<string, unknown>>;
  reproduce: string[];
}

export interface ArmSummary { status: string; reason?: string; accepted_proposals?: number; rejected_proposals?: number; rtl_executions_charged?: number; rtl_cache_hits?: number;
  credited_counterexamples?: number; first_credited_discovery_at_rtl_execution?: number | null; verdict_counts?: Record<string, number>;
  max_regret?: number | null; mean_regret_over_valid?: number | null; wall_seconds?: number; solver_calls?: number; stop_reason?: string }

export interface StudySummary {
  screen_run_id: string; study_id: string; study_digest: string; budget: Record<string, number | string>;
  cases: Record<string, { provenance: string; models: Record<string, { model_id: string }>; expectation: string; arms: Record<string, ArmSummary> }>;
  not_run_arms: Record<string, string>; executor: { distinct_rtl_executions: number; rtl_cache_hits: number };
  case_definitions: { case_id: string; models: Record<string, string>; provenance: string; expectation: string; mechanism_family: string }[];
  arms: string[]; description: string; public_patterns_zero_credit: string[];
  curves: Record<string, Record<string, [number, number][]>>;
}

export interface Specimen {
  id: string; label: string; kind: string; model: Costs | null; reference: Costs | null; reference_valid: boolean;
  predicted_active_acceptance_cycles?: Record<string, number>; failure?: string; evidence_status: string;
  repair: null | { A: number; B: number; status: string; withheld_evaluation: string; accepted: boolean; parent_retained?: boolean;
    withheld_example?: { parent_model: Costs; candidate_model: Costs; reference: Costs; scope: string } };
}
export interface Specimens { provenance: string; fixtures: Specimen[]; tie_break: string; namespace: string }

export interface DiagCycle { c: number; requesters: number[]; forwarded: boolean; granted: boolean; winner: number | null }
export interface DiagOutput { level: number; router: number; output: number; label: string; banks: number[]; inputs: number[]; cycles: DiagCycle[];
  requests_passed: number; conflict_cycles: number; max_requesters: number }
export interface MapVerdict {
  verdict: string; dM: number | null; dR: number | null; choice: string | null; best: string | null;
  model_margin_met: boolean | null; rtl_margin_met: boolean | null; extra?: number; regret?: [number, number];
}
export type MapModel = "parent" | "repaired";
export interface MapCell {
  i: number; j: number; x: [number, number]; y: [number, number];
  rtl: Record<string, number | null>; model: { A: number | null; parent: number | null; repaired: number | null };
  runs: Record<string, string>; verdict: Record<MapModel, MapVerdict>;
}
export interface MapLandmark {
  name: string; case_id: string; x: [number, number]; y: [number, number]; in_family: boolean | null; outside_family_because: string[];
  verdict: string; rtl_costs: Record<string, number> | null; model_costs: Record<string, number> | null; comparison_run_id: string;
}
export interface MapModelSummary {
  verdicts: Record<string, number>; strict_reversals: number; model_undecided_hardware_decisive: number; extra_cycles_strict: number;
  max_extra_cycles_strict: number; max_regret_strict: number; max_abs_error_B: number | null;
}
export interface MapAxis { id: string; label: string; definition: string; unit: string; denominator: number; levels: number[] }
export interface DecisionMapView {
  schema_version: 1; map_id: string; map_study_id: string; evidence_basis: string; reference_epoch: string; order: string[];
  configs: Record<string, string>; models: Record<"A" | MapModel, { model_id: string; model_digest: string }>;
  question: string; axes: { x: MapAxis; y: MapAxis }; features_note: string; scope: Record<string, string | number>; evaluation: string;
  prediction_before_execution: Record<string, string>;
  grid: { x: number[]; y: number[]; x_denominator: number; y_denominator: number };
  cells: MapCell[];
  summary: { cells: number; hardware: { A_faster: number; B_faster: number; within_margin: number }; parent: MapModelSummary; repaired: MapModelSummary;
    prediction_checks: { parent_B_costs: number[]; parent_reversals_where_sharing_exceeds_collisions: [number, number] } };
  executor: { distinct_rtl_executions: number; rtl_cache_hits: number };
  landmarks: MapLandmark[]; integrity_errors: string[]; integrity_error_count: number;
}

export interface DiagnosticView {
  schema_version: 1; case_id: string; diagnostic_run_id: string; reference_run_id: string; config_id: string; topology: string;
  boundary_events_identical_to_reference: boolean; mapping_check: { signal: string; mismatches: number; cycles_checked: number };
  signals: Record<string, string>; bit_layout: string; window: [number, number]; initiators: { master: number; router: number; port: number }[];
  first_stage_outputs: DiagOutput[]; priority: { c: number; prio: number }[]; valid: boolean;
}
export interface HeldoutRow { family_id: string; seed: number; config_B: string; rtl_costs: Costs | null;
  parent: { verdict: string; costs: Costs | null; regret: Fraction | null }; candidate: { verdict: string; costs: Costs | null; regret: Fraction | null } }
