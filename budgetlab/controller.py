"""Deterministic research controller.

Flow of one run (``run_research``):

1. load development data only, apply the scenario card, freeze the protocol;
2. run the baseline, calibrate ``min_effect`` on calibration split seeds, freeze the contract;
3. explore with one of the systems below - every experiment is a real subprocess fit and every
   verdict is computed here, never by a model;
4. confirm the best passing candidate on unseen split seeds, refit on all development data
   and freeze the delivery. The sealed holdout is scored later by ``budgetlab.evaluation``.

Systems:
* ``random_search``          zero-token sampler over the same legal space;
* ``budgetlab_no_schedule``  proposer loop with dedup, budget and stop rules only;
* ``budgetlab``              adds the scheduled zero-token tool search and on-demand critic.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib

from .budget import Budget
from .contracts import (
    freeze_contract,
    spec_hash,
    stable_hash,
    validate_experiment_spec,
)
from .data import (
    DatasetBundle,
    load_development,
    numeric_minima,
    prepare_task,
    split_manifest,
)
from .evaluator import calibrate, evaluate_candidate, evaluate_confirmation
from .ledger import EventLedger, atomic_write_json, utc_now
from .pipeline import build_pipeline
from .profile import profile_development
from .proposers import (
    CallOutcome,
    Critic,
    LLMSettings,
    Proposer,
    PydanticAICritic,
    PydanticAIProposer,
    ScriptedProposer,
    build_context,
    load_dotenv,
)
from .provenance import code_version_label, environment_info, git_info
from .reporting import write_report
from .runner import PROJECT_ROOT, Runner
from .schemas import (
    BudgetLimits,
    Candidate,
    ExecutionResult,
    ExperimentSpec,
    LoopPolicy,
    ProposalBatch,
    ProtocolSpec,
    ResourceVector,
    TaskContract,
)
from .search import SpecSampler, baseline_spec
from .state import ExperimentRecord, ResearchState, RoundRecord
from .tasks import approved_features, get_task

SYSTEMS = ("random_search", "budgetlab_no_schedule", "budgetlab")
EVIDENCE_EXTRAS = ("eda", "calibration", "scenario_card")


def make_run_id(system: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{system}-{uuid.uuid4().hex[:6]}"


@dataclass
class RunContext:
    run_id: str
    run_dir: Path
    system: str
    config: dict[str, Any]
    ledger: EventLedger
    budget: Budget
    runner: Runner
    card: dict[str, Any]
    profile: dict[str, Any]
    contract: TaskContract
    bundle: DatasetBundle
    minima: dict[str, float]
    started: float

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def experiment_cost(self) -> ResourceVector:
        return ResourceVector(
            experiments=1,
            fits=self.contract.cv_folds,
            seconds=self.contract.budgets.experiment_timeout_seconds,
        )


# ---------------------------------------------------------------------------- protocol


def build_protocol(
    config: dict[str, Any],
    bundle: DatasetBundle,
    card: dict[str, Any],
    approved: tuple[str, ...],
    holdout_sha256: str,
) -> ProtocolSpec:
    task = get_task(config["task_id"])
    limits = dict(config["budget"])
    return ProtocolSpec(
        task_id=task.task_id,
        dataset_ref=task.task_id,
        dataset_hash=bundle.dataset_hash,
        scenario_card_hash=stable_hash(card),
        target_column=task.target_column,
        primary_metric=config.get("primary_metric", task.primary_metric),
        prediction_time=str(card["prediction_time"]),
        approved_feature_columns=approved,
        text_columns=tuple(config.get("text_columns", ())),
        split_seed=config["split_seed"],
        calibration_split_seeds=tuple(config["calibration_split_seeds"]),
        confirmation_split_seeds=tuple(config["confirmation_split_seeds"]),
        cv_folds=config["cv_folds"],
        search_training_seed=config["training_seed"],
        allowed_model_families=tuple(
            config.get(
                "allowed_model_families",
                ("logistic_regression", "random_forest", "hist_gradient_boosting"),
            )
        ),
        min_effect_floor=config["min_effect_floor"],
        budgets=BudgetLimits(**limits),
        loop_policy=LoopPolicy(**config.get("loop", {})),
        sealed_holdout_sha256=holdout_sha256,
    )


def provisional_contract(protocol: ProtocolSpec, manifest_hash: str) -> TaskContract:
    return TaskContract(
        parent_protocol_hash=stable_hash(protocol),
        task_id=protocol.task_id,
        dataset_ref=protocol.dataset_ref,
        dataset_hash=protocol.dataset_hash,
        scenario_card_hash=protocol.scenario_card_hash,
        target_column=protocol.target_column,
        primary_metric=protocol.primary_metric,
        prediction_time=protocol.prediction_time,
        approved_feature_columns=protocol.approved_feature_columns,
        text_columns=protocol.text_columns,
        split_seed=protocol.split_seed,
        split_manifest_hash=manifest_hash,
        cv_folds=protocol.cv_folds,
        search_training_seed=protocol.search_training_seed,
        allowed_model_families=protocol.allowed_model_families,
        decision_policy={
            "metric": protocol.primary_metric,
            "min_effect_floor": protocol.min_effect_floor,
            "noise_floor": 0.0,
            "min_effect": protocol.min_effect_floor,
            "calibration_split_seeds": protocol.calibration_split_seeds,
            "confirmation_split_seeds": protocol.confirmation_split_seeds,
        },
        budgets=protocol.budgets,
        loop_policy=protocol.loop_policy,
        sealed_holdout_sha256=protocol.sealed_holdout_sha256,
        memory_snapshot_hash=stable_hash([]),
    )


def setup_run(
    config: dict[str, Any],
    system: str,
    runs_root: Path,
    data_root: Path,
    proposal_source: str,
) -> tuple[RunContext, ResearchState]:
    if system not in SYSTEMS:
        raise ValueError(f"unsupported research system: {system}; choose from {SYSTEMS}")
    started = time.monotonic()
    run_id = make_run_id(system)
    run_dir = runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    ledger = EventLedger(run_id, run_dir)
    ledger.append("run_created", details={"system": system, "proposal_source": proposal_source})
    task = get_task(config["task_id"])
    manifest = prepare_task(task.task_id, data_root)
    bundle = load_development(task.task_id, data_root)
    card = task.card
    approved = approved_features(card, list(bundle.features.columns))
    protocol = build_protocol(config, bundle, card, approved, manifest["holdout_sha256"])
    atomic_write_json(run_dir / "protocol.json", protocol.model_dump(mode="json"))
    atomic_write_json(run_dir / "scenario_card.json", card)
    atomic_write_json(
        run_dir / "run_config.json",
        {
            "config": config,
            "system": system,
            "proposal_source": proposal_source,
            "data_root": str(data_root.resolve()),
            "git": git_info(PROJECT_ROOT),
            "environment": environment_info(),
        },
    )
    ledger.append(
        "protocol_accepted",
        artifact_ref="protocol.json",
        details={
            "approved_features": len(approved),
            "excluded_features": sorted(set(bundle.features.columns) - set(approved)),
        },
    )
    features = bundle.features[list(approved)]
    profile = profile_development(bundle.features, bundle.target, card, protocol.text_columns)
    atomic_write_json(run_dir / "eda.json", profile)
    ledger.append("profile_written", artifact_ref="eda.json")
    seeds = (
        protocol.split_seed,
        *protocol.calibration_split_seeds,
        *protocol.confirmation_split_seeds,
    )
    split_value, manifest_hash = split_manifest(bundle, seeds, protocol.cv_folds)
    atomic_write_json(run_dir / "split_manifest.json", split_value)
    tail = ResourceVector(
        experiments=7,
        fits=6 * protocol.cv_folds + 1,
        seconds=7 * min(protocol.budgets.experiment_timeout_seconds, 60),
    )
    budget = Budget(protocol.budgets, run_dir / "budget.json", ledger, tail_reserve=tail)
    provisional = provisional_contract(protocol, manifest_hash)
    runner = Runner(run_dir, ledger, budget, data_root)
    minima = numeric_minima(features)
    base_spec = baseline_spec()
    validate_experiment_spec(base_spec, provisional, numeric_minima=minima)
    baseline_result = runner.execute(
        base_spec,
        provisional,
        purpose="initial_baseline",
        split_seed=protocol.split_seed,
        experiment_id="baseline",
    )
    if baseline_result.status != "ok":
        raise RuntimeError(f"baseline failed: {baseline_result.error}")
    ledger.append("baseline_completed", artifact_ref=baseline_result.artifact_ref)
    calibration_results = [
        runner.execute(
            base_spec,
            provisional,
            purpose="calibration",
            split_seed=seed,
            experiment_id=f"calibration-{seed}",
        )
        for seed in protocol.calibration_split_seeds
    ]
    calibration = calibrate(stable_hash(protocol), calibration_results, protocol.min_effect_floor)
    atomic_write_json(run_dir / "calibration.json", calibration.model_dump(mode="json"))
    ledger.append("calibration_completed", artifact_ref="calibration.json")
    contract = freeze_contract(
        protocol,
        calibration,
        split_manifest_hash=manifest_hash,
        memory_snapshot_hash=stable_hash([]),
    )
    atomic_write_json(run_dir / "contract.json", contract.model_dump(mode="json"))
    ledger.append("contract_frozen", artifact_ref="contract.json")
    ctx = RunContext(
        run_id=run_id,
        run_dir=run_dir,
        system=system,
        config=config,
        ledger=ledger,
        budget=budget,
        runner=runner,
        card=card,
        profile=profile,
        contract=contract,
        bundle=bundle,
        minima=minima,
        started=started,
    )
    baseline_record = ExperimentRecord(
        experiment_id="baseline",
        origin="baseline",
        round_index=0,
        spec=base_spec,
        spec_hash=spec_hash(base_spec),
        result=baseline_result,
        vs_baseline=None,
        vs_previous_best=None,
        previous_best_id=None,
        elapsed_seconds=ctx.elapsed(),
    )
    state = ResearchState(baseline=baseline_record, min_effect=contract.decision_policy.min_effect)
    _write_experiment(ctx, baseline_record)
    return ctx, state


# ---------------------------------------------------------------------------- experiments


def _write_experiment(ctx: RunContext, record: ExperimentRecord) -> None:
    payload = {
        "experiment_id": record.experiment_id,
        "origin": record.origin,
        "round": record.round_index,
        "candidate_id": record.candidate_id,
        "hypothesis": record.hypothesis,
        "spec": record.spec.model_dump(mode="json"),
        "spec_hash": record.spec_hash,
        "result": record.result.model_dump(mode="json"),
        "vs_baseline": record.vs_baseline.model_dump(mode="json") if record.vs_baseline else None,
        "hypothesis_check": record.hypothesis_check.model_dump(mode="json")
        if record.hypothesis_check
        else None,
        "previous_best_id": record.previous_best_id,
        "delta_vs_previous_best": record.vs_previous_best,
        "best_score_after": record.best_score_after,
        "elapsed_seconds": record.elapsed_seconds,
        "llm_tokens_so_far": record.llm_tokens_so_far,
        "logs": [
            f"logs/{record.experiment_id}.stdout.log",
            f"logs/{record.experiment_id}.stderr.log",
        ],
    }
    atomic_write_json(ctx.run_dir / record.result.artifact_ref, payload)


def run_experiment(
    ctx: RunContext,
    state: ResearchState,
    spec: ExperimentSpec,
    *,
    experiment_id: str,
    origin: str,
    round_index: int,
    candidate: Candidate | None = None,
) -> tuple[ExperimentRecord, bool]:
    """Execute one exploration experiment and judge it with program rules only."""
    min_effect = ctx.contract.decision_policy.min_effect
    result = ctx.runner.execute(
        spec,
        ctx.contract,
        purpose="exploration",
        split_seed=ctx.contract.split_seed,
        experiment_id=experiment_id,
    )
    previous_best = state.best
    vs_baseline = evaluate_candidate(result, state.baseline.result, min_effect)
    vs_best = evaluate_candidate(result, previous_best.result, min_effect)
    hypothesis_check = None
    if candidate is not None:
        comparator = state.get(candidate.hypothesis.comparator_experiment_id)
        hypothesis_check = evaluate_candidate(result, comparator.result, min_effect)
    record = ExperimentRecord(
        experiment_id=experiment_id,
        origin=origin,  # type: ignore[arg-type]
        round_index=round_index,
        spec=spec,
        spec_hash=spec_hash(spec),
        result=result,
        vs_baseline=vs_baseline,
        vs_previous_best=vs_best.mean_paired_delta,
        previous_best_id=previous_best.experiment_id,
        hypothesis_check=hypothesis_check,
        candidate_id=candidate.candidate_id if candidate else None,
        hypothesis=candidate.hypothesis.statement if candidate else None,
    )
    improved = state.add(record)
    record.elapsed_seconds = ctx.elapsed()
    record.llm_tokens_so_far = ctx.budget.used.llm_tokens
    _write_experiment(ctx, record)
    evaluation_ref = f"evaluations/{experiment_id}.json"
    atomic_write_json(
        ctx.run_dir / evaluation_ref,
        {
            "vs_baseline": vs_baseline.model_dump(mode="json"),
            "vs_previous_best": vs_best.model_dump(mode="json"),
            "hypothesis_check": hypothesis_check.model_dump(mode="json")
            if hypothesis_check
            else None,
        },
    )
    ctx.ledger.append(
        "evaluation_recorded",
        action_id=f"train:{experiment_id}",
        artifact_ref=evaluation_ref,
        details={
            "origin": origin,
            "baseline_verdict": vs_baseline.policy_status,
            "hypothesis_verdict": hypothesis_check.policy_status if hypothesis_check else None,
            "new_best": state.best_id == experiment_id,
            "improved_by_min_effect": improved,
        },
    )
    return record, improved


def run_tool_search(
    ctx: RunContext, state: ResearchState, sampler: SpecSampler, count: int, reason: str
) -> bool:
    """Zero-token action scheduled by rules; it shares code with the random_search system."""
    limit = ctx.contract.budgets.max_tool_search_fits
    improved = False
    ran = 0
    ctx.ledger.append("tool_search_started", reason_code=reason, details={"count": count})
    for _ in range(count):
        if state.tool_search_fits + ctx.contract.cv_folds > limit:
            break
        if not ctx.budget.can_reserve(ctx.experiment_cost()):
            break
        spec = sampler.sample_new(lambda s: state.duplicate_of(s) is not None)
        if spec is None:
            break
        validate_experiment_spec(spec, ctx.contract, numeric_minima=ctx.minima)
        experiment_id = f"tool-{len(state.experiments):02d}"
        record, better = run_experiment(
            ctx,
            state,
            spec,
            experiment_id=experiment_id,
            origin="tool_search",
            round_index=len(state.rounds),
        )
        state.tool_search_fits += record.result.fit_attempts
        improved = improved or better
        ran += 1
    ctx.ledger.append(
        "tool_search_completed",
        reason_code=reason,
        details={"ran": ran, "improved": improved, "trigger_source": "rule"},
    )
    return improved


# ---------------------------------------------------------------------------- LLM metering


def metered_call(
    ctx: RunContext,
    *,
    role: str,
    round_index: int,
    source: str,
    estimate: ResourceVector,
    call: Any,
    context: dict[str, Any],
) -> CallOutcome:
    """Reserve before the call, settle with reported usage after it, log every request."""
    action_id = f"llm:{role}:r{round_index:02d}"
    metered = estimate != ResourceVector()
    if metered:
        if not ctx.budget.can_reserve(estimate):
            return CallOutcome(output=None, error="llm_budget_insufficient")
        ctx.budget.reserve(action_id, estimate)
    context_ref = f"llm/{role}-r{round_index:02d}.context.json"
    atomic_write_json(ctx.run_dir / context_ref, context)
    ctx.ledger.append("llm_call_started", action_id=action_id, artifact_ref=context_ref)
    outcome: CallOutcome = call(context)
    if metered:
        ctx.budget.settle(action_id, outcome.usage, unknown=outcome.unknown)
    output_ref = None
    if outcome.output is not None:
        output_ref = f"llm/{role}-r{round_index:02d}.output.json"
        atomic_write_json(ctx.run_dir / output_ref, outcome.output.model_dump(mode="json"))
    line = {
        "timestamp": utc_now(),
        "action_id": action_id,
        "role": role,
        "round": round_index,
        "source": source,
        "planned": estimate.model_dump(mode="json"),
        "usage": outcome.usage.model_dump(mode="json"),
        "unknown": outcome.unknown.model_dump(mode="json"),
        "details": outcome.details,
        "error": outcome.error,
        "context_ref": context_ref,
        "output_ref": output_ref,
    }
    with (ctx.run_dir / "llm_calls.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
    ctx.ledger.append(
        "llm_call_completed" if outcome.error is None else "llm_call_failed",
        action_id=action_id,
        artifact_ref=output_ref,
        reason_code=None if outcome.error is None else "call_failed",
        details={"role": role, "error": outcome.error, **outcome.details},
    )
    return outcome


# ---------------------------------------------------------------------------- research loop


def screen_candidates(
    ctx: RunContext, state: ResearchState, batch: ProposalBatch
) -> tuple[list[Candidate], list[dict[str, str]]]:
    known = set(state.known_ids())
    allowed_refs = known | set(EVIDENCE_EXTRAS)
    valid: list[Candidate] = []
    rejected: list[dict[str, str]] = []
    batch_hashes: set[str] = set()
    for candidate in batch.candidates:
        digest = spec_hash(candidate.experiment)
        reason = None
        if digest in batch_hashes:
            reason = "duplicate of the other candidate in this batch"
        elif (duplicate := state.seen.get(digest)) is not None:
            reason = f"duplicate of experiment {duplicate}; reuse its result instead"
            state.duplicates_blocked += 1
        elif candidate.hypothesis.comparator_experiment_id not in known:
            reason = f"unknown comparator {candidate.hypothesis.comparator_experiment_id}"
        elif not set(candidate.hypothesis.evidence_refs) & allowed_refs:
            reason = "no valid evidence_refs"
        else:
            try:
                validate_experiment_spec(
                    candidate.experiment, ctx.contract, numeric_minima=ctx.minima
                )
            except ValueError as exc:
                reason = f"invalid spec: {exc}"
                state.invalid_rejected += 1
        batch_hashes.add(digest)
        if reason is None:
            valid.append(candidate)
        else:
            rejected.append({"candidate_id": candidate.candidate_id, "reason": reason})
    return valid, rejected


def choose_candidates(
    ctx: RunContext, state: ResearchState, valid: list[Candidate]
) -> tuple[list[Candidate], list[dict[str, str]]]:
    """Novel factors first, proposer order second; run both when both are cheap."""
    policy = ctx.contract.loop_policy
    tried_families = {record.spec.model.family for record in state.experiments}
    tried_actions = {
        action.kind for record in state.experiments for action in record.spec.feature_actions
    }

    def novelty(candidate: Candidate) -> int:
        spec = candidate.experiment
        new_family = spec.model.family not in tried_families
        new_action = any(action.kind not in tried_actions for action in spec.feature_actions)
        return int(new_family or new_action)

    def estimate_seconds(candidate: Candidate) -> float:
        family = candidate.experiment.model.family
        return (
            state.family_seconds(family)
            or state.max_seconds()
            or float(ctx.contract.budgets.experiment_timeout_seconds)
        )

    ordered = sorted(enumerate(valid), key=lambda item: (-novelty(item[1]), item[0]))
    ranked = [candidate for _, candidate in ordered]
    two = ResourceVector(
        experiments=2,
        fits=2 * ctx.contract.cv_folds,
        seconds=2 * ctx.contract.budgets.experiment_timeout_seconds,
    )
    cheap = all(estimate_seconds(c) <= policy.cheap_experiment_seconds for c in ranked)
    if len(ranked) == 2 and cheap and ctx.budget.can_reserve(two):
        return ranked, []
    not_run = [
        {
            "candidate_id": candidate.candidate_id,
            "reason": "not cheap enough to run both" if not cheap else "budget allows one",
        }
        for candidate in ranked[1:]
    ]
    return ranked[:1], not_run


def stop_reason(
    ctx: RunContext, state: ResearchState, proposer: Proposer, probe: dict[str, Any]
) -> str | None:
    policy = ctx.contract.loop_policy
    best_score = state.best.result.mean_score or 0.0
    if policy.target_score is not None and best_score >= policy.target_score:
        return "target_reached"
    if len(state.rounds) >= policy.max_rounds:
        return "max_rounds"
    if state.stagnation >= policy.stagnation_stop:
        return "diminishing_returns"
    if state.empty_rounds >= ctx.contract.budgets.max_empty_proposal_rounds:
        return "no_valid_candidates"
    if not ctx.budget.can_reserve(ctx.experiment_cost()):
        return "budget_exhausted"
    if not ctx.budget.can_reserve(proposer.estimate(probe)):
        return "llm_budget_exhausted"
    return None


def explore_loop(
    ctx: RunContext,
    state: ResearchState,
    proposer: Proposer,
    critic: Critic | None,
    *,
    schedule: bool,
) -> None:
    policy = ctx.contract.loop_policy
    sampler = SpecSampler(ctx.config.get("search_seed", 2026), ctx.contract, ctx.profile)
    if schedule and policy.initial_tool_search > 0:
        if run_tool_search(ctx, state, sampler, policy.initial_tool_search, "initial_survey"):
            state.stagnation = 0
    previous_error = False
    while True:
        mode = "replan" if state.stagnation >= policy.stagnation_replan else "normal"
        context = build_context(
            card=ctx.card,
            profile=ctx.profile,
            contract=ctx.contract,
            state=state,
            remaining=ctx.budget.remaining(),
            mode=mode,
        )
        reason = stop_reason(ctx, state, proposer, context)
        if reason is not None:
            state.stop_reason = reason
            ctx.ledger.append("stop_decided", reason_code=reason)
            return
        round_index = len(state.rounds) + 1
        if (
            schedule
            and state.stagnation >= policy.stagnation_tool_search
            and not state.tool_search_since_improvement
        ):
            state.tool_search_since_improvement = True
            if run_tool_search(ctx, state, sampler, policy.tool_search_batch, "stagnation"):
                _reset_stagnation(state)
                continue
            context = build_context(
                card=ctx.card,
                profile=ctx.profile,
                contract=ctx.contract,
                state=state,
                remaining=ctx.budget.remaining(),
                mode=mode,
            )
        if (
            schedule
            and critic is not None
            and policy.critic_on_stagnation
            and state.stagnation >= policy.stagnation_replan
            and not state.critic_since_improvement
        ):
            state.critic_since_improvement = True
            critic_outcome = metered_call(
                ctx,
                role="critic",
                round_index=round_index,
                source=critic.source,
                estimate=critic.estimate(context),
                call=critic.review,
                context=context,
            )
            if critic_outcome.output is not None:
                state.critic_advice = critic_outcome.output.model_dump(mode="json")
                context["critic_advice"] = state.critic_advice
        record = RoundRecord(
            round_index=round_index,
            mode=mode,
            trigger_source="rule" if mode == "replan" else ("error" if previous_error else "agent"),
        )
        outcome = metered_call(
            ctx,
            role="proposer",
            round_index=round_index,
            source=proposer.source,
            estimate=proposer.estimate(context),
            call=proposer.propose,
            context=context,
        )
        state.rounds.append(record)
        batch: ProposalBatch | None = outcome.output
        if batch is None:
            record.proposal_error = outcome.error
            state.empty_rounds += 1
            state.feedback = [f"previous proposal failed: {outcome.error}"]
            previous_error = True
            _write_round(ctx, record)
            continue
        record.intent = batch.intent
        record.direction = batch.direction
        record.direction_changed = batch.intent in ("pivot", "replan")
        if record.direction_changed:
            ctx.ledger.append(
                "direction_changed",
                reason_code=record.trigger_source,
                details={"from": state.direction, "to": batch.direction, "intent": batch.intent},
            )
        state.direction = batch.direction
        valid, rejected = screen_candidates(ctx, state, batch)
        record.rejected = rejected
        for item in rejected:
            ctx.ledger.append("candidate_rejected", reason_code="screen", details=item)
        if not valid:
            state.empty_rounds += 1
            state.feedback = [f"{item['candidate_id']}: {item['reason']}" for item in rejected]
            previous_error = True
            _write_round(ctx, record)
            continue
        state.empty_rounds = 0
        selected, not_run = choose_candidates(ctx, state, valid)
        record.not_run = not_run
        improved = False
        failed = False
        for index, candidate in enumerate(selected, start=1):
            if not ctx.budget.can_reserve(ctx.experiment_cost()):
                record.not_run.append(
                    {"candidate_id": candidate.candidate_id, "reason": "budget exhausted"}
                )
                continue
            experiment_id = f"r{round_index:02d}-c{index}"
            ctx.ledger.append(
                "candidate_selected",
                details={"candidate_id": candidate.candidate_id, "experiment_id": experiment_id},
            )
            result_record, better = run_experiment(
                ctx,
                state,
                candidate.experiment,
                experiment_id=experiment_id,
                origin="proposer",
                round_index=round_index,
                candidate=candidate,
            )
            record.selected.append(experiment_id)
            improved = improved or better
            failed = failed or result_record.result.status != "ok"
        state.feedback = [f"{item['candidate_id']}: {item['reason']}" for item in rejected]
        record.improved = improved
        previous_error = failed
        if improved:
            _reset_stagnation(state)
        else:
            state.stagnation += 1
        _write_round(ctx, record, batch)


def _reset_stagnation(state: ResearchState) -> None:
    state.stagnation = 0
    state.tool_search_since_improvement = False
    state.critic_since_improvement = False
    state.critic_advice = None


def _write_round(ctx: RunContext, record: RoundRecord, batch: ProposalBatch | None = None) -> None:
    payload = {
        **record.__dict__,
        "proposal": batch.model_dump(mode="json") if batch else None,
    }
    atomic_write_json(ctx.run_dir / "rounds" / f"round-{record.round_index:02d}.json", payload)


def explore_random(ctx: RunContext, state: ResearchState) -> None:
    policy = ctx.contract.loop_policy
    sampler = SpecSampler(ctx.config.get("search_seed", 2026), ctx.contract, ctx.profile)
    limit = ctx.config.get(
        "random_search_experiments", 2 * policy.max_rounds + policy.initial_tool_search
    )
    count = 0
    while count < limit:
        if not ctx.budget.can_reserve(ctx.experiment_cost()):
            state.stop_reason = "budget_exhausted"
            break
        spec = sampler.sample_new(lambda s: state.duplicate_of(s) is not None)
        if spec is None:
            state.stop_reason = "space_exhausted"
            break
        validate_experiment_spec(spec, ctx.contract, numeric_minima=ctx.minima)
        count += 1
        run_experiment(
            ctx,
            state,
            spec,
            experiment_id=f"random-{count:02d}",
            origin="tool_search",
            round_index=0,
        )
    state.stop_reason = state.stop_reason or "experiment_limit"
    ctx.ledger.append("stop_decided", reason_code=state.stop_reason)


# ---------------------------------------------------------------------------- finalize


def finalize(ctx: RunContext, state: ResearchState) -> dict[str, Any]:
    contract = ctx.contract
    runner = ctx.runner
    baseline = state.baseline
    passing = [
        record
        for record in state.experiments
        if record.vs_baseline is not None and record.vs_baseline.policy_status == "candidate_pass"
    ]
    passing.sort(
        key=lambda record: (
            -(record.result.mean_score or -1),
            record.result.duration_seconds,
            record.spec_hash,
        )
    )
    finalist = passing[0] if passing else None
    delivered = baseline
    confirmation_status = "not_required_no_candidate"
    confirmation_deltas: list[float] = []
    ctx.budget.set_tail_reserve(ResourceVector())
    if finalist is not None:
        confirmation_refs: list[str] = []
        for seed in contract.decision_policy.confirmation_split_seeds:
            candidate_run = runner.execute(
                finalist.spec,
                contract,
                purpose="confirmation_candidate",
                split_seed=seed,
                experiment_id=f"confirm-candidate-{seed}",
            )
            baseline_run = runner.execute(
                baseline.spec,
                contract,
                purpose="confirmation_baseline",
                split_seed=seed,
                experiment_id=f"confirm-baseline-{seed}",
            )
            confirmation_refs.extend([candidate_run.artifact_ref, baseline_run.artifact_ref])
            if candidate_run.status == "ok" and baseline_run.status == "ok":
                deltas = [
                    a - b
                    for a, b in zip(
                        candidate_run.fold_scores, baseline_run.fold_scores, strict=True
                    )
                ]
                confirmation_deltas.append(sum(deltas) / len(deltas))
        confirmation = evaluate_confirmation(
            finalist.experiment_id,
            confirmation_deltas,
            contract.decision_policy.min_effect,
            contract.decision_policy.min_positive_fraction,
            tuple(confirmation_refs),
        )
        atomic_write_json(ctx.run_dir / "confirmation.json", confirmation.model_dump(mode="json"))
        ctx.ledger.append("confirmation_completed", artifact_ref="confirmation.json")
        confirmation_status = confirmation.policy_status
        if confirmation.policy_status == "confirmed_pass":
            delivered = finalist
    refit = runner.execute(
        delivered.spec, contract, purpose="final_refit", experiment_id="final-refit"
    )
    if refit.status != "ok":
        ctx.ledger.append("refit_failed", artifact_ref=refit.artifact_ref)
        raise RuntimeError(f"final refit failed: {refit.error}")
    ctx.ledger.append("refit_completed", artifact_ref=refit.artifact_ref)
    model_path = ctx.run_dir / "delivery" / "model.joblib"
    delivery = {
        "run_id": ctx.run_id,
        "system": ctx.system,
        "contract_hash": stable_hash(contract),
        "dataset_hash": contract.dataset_hash,
        "delivered_experiment_id": delivered.experiment_id,
        "delivered_spec": delivered.spec.model_dump(mode="json"),
        "delivered_spec_hash": delivered.spec_hash,
        "development_cv_score": delivered.result.mean_score,
        "model_ref": "delivery/model.joblib",
        "model_hash": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "confirmation_status": confirmation_status,
        "frozen_at": utc_now(),
    }
    atomic_write_json(ctx.run_dir / "delivery" / "frozen_delivery.json", delivery)
    ctx.ledger.append("delivery_frozen", artifact_ref="delivery/frozen_delivery.json")
    return _summary(ctx, state, delivery, finalist, confirmation_status, confirmation_deltas)


def _summary(
    ctx: RunContext,
    state: ResearchState,
    delivery: dict[str, Any],
    finalist: ExperimentRecord | None,
    confirmation_status: str,
    confirmation_deltas: list[float],
) -> dict[str, Any]:
    explored = [record for record in state.experiments if record.origin != "baseline"]
    llm_lines = []
    calls_path = ctx.run_dir / "llm_calls.jsonl"
    if calls_path.exists():
        llm_lines = [
            json.loads(line) for line in calls_path.read_text(encoding="utf-8").splitlines()
        ]
    by_role: dict[str, dict[str, int]] = {}
    for line in llm_lines:
        role = by_role.setdefault(line["role"], {"calls": 0, "input_tokens": 0, "output_tokens": 0})
        role["calls"] += 1
        role["input_tokens"] += int(line["details"].get("input_tokens", 0))
        role["output_tokens"] += int(line["details"].get("output_tokens", 0))
    direction_changes = {"agent": 0, "rule": 0, "error": 0}
    for record in state.rounds:
        if record.direction_changed:
            direction_changes[record.trigger_source] += 1
    hypothesis_verdicts: dict[str, int] = {}
    for record in explored:
        if record.hypothesis_check is not None:
            key = record.hypothesis_check.policy_status
            hypothesis_verdicts[key] = hypothesis_verdicts.get(key, 0) + 1
    budget = ctx.budget.summary()
    run_config = json.loads((ctx.run_dir / "run_config.json").read_text(encoding="utf-8"))
    return {
        "run_id": ctx.run_id,
        "system": ctx.system,
        "task_id": ctx.contract.task_id,
        "code_version": code_version_label(run_config.get("git")),
        "git": run_config.get("git"),
        "proposal_source": run_config["proposal_source"],
        "primary_metric": ctx.contract.primary_metric,
        "min_effect": ctx.contract.decision_policy.min_effect,
        "baseline_score": state.baseline.result.mean_score,
        "exploration_best_id": state.best_id,
        "exploration_best_score": state.best.result.mean_score,
        "finalist_id": finalist.experiment_id if finalist else None,
        "confirmation_status": confirmation_status,
        "confirmation_deltas": confirmation_deltas,
        "delivered_experiment_id": delivery["delivered_experiment_id"],
        "delivered_spec_hash": delivery["delivered_spec_hash"],
        "delivered_dev_score": delivery["development_cv_score"],
        "model_ref": delivery["model_ref"],
        "stop_reason": state.stop_reason,
        "wall_seconds": round(ctx.elapsed(), 2),
        "counts": {
            "rounds": len(state.rounds),
            "experiments": len(explored),
            "proposer_experiments": sum(r.origin == "proposer" for r in explored),
            "tool_search_experiments": sum(r.origin == "tool_search" for r in explored),
            "failed_experiments": sum(r.result.status != "ok" for r in explored),
            "passed_vs_baseline": sum(
                r.vs_baseline is not None and r.vs_baseline.policy_status == "candidate_pass"
                for r in explored
            ),
            "duplicates_blocked": state.duplicates_blocked,
            "invalid_rejected": state.invalid_rejected,
            "empty_rounds": sum(
                r.proposal_error is not None or not r.selected for r in state.rounds
            ),
            "direction_changes": direction_changes,
            "hypothesis_verdicts": hypothesis_verdicts,
        },
        "llm": {
            "calls": len(llm_lines),
            "by_role": by_role,
            "requests": budget["used"]["llm_requests"],
            "tokens": budget["used"]["llm_tokens"],
            "cost_usd": budget["used"]["cost_usd"],
            "unknown": budget["unknown"],
        },
        "trajectory": [
            {
                "experiment_id": record.experiment_id,
                "origin": record.origin,
                "round": record.round_index,
                "mean_score": record.result.mean_score,
                "best_score_after": record.best_score_after,
                "elapsed_seconds": round(record.elapsed_seconds, 2),
                "llm_tokens_so_far": record.llm_tokens_so_far,
            }
            for record in state.experiments
        ],
        "experiments": [record.summary() for record in state.experiments],
        "budget": budget,
    }


# ---------------------------------------------------------------------------- entry points


def make_agents(config: dict[str, Any], proposer_kind: str) -> tuple[Proposer, Critic | None]:
    if proposer_kind == "scripted":
        return ScriptedProposer(), None
    if proposer_kind == "llm":
        load_dotenv(PROJECT_ROOT / ".env")
        settings = LLMSettings.from_config(config)
        return PydanticAIProposer(settings), PydanticAICritic(settings)
    raise ValueError(f"unknown proposer kind: {proposer_kind}")


def run_research(
    config: dict[str, Any],
    system: str,
    runs_root: Path = Path("runs"),
    data_root: Path = Path("data"),
    *,
    proposer: Proposer | None = None,
    critic: Critic | None = None,
    proposer_kind: str | None = None,
) -> dict[str, Any]:
    if system != "random_search" and proposer is None:
        proposer, default_critic = make_agents(
            config, proposer_kind or config.get("proposer", "scripted")
        )
        critic = critic or default_critic
    source = "none" if system == "random_search" else proposer.source  # type: ignore[union-attr]
    ctx, state = setup_run(config, system, runs_root, data_root, source)
    if system == "random_search":
        explore_random(ctx, state)
    else:
        explore_loop(
            ctx,
            state,
            proposer,
            critic,
            schedule=system == "budgetlab",  # type: ignore[arg-type]
        )
    summary = finalize(ctx, state)
    write_report(ctx.run_dir, summary)
    ctx.ledger.append("run_terminal", artifact_ref="summary.json", reason_code="completed")
    return summary


def reproduce_run(run_id: str, runs_root: Path = Path("runs")) -> dict[str, Any]:
    run_dir = runs_root / run_id
    contract = TaskContract.model_validate_json(
        (run_dir / "contract.json").read_text(encoding="utf-8")
    )
    run_config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
    delivery = json.loads(
        (run_dir / "delivery" / "frozen_delivery.json").read_text(encoding="utf-8")
    )
    spec = ExperimentSpec.model_validate(delivery["delivered_spec"])
    bundle = load_development(contract.dataset_ref, Path(run_config["data_root"]))
    if bundle.dataset_hash != contract.dataset_hash:
        raise ValueError("dataset hash changed; refusing reproduction")
    features = bundle.features[list(contract.approved_feature_columns)]
    pipeline = build_pipeline(spec, features, contract.search_training_seed)
    pipeline.fit(features, bundle.target)
    destination = (
        run_dir
        / "reproductions"
        / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + f"-{uuid.uuid4().hex[:4]}")
    )
    destination.mkdir(parents=True, exist_ok=False)
    model_path = destination / "model.joblib"
    joblib.dump(pipeline, model_path)
    result = {
        "run_id": run_id,
        "status": "ok",
        "fit_attempts": 1,
        "dataset_hash": bundle.dataset_hash,
        "spec_hash": spec_hash(spec),
        "model_ref": str(model_path),
    }
    atomic_write_json(destination / "reproduction.json", result)
    return result


def replay_run(run_id: str, runs_root: Path = Path("runs")) -> dict[str, Any]:
    events = EventLedger(run_id, runs_root / run_id).read_events()
    return {
        "run_id": run_id,
        "mode": "replay",
        "event_count": len(events),
        "fit_attempts_started_by_replay": 0,
        "llm_requests_started_by_replay": 0,
        "terminal_event": events[-1]["event_type"] if events else None,
        "events_by_type": _count(event["event_type"] for event in events),
    }


def _count(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


__all__ = [
    "ExecutionResult",
    "SYSTEMS",
    "replay_run",
    "reproduce_run",
    "run_research",
]
