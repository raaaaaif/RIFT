"""Phase 0 blinded-screen controller.

For every (case, arm) pair the controller asks the arm for proposals, validates
them, records the audited model's prediction *before* reference execution,
executes the RTL pair, and has the independent evaluator classify the result.
Budgets are counted in accepted proposals (2 RTL executions each). Cache hits
are disclosed and still charged. Rejected proposals are recorded. Public
calibration programs earn zero discovery credit.
"""

from __future__ import annotations

import json
import os
import random
import resource
import time
from pathlib import Path

from rift.contracts.canonical import digest, read_json
from rift.contracts.config import load_config
from rift.contracts.workload import WorkloadError, validate_and_compile
from rift.evaluate.compare import classify
from rift.model.registry import get_spec, model_digest
from rift.modelrun import run_model_artifact
from rift.paths import ROOT, STUDIES, rel
from rift.rtl import run_rtl
from rift.search.acquisition import score_candidate, signature, variant_specs
from rift.store import RunDir
from rift.workloads.generators import mutate, crossover, random_legal, sweep_family

PUBLIC_PATTERNS = {n: read_json(ROOT / f"experiments/workloads/{n}.json") for n in "LBM"}


class Executor:
    """Executes and caches reference and audited-model runs under complete identities."""

    def __init__(self, cfgs: dict, tags: tuple = ("screen",)):
        self.cfgs = cfgs
        self.tags = tags
        self.rtl_cache: dict = {}
        self.model_cache: dict = {}
        self.rtl_executed = 0
        self.rtl_cache_hits = 0

    def rtl(self, d: str, compiled):
        key = (self.cfgs[d].digest, compiled.digest)
        if key in self.rtl_cache:
            self.rtl_cache_hits += 1
            return self.rtl_cache[key], True
        r = run_rtl(self.cfgs[d], compiled, compress=True, tags=self.tags)
        rec = {"run_id": r["run_id"], "status": r["check"]["status"], "makespan": r["check"].get("makespan"),
               "wall_seconds": r["manifest"]["wall_seconds"], "reference_epoch": r["manifest"]["reference_epoch"]}
        self.rtl_cache[key] = rec
        self.rtl_executed += 1
        return rec, False

    def model(self, spec: dict, d: str, compiled):
        md = model_digest(spec)
        key = (md, self.cfgs[d].digest, compiled.digest)
        if key in self.model_cache:
            return self.model_cache[key], True
        r = run_model_artifact(spec, self.cfgs[d], compiled, compress=True, tags=self.tags)
        rec = {"run_id": r["run_id"], "status": r["check"]["status"], "makespan": r["check"].get("makespan"), "model_digest": md}
        self.model_cache[key] = rec
        return rec, False


# ---------------------------------------------------------------------------
# Arms
# ---------------------------------------------------------------------------
class Arm:
    arm_id = "abstract"
    adaptive = False

    def __init__(self, case: dict, ctx: dict):
        self.case, self.ctx = case, ctx
        self.history: list[dict] = []

    def propose(self, step: int) -> tuple[dict, dict]:
        raise NotImplementedError

    def observe(self, entry: dict) -> None:
        self.history.append(entry)


class SweepArm(Arm):
    arm_id = "B1_public_sweeps"

    def propose(self, step):
        if step < 3:
            n = "LBM"[step]
            return PUBLIC_PATTERNS[n], {"operator": f"public_pattern_{n}", "public_pattern": n}
        return sweep_family(step - 3), {"operator": "sweep_family", "index": step - 3}


class RandomArm(Arm):
    arm_id = "B2_legal_random"

    def propose(self, step):
        seed = 20000 + step
        return random_legal(seed, hot_words=(8 if step % 2 else None)), {"operator": "random_legal", "seed": seed}


def observed_decision_fitness(entry: dict) -> float:
    v = entry.get("verdict") or {}
    if not v.get("rtl_costs") or not v.get("model_costs") or v.get("dM") is None:
        return -1.0
    R, M = v["rtl_costs"], v["model_costs"]
    f = 0.1 * abs(v["dM"] - v["dR"]) / max(1, min(R.values()))
    if v["verdict"] == "VALID_COUNTEREXAMPLE":
        f += 1.0 + v["selection"]["regret"]["decimal"]
    elif v["sign_product"] < 0:
        f += 0.5
    return f


