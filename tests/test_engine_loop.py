from __future__ import annotations

import json

import pytest

import budgetlab.controller as controller
from budgetlab.budget import Budget
from budgetlab.controller import (
    RunContext,
    choose_candidates,
    explore_loop,
    finalization_reserve,
    finalize,
    metered_call,
    screen_candidates,
    stop_reason,
)
from budgetlab.data import load_development
from budgetlab.evaluator import evaluate_candidate
from budgetlab.ledger import EventLedger
from budgetlab.proposers import CallOutcome
from budgetlab.schemas import (
    BudgetLimits,
    Candidate,
    CriticAdvice,
    ExecutionResult,
    ExperimentSpec,
    Hypothesis,
    LogisticSpec,
    LoopPolicy,
    PreprocessingSpec,
    ProposalBatch,
    ResourceVector,
)
from budgetlab.search import baseline_spec
from budgetlab.state import ExperimentRecord, ResearchState
from budgetlab.tasks import approved_features, get_task


def _result(experiment_id: str, score: float, *, seconds: float = 1.0) -> ExecutionResult:
    return ExecutionResult(
        experiment_id=experiment_id,
        purpose="exploration",
        status="ok",
        split_seed=42,
        fold_scores=(score, score, score),
        mean_score=score,
        fit_attempts=3,
        fit_completed=3,
        fold_hash="folds",
        dataset_hash="dataset",
        metric="f1_macro",
        duration_seconds=seconds,
        artifact_ref=f"experiments/{experiment_id}.json",
    )


def _context(
    tmp_path, make_contract, *, policy: LoopPolicy | None = None, limits=None, seconds=1.0
):
    contract = make_contract()
    if policy is not None:
        contract = contract.model_copy(update={"loop_policy": policy})
    if limits is not None:
        contract = contract.model_copy(update={"budgets": limits})
    run_dir = tmp_path / "run"
    ledger = EventLedger("loop-run", run_dir)
    budget = Budget(
        contract.budgets, run_dir / "budget.json", ledger, tail_reserve=ResourceVector()
    )
    baseline = ExperimentRecord(
        experiment_id="baseline",
        origin="baseline",
        round_index=0,
        spec=baseline_spec(),
        spec_hash="baseline-hash",
        result=_result("baseline", 0.60, seconds=seconds),
        vs_baseline=None,
        vs_previous_best=None,
        previous_best_id=None,
    )
    state = ResearchState(baseline=baseline, min_effect=contract.decision_policy.min_effect)
    ctx = RunContext(
        run_id="loop-run",
        run_dir=run_dir,
        system="budgetlab",
        config={"search_seed": 1},
        ledger=ledger,
        budget=budget,
        runner=None,  # type: ignore[arg-type]
        card={"task_id": "breast_cancer"},
        profile={"columns": [], "rows": 100, "positive_rate": 0.5},
        contract=contract,
        bundle=None,  # type: ignore[arg-type]
        minima={},
        started=0.0,
    )
    return ctx, state


def _candidate(
    candidate_id: str,
    c: float,
    *,
    evidence_refs: tuple[str, ...] = ("baseline", "eda"),
    comparator: str = "baseline",
    spec: ExperimentSpec | None = None,
) -> Candidate:
    return Candidate(
        candidate_id=candidate_id,
        hypothesis=Hypothesis(
            statement="Test a deterministic regularisation change.",
            evidence_refs=evidence_refs,
            comparator_experiment_id=comparator,
            decision_policy_id="practical_gain_v2",
            proposed_change=f"C={c}",
        ),
        experiment=spec
        or ExperimentSpec(
            model=LogisticSpec(family="logistic_regression", c=c),
            preprocessing=PreprocessingSpec(numeric_scaler="standard"),
        ),
    )


def _batch(first: Candidate, second: Candidate) -> ProposalBatch:
    return ProposalBatch(
        previous_result_interpretation="fixture",
        intent="refine",
        direction="regularisation",
        candidates=(first, second),
    )


class _SequenceProposer:
    source = "scripted"

    def __init__(self, batches: list[ProposalBatch]) -> None:
        self.batches = list(batches)
        self.contexts: list[dict] = []

    def estimate(self, context: dict) -> ResourceVector:
        return ResourceVector()

    def propose(self, context: dict) -> CallOutcome:
        self.contexts.append(context)
        return CallOutcome(output=self.batches.pop(0))


class _Critic:
    source = "scripted"

    def __init__(self) -> None:
        self.calls = 0

    def estimate(self, context: dict) -> ResourceVector:
        return ResourceVector()

    def review(self, context: dict) -> CallOutcome:
        self.calls += 1
        return CallOutcome(
            output=CriticAdvice(
                explanation="No improvement yet.",
                evidence_refs=("baseline",),
                next_focus="Try a new family.",
            )
        )


def _fake_run(scores: list[float]):
    def run(ctx, state, spec, *, experiment_id, origin, round_index, candidate=None):
        score = scores.pop(0)
        result = _result(experiment_id, score)
        previous_best = state.best
        vs_baseline = evaluate_candidate(result, state.baseline.result, state.min_effect)
        vs_best = evaluate_candidate(result, previous_best.result, state.min_effect)
        hypothesis_check = (
            evaluate_candidate(
                result,
                state.get(candidate.hypothesis.comparator_experiment_id).result,
                state.min_effect,
            )
            if candidate is not None
            else None
        )
        record = ExperimentRecord(
            experiment_id=experiment_id,
            origin=origin,
            round_index=round_index,
            spec=spec,
            spec_hash=f"{experiment_id}-hash",
            result=result,
            vs_baseline=vs_baseline,
            vs_previous_best=vs_best.mean_paired_delta,
            previous_best_id=previous_best.experiment_id,
            hypothesis_check=hypothesis_check,
        )
        return record, state.add(record)

    return run


def test_screening_requires_every_evidence_reference_and_legal_spec(
    tmp_path, make_contract
) -> None:
    ctx, state = _context(tmp_path, make_contract)
    valid, rejected = screen_candidates(
        ctx,
        state,
        _batch(
            _candidate("valid", 0.2),
            _candidate("partial", 0.3, evidence_refs=("baseline", "not-real")),
        ),
    )
    assert [candidate.candidate_id for candidate in valid] == ["valid"]
    assert rejected == [
        {"candidate_id": "partial", "reason": "one or more evidence_refs are unavailable"}
    ]

    extras, rejected = screen_candidates(
        ctx,
        state,
        _batch(
            _candidate("extras", 0.4, evidence_refs=("eda", "calibration")),
            _candidate("bad-comparator", 0.5, comparator="missing"),
        ),
    )
    assert [candidate.candidate_id for candidate in extras] == ["extras"]
    assert rejected[0]["reason"] == "unknown comparator missing"

    invalid_spec = ExperimentSpec(
        model=LogisticSpec(family="logistic_regression", c=0.6),
        preprocessing=PreprocessingSpec(numeric_scaler="standard"),
        feature_actions=({"kind": "drop_columns", "columns": ("not-approved",)},),
    )
    valid, rejected = screen_candidates(
        ctx,
        state,
        _batch(_candidate("illegal", 0.6, spec=invalid_spec), _candidate("other", 0.7)),
    )
    assert [candidate.candidate_id for candidate in valid] == ["other"]
    assert rejected[0]["reason"].startswith("invalid spec:")

    same_spec = _candidate("same-1", 0.75)
    valid, rejected = screen_candidates(
        ctx,
        state,
        _batch(same_spec, _candidate("same-2", 0.75)),
    )
    assert [candidate.candidate_id for candidate in valid] == ["same-1"]
    assert rejected == [
        {"candidate_id": "same-2", "reason": "duplicate of the other candidate in this batch"}
    ]

    state.seen["historical"] = "old-experiment"
    duplicate = _candidate("duplicate", 0.8)
    state.seen[controller.spec_hash(duplicate.experiment)] = "old-experiment"
    valid, rejected = screen_candidates(ctx, state, _batch(duplicate, _candidate("new", 0.9)))
    assert not [candidate for candidate in valid if candidate.candidate_id == "duplicate"]
    assert rejected[0]["reason"].startswith("duplicate of experiment")
    assert state.duplicates_blocked == 1