def observed_error_fitness(entry: dict) -> float:
    v = entry.get("verdict") or {}
    if not v.get("rtl_costs") or not v.get("model_costs"):
        return -1.0
    R, M = v["rtl_costs"], v["model_costs"]
    return sum(abs(M[d] - R[d]) / max(1, R[d]) for d in R)


class EvolutionaryArm(Arm):
    arm_id = "B2_evolutionary"
    adaptive = True

    def __init__(self, case, ctx):
        super().__init__(case, ctx)
        self.rng = random.Random(31000)

    def propose(self, step):
        if step < 8:
            seed = 30000 + step
            return random_legal(seed, hot_words=(8 if step % 2 else None)), {"operator": "seed_population", "seed": seed}
        ranked = sorted((e for e in self.history if "verdict" in e), key=observed_decision_fitness, reverse=True)
        elite = [e["workload"] for e in ranked[:4]] or [random_legal(30000)]
        if self.rng.random() < 0.3 and len(elite) > 1:
            a, b = self.rng.sample(elite, 2)
            return crossover(a, b, self.rng), {"operator": "crossover"}
        return mutate(self.rng.choice(elite), self.rng), {"operator": "mutate_elite"}


class AcquisitionArm(Arm):
    """Shared machinery for decision-directed and error-directed acquisition."""

    adaptive = True
    score_key = "decision_score"
    fitness = staticmethod(observed_decision_fitness)
    pool_size = 24
    explore_every = 5

    def __init__(self, case, ctx):
        super().__init__(case, ctx)
        self.rng = random.Random(41000 if self.score_key == "decision_score" else 51000)
        self.variants = variant_specs(case["models"], ctx.get("fitted_model"))
        self.seen_sigs: dict = {}
        self.cost_history: list[float] = []
        self.unselected = 0

    def _pool(self, step):
        pool = []
        ranked = sorted((e for e in self.history if "verdict" in e), key=self.fitness, reverse=True)
        elite = [e["workload"] for e in ranked[:4]]
        for _ in range(self.pool_size):
            r = self.rng.random()
            if elite and r < 0.55:
                pool.append((mutate(self.rng.choice(elite), self.rng), "mutate_elite"))
            elif r < 0.8:
                pool.append((random_legal(self.rng.randrange(10 ** 9), hot_words=self.rng.choice([None, 4, 8, 16])), "random_candidate"))
            else:
                pool.append((sweep_family(self.rng.randrange(64)), "sweep_candidate"))
        return pool

    def propose(self, step):
        pool = self._pool(step)
        cfg_a, cfg_b = self.ctx["cfgs"]["A"], self.ctx["cfgs"]["B"]
        scored = []
        for w, op in pool:
            try:
                ca, cb = validate_and_compile(w, cfg_a), validate_and_compile(w, cfg_b)
            except WorkloadError:
                continue
            s = score_candidate(self.variants, cfg_a, cfg_b, ca, cb, self.seen_sigs, self.cost_history)
            scored.append((s[self.score_key] if s["valid"] else -1, w, op, s, ca))
        self.unselected += max(0, len(scored) - 1)
        explore = (step % self.explore_every) == self.explore_every - 1
        if explore:
            pick = scored[self.rng.randrange(len(scored))]
        else:
            pick = max(scored, key=lambda x: x[0])
        sc, w, op, s, ca = pick
        sig = signature(ca, cfg_b)
        self.seen_sigs[sig] = self.seen_sigs.get(sig, 0) + 1
        meta = {"operator": op, "exploration_pick": explore, "acquisition": {k: s.get(k) for k in (
            "model_choice", "disagreement", "decision_loss_proxy", "information", "novelty", "signature",
            "estimated_cost_seconds", "decision_score", "error_score", "variant_predictions")}, "pool_size": len(scored)}
        return w, meta

    def observe(self, entry):
        super().observe(entry)
        if entry.get("rtl_wall"):
            self.cost_history.append(entry["rtl_wall"])


class DecisionDirectedArm(AcquisitionArm):
    arm_id = "RIFT_decision_directed"
    score_key = "decision_score"
    fitness = staticmethod(observed_decision_fitness)


class ErrorDirectedArm(AcquisitionArm):
    arm_id = "B5_error_directed"
    score_key = "error_score"
    fitness = staticmethod(observed_error_fitness)