def test_candidate_selection_runs_two_only_when_cheap_and_budgeted(tmp_path, make_contract) -> None:
    cheap_ctx, cheap_state = _context(tmp_path / "cheap", make_contract, seconds=1.0)
    candidates = [_candidate("first", 0.2), _candidate("second", 0.3)]
    selected, not_run = choose_candidates(cheap_ctx, cheap_state, candidates)
    assert [candidate.candidate_id for candidate in selected] == ["first", "second"]
    assert not not_run

    limited = BudgetLimits(
        max_experiments=1,
        max_fits=3,
        max_total_seconds=10,
        experiment_timeout_seconds=10,
    )
    limited_ctx, limited_state = _context(
        tmp_path / "limited", make_contract, limits=limited, seconds=1.0
    )
    selected, not_run = choose_candidates(limited_ctx, limited_state, candidates)
    assert [candidate.candidate_id for candidate in selected] == ["first"]
    assert not_run == [{"candidate_id": "second", "reason": "budget allows one"}]

    slow_ctx, slow_state = _context(tmp_path / "slow", make_contract, seconds=31.0)
    selected, not_run = choose_candidates(slow_ctx, slow_state, candidates)
    assert [candidate.candidate_id for candidate in selected] == ["first"]
    assert not_run == [{"candidate_id": "second", "reason": "not cheap enough to run both"}]


def test_loop_stops_after_consecutive_invalid_batches(tmp_path, make_contract) -> None:
    policy = LoopPolicy(max_rounds=5, initial_tool_search=0, stagnation_stop=5)
    ctx, state = _context(tmp_path, make_contract, policy=policy)
    invalid = _batch(
        _candidate("bad-1", 0.2, evidence_refs=("missing",)),
        _candidate("bad-2", 0.3, evidence_refs=("missing",)),
    )
    proposer = _SequenceProposer([invalid, invalid])
    explore_loop(ctx, state, proposer, None, schedule=False)
    assert state.stop_reason == "no_valid_candidates"
    assert len(state.rounds) == 2
    assert all(round_record.rejected for round_record in state.rounds)


def test_stagnation_replans_once_per_cycle_and_improvement_resets_state(
    tmp_path, make_contract, monkeypatch
) -> None:
    policy = LoopPolicy(
        max_rounds=3,
        initial_tool_search=0,
        tool_search_batch=1,
        stagnation_tool_search=1,
        stagnation_replan=1,
        stagnation_stop=3,
    )
    ctx, state = _context(tmp_path, make_contract, policy=policy)
    batches = [
        _batch(_candidate("r1a", 0.2), _candidate("r1b", 0.3)),
        _batch(_candidate("r2a", 0.4), _candidate("r2b", 0.5)),
        _batch(_candidate("r3a", 0.6), _candidate("r3b", 0.7)),
    ]
    proposer = _SequenceProposer(batches)
    critic = _Critic()
    tool_search_calls: list[str] = []

    def no_improvement_tool_search(ctx, state, sampler, count, reason):
        tool_search_calls.append(reason)
        return False

    monkeypatch.setattr(controller, "run_tool_search", no_improvement_tool_search)
    monkeypatch.setattr(
        controller,
        "run_experiment",
        _fake_run([0.601, 0.602, 0.61, 0.60, 0.611, 0.61]),
    )
    explore_loop(ctx, state, proposer, critic, schedule=True)

    assert state.stop_reason == "max_rounds"
    assert tool_search_calls == ["stagnation"]
    assert critic.calls == 1
    assert [context["mode"] for context in proposer.contexts] == ["normal", "replan", "normal"]
    assert state.stagnation == 1
    assert not state.tool_search_since_improvement
    assert not state.critic_since_improvement


def test_stop_reasons_and_tail_reserve_protect_finalization(
    tmp_path, make_contract, smoke_config, data_root
) -> None:
    policy = LoopPolicy(max_rounds=1, initial_tool_search=0, stagnation_stop=2)
    ctx, state = _context(tmp_path / "stops", make_contract, policy=policy)
    proposer = _SequenceProposer([])
    assert stop_reason(ctx, state, proposer, {}) is None
    state.rounds.append(object())  # type: ignore[arg-type]
    assert stop_reason(ctx, state, proposer, {}) == "max_rounds"

    bundle = load_development("breast_cancer", data_root)
    task = get_task("breast_cancer")
    protocol = controller.build_protocol(
        smoke_config,
        bundle,
        task.card,
        approved_features(task.card, list(bundle.features.columns)),
        "holdout-hash",
    )
    tail = finalization_reserve(protocol)
    assert tail.experiments == 7
    assert tail.fits == 6 * protocol.cv_folds + 1
    assert tail.seconds == 7 * protocol.budgets.experiment_timeout_seconds

    limits = BudgetLimits(
        max_experiments=8,
        max_fits=tail.fits + protocol.cv_folds,
        max_total_seconds=int(tail.seconds + protocol.budgets.experiment_timeout_seconds),
        experiment_timeout_seconds=protocol.budgets.experiment_timeout_seconds,
    )
    ledger = EventLedger("tail-run", tmp_path / "tail")
    budget = Budget(limits, tmp_path / "tail" / "budget.json", ledger, tail_reserve=tail)
    exploration = ResourceVector(
        experiments=1,
        fits=protocol.cv_folds,
        seconds=protocol.budgets.experiment_timeout_seconds,
    )
    budget.reserve("exploration", exploration)
    budget.settle("exploration", exploration)
    assert not budget.can_reserve(exploration)
    budget.set_tail_reserve(ResourceVector())
    for index in range(6):
        action = f"confirmation-{index}"
        budget.reserve(action, exploration)
        budget.settle(action, exploration)
    refit = ResourceVector(
        experiments=1, fits=1, seconds=protocol.budgets.experiment_timeout_seconds
    )
    budget.reserve("final-refit", refit)
    budget.settle("final-refit", refit)
    assert not any(
        item["status"] == "reserved" for item in budget.summary()["reservations"].values()
    )


def test_run_failure_event_closes_pending_reservations(tmp_path, make_contract) -> None:
    ctx, _ = _context(tmp_path, make_contract)
    ctx.budget.reserve("unclosed", ResourceVector(experiments=1, fits=1, seconds=1))

    controller._record_run_failure(ctx, "finalize", RuntimeError("fixture failure"))

    events = ctx.ledger.read_events()
    assert events[-1]["event_type"] == "run_failed"
    assert events[-1]["details"]["exception_type"] == "RuntimeError"
    assert events[-1]["details"]["phase"] == "finalize"
    assert ctx.budget.summary()["reservations"]["unclosed"]["status"] == "unknown"


def test_metered_call_does_not_hide_unexpected_errors(tmp_path, make_contract) -> None:
    limits = BudgetLimits(
        max_llm_tokens=100,
        max_llm_requests=2,
        max_experiments=20,
        max_fits=60,
        max_total_seconds=300,
        experiment_timeout_seconds=10,
    )
    ctx, _ = _context(tmp_path, make_contract, limits=limits)

    def fail_call(context):
        raise RuntimeError("unexpected proposer bug")

    with pytest.raises(RuntimeError, match="unexpected proposer bug"):
        metered_call(
            ctx,
            role="proposer",
            round_index=1,
            source="fixture",
            estimate=ResourceVector(llm_tokens=10, llm_requests=1),
            call=fail_call,
            context={"mode": "normal"},
        )

    reservation = ctx.budget.summary()["reservations"]["llm:proposer:r01"]
    assert reservation["status"] == "unknown"
    assert reservation["unknown"]["llm_tokens"] == 10
    assert reservation["unknown"]["llm_requests"] == 1