class SmtArm(Arm):
    """B3: bounded SMT cover search on the BFLY RTL for acceptance shortfalls a bank-only model misses."""

    arm_id = "B3_bounded_smt"
    applicable_models = {"bank_only_v1"}

    def __init__(self, case, ctx):
        super().__init__(case, ctx)
        self.excluded: list[list[int]] = []
        self.solver_calls = []
        self.workdir = ctx["workdir"] / f"b3_{case['case_id']}"

    def propose(self, step):
        from rift.formal import b3_search_next
        from rift.workloads.generators import fixed_word_streams
        r = b3_search_next(self.excluded, self.workdir)
        self.solver_calls.append({"outcome": r["outcome"], "seconds": r["elapsed_seconds"], "vector": r["vector"]})
        if not r["vector"]:
            raise StopIteration(f"solver returned {r['outcome']}")
        self.excluded.append(r["vector"])
        return fixed_word_streams(r["vector"], 32, label=f"B3 smt vector {r['vector']}"), {
            "operator": "smt_cover_acceptance_shortfall", "vector": r["vector"], "solver_seconds": r["elapsed_seconds"], "depth": r["depth"]}


ARMS = {a.arm_id: a for a in (SweepArm, RandomArm, EvolutionaryArm, SmtArm, ErrorDirectedArm, DecisionDirectedArm)}


# ---------------------------------------------------------------------------
# Study controller
# ---------------------------------------------------------------------------
def _child_cpu() -> float:
    ru = resource.getrusage(resource.RUSAGE_CHILDREN)
    return ru.ru_utime + ru.ru_stime