@pytest.mark.parametrize(
    ("scenario", "expected_status", "expected_delivery"),
    [
        ("confirmed", "confirmed_pass", "candidate"),
        ("not_met", "not_met", "baseline"),
        ("inconclusive", "inconclusive", "baseline"),
    ],
)
def test_finalize_delivers_candidate_only_after_confirmation(
    tmp_path,
    make_contract,
    scenario,
    expected_status,
    expected_delivery,
) -> None:
    ctx, state = _context(tmp_path, make_contract)
    (ctx.run_dir / "run_config.json").write_text(
        json.dumps({"git": None, "proposal_source": "scripted"}), encoding="utf-8"
    )
    candidate_result = _result("candidate", 0.62)
    candidate_spec = _candidate("candidate", 0.2).experiment
    comparison = evaluate_candidate(candidate_result, state.baseline.result, state.min_effect)
    candidate = ExperimentRecord(
        experiment_id="candidate",
        origin="proposer",
        round_index=1,
        spec=candidate_spec,
        spec_hash=controller.spec_hash(candidate_spec),
        result=candidate_result,
        vs_baseline=comparison,
        vs_previous_best=comparison.mean_paired_delta,
        previous_best_id="baseline",
    )
    state.add(candidate)
    state.stop_reason = "max_rounds"

    class FinalizeRunner:
        def execute(
            self,
            spec,
            contract,
            *,
            purpose,
            split_seed=None,
            experiment_id=None,
        ):
            if purpose == "final_refit":
                model_path = ctx.run_dir / "delivery" / "model.joblib"
                model_path.parent.mkdir(parents=True, exist_ok=True)
                model_path.write_bytes(b"fixture-model")
                return ExecutionResult(
                    experiment_id=experiment_id,
                    purpose=purpose,
                    status="ok",
                    fit_attempts=1,
                    fit_completed=1,
                    dataset_hash=contract.dataset_hash,
                    metric=contract.primary_metric,
                    artifact_ref=f"experiments/{experiment_id}.json",
                )

            candidate_side = purpose == "confirmation_candidate"
            if scenario == "inconclusive" and candidate_side and split_seed == 137:
                return ExecutionResult(
                    experiment_id=experiment_id,
                    purpose=purpose,
                    status="timeout",
                    split_seed=split_seed,
                    dataset_hash=contract.dataset_hash,
                    metric=contract.primary_metric,
                    artifact_ref=f"experiments/{experiment_id}.json",
                    error="fixture timeout",
                )
            score = 0.60
            if candidate_side:
                score = 0.601 if scenario == "not_met" else 0.62
            return ExecutionResult(
                experiment_id=experiment_id,
                purpose=purpose,
                status="ok",
                split_seed=split_seed,
                fold_scores=(score,) * contract.cv_folds,
                mean_score=score,
                fit_attempts=contract.cv_folds,
                fit_completed=contract.cv_folds,
                fold_hash=f"folds-{split_seed}",
                dataset_hash=contract.dataset_hash,
                metric=contract.primary_metric,
                artifact_ref=f"experiments/{experiment_id}.json",
            )

    ctx.runner = FinalizeRunner()  # type: ignore[assignment]
    summary = finalize(ctx, state)

    assert summary["confirmation_status"] == expected_status
    assert summary["delivered_experiment_id"] == expected_delivery
    delivery = json.loads(
        (ctx.run_dir / "delivery" / "frozen_delivery.json").read_text(encoding="utf-8")
    )
    assert delivery["delivered_experiment_id"] == expected_delivery