def run_screen(study_path: Path, arms: list[str] | None = None, cases: list[str] | None = None) -> dict:
    study = read_json(study_path)
    designs = study["admitted_designs"]
    order = [d["design"] for d in designs]
    cfgs = {d["design"]: load_config(d["config"]) for d in designs}
    budget = study["budget"]["accepted_proposals_per_case_per_arm"]
    max_props = study["budget"]["max_total_proposals_per_case_per_arm"]
    wall_cap = study["budget"]["wall_seconds_per_case_per_arm"]
    public_digests = {digest(w): n for n, w in PUBLIC_PATTERNS.items()}
    ex = Executor(cfgs)
    sd = RunDir("screen", root=STUDIES)
    sd.write_json("study.json", study)
    summary = {"schema_version": 1, "study_id": study["study_id"], "study_digest": digest(study), "screen_run_id": sd.run_id,
               "budget": study["budget"], "cases": {}}
    arm_ids = arms or study["arms"]
    for case in study["cases"]:
        if cases and case["case_id"] not in cases:
            continue
        ctx = {"cfgs": cfgs, "fitted_model": study.get("fitted_model"), "workdir": sd.path / "work"}
        specs = {d: get_spec(case["models"][d]) for d in order}
        case_sum = {"provenance": case["provenance"], "models": {d: {"model_id": specs[d]["model_id"], "model_digest": model_digest(specs[d])} for d in order},
                    "expectation": case.get("expectation"), "arms": {}}
        for arm_id in arm_ids:
            arm_cls = ARMS[arm_id]
            if getattr(arm_cls, "applicable_models", None) and case["models"]["B"] not in arm_cls.applicable_models:
                case_sum["arms"][arm_id] = {"status": "NOT_APPLICABLE",
                                            "reason": "a formal encoding exists only for the bank-only model's acceptance predicate"}
                continue
            arm = arm_cls(case, ctx)
            ledger_name = f"ledger__{case['case_id']}__{arm_id}.jsonl"
            ledger = open(sd.file(ledger_name), "x")
            t0, cpu0, ccpu0 = time.time(), time.process_time(), _child_cpu()
            accepted = rejected = step = 0
            credited, first_credit_rtl, verdicts, regrets, cached = 0, None, {}, [], 0
            rtl_execs = 0
            stop_reason = "budget"
            while accepted < budget and accepted + rejected < max_props and time.time() - t0 < wall_cap:
                try:
                    w, meta = arm.propose(step)
                except StopIteration as e:
                    stop_reason = f"arm exhausted: {e}"
                    break
                step += 1
                entry = {"step": step, "case_id": case["case_id"], "arm_id": arm_id, "meta": meta}
                try:
                    comp = {d: validate_and_compile(w, cfgs[d]) for d in order}
                except WorkloadError as e:
                    rejected += 1
                    entry.update(status="REJECTED_PROPOSAL", reason=str(e))
                    ledger.write(json.dumps(entry) + "\n")
                    arm.observe(entry)
                    continue
                accepted += 1
                wd = comp[order[0]].digest
                # prediction recorded before reference execution
                mod = {d: ex.model(specs[d], d, comp[d])[0] for d in order}
                entry["prediction"] = {"recorded_at": time.time(), "model_costs": {d: mod[d]["makespan"] for d in order},
                                       "model_status": {d: mod[d]["status"] for d in order}, "model_run_ids": {d: mod[d]["run_id"] for d in order}}
                rtl, hits = {}, {}
                for d in order:
                    rec, hit = ex.rtl(d, comp[d])
                    rtl[d], hits[d] = rec, hit
                    cached += int(hit)
                    rtl_execs += 1
                verdict = classify(order, {d: {"status": mod[d]["status"], "makespan": mod[d]["makespan"]} for d in order},
                                   {d: {"status": rtl[d]["status"], "makespan": rtl[d]["makespan"]} for d in order})
                public = public_digests.get(wd)
                credit = int(verdict["verdict"] == "VALID_COUNTEREXAMPLE" and public is None)
                if credit:
                    credited += 1
                    if first_credit_rtl is None:
                        first_credit_rtl = rtl_execs
                verdicts[verdict["verdict"]] = verdicts.get(verdict["verdict"], 0) + 1
                if "selection" in verdict:
                    regrets.append(verdict["selection"]["regret"]["decimal"])
                entry.update(status="EVALUATED", workload_digest=wd, workload=w, public_pattern=public,
                             rtl={d: {"run_id": rtl[d]["run_id"], "status": rtl[d]["status"], "makespan": rtl[d]["makespan"]} for d in order},
                             rtl_cached=hits,
                             verdict={k: verdict.get(k) for k in ("verdict", "model_costs", "rtl_costs", "dM", "dR", "sign_product", "model_choice", "rtl_best", "selection", "model_margin", "rtl_margin")},
                             discovery_credit=credit, reference_epoch=rtl[order[0]].get("reference_epoch"),
                             rtl_wall=sum(rtl[d]["wall_seconds"] for d in order))
                ledger.write(json.dumps(entry) + "\n")
                arm.observe(entry)
            ledger.close()
            if stop_reason == "budget" and accepted < budget:
                stop_reason = "proposal or wall-time cap"
            arm_sum = {
                "status": "COMPLETED",
                "stop_reason": stop_reason,
                "solver_calls": len(getattr(arm, "solver_calls", [])),
                "solver_seconds": round(sum(c["seconds"] for c in getattr(arm, "solver_calls", [])), 2),
                "accepted_proposals": accepted,
                "rejected_proposals": rejected,
                "rtl_executions_charged": rtl_execs,
                "rtl_cache_hits": cached,
                "credited_counterexamples": credited,
                "first_credited_discovery_at_rtl_execution": first_credit_rtl,
                "verdict_counts": verdicts,
                "max_regret": max(regrets) if regrets else None,
                "mean_regret_over_valid": (sum(regrets) / len(regrets)) if regrets else None,
                "wall_seconds": round(time.time() - t0, 3),
                "controller_cpu_seconds": round(time.process_time() - cpu0, 3),
                "child_cpu_seconds": round(_child_cpu() - ccpu0, 3),
                "model_tokens": 0,
                "monetary_charges": 0,
                "unselected_candidates": getattr(arm, "unselected", 0),
                "ledger": ledger_name,
            }
            case_sum["arms"][arm_id] = arm_sum
        summary["cases"][case["case_id"]] = case_sum
    summary["executor"] = {"distinct_rtl_executions": ex.rtl_executed, "rtl_cache_hits": ex.rtl_cache_hits}
    sd.write_json("summary.json", summary)
    m = sd.finalize({"schema_version": 1, "kind": "phase0_screen", "status": "COMPLETED", "study_id": study["study_id"], "tags": ["screen"]})
    return {"screen_run_id": sd.run_id, "path": rel(sd.path), "summary": summary}
