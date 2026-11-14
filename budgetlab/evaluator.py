"""Program-side verdicts. Engineering thresholds, not significance tests.

Every paired comparison first checks that both results are complete, finite and genuinely
paired (same split seed, same validation rows per fold, same data and metric). A comparison
that fails these checks is ``invalid`` with a concrete reason; it never counts as evidence
for or against a hypothesis.
"""

from __future__ import annotations

import math
import statistics

from .schemas import (
    REGRESSION_METRICS,
    CalibrationReport,
    Direction,
    EvaluationRecord,
    ExecutionResult,
)


def result_problem(result: ExecutionResult, label: str = "result") -> str | None:
    """Why a single result cannot serve as evidence, or None when it can."""
    if result.status != "ok":
        return f"{label}_{result.status}"
    if not result.fold_scores or result.mean_score is None:
        return f"{label}_missing_scores"
    if result.metric in REGRESSION_METRICS:
        bad = any(not math.isfinite(s) for s in result.fold_scores)
    else:
        bad = any(not math.isfinite(s) or s < 0 or s > 1 for s in result.fold_scores)
    if bad:
        return f"{label}_invalid_fold_score"
    if not math.isclose(result.mean_score, statistics.mean(result.fold_scores), abs_tol=1e-9):
        return f"{label}_mean_fold_mismatch"
    if result.fit_completed != len(result.fold_scores):
        return f"{label}_incomplete_fits"
    return None


def comparison_problem(candidate: ExecutionResult, comparator: ExecutionResult) -> str | None:
    """Why two results are not a valid same-fold pair, or None when they are."""
    for result, label in ((candidate, "candidate"), (comparator, "comparator")):
        problem = result_problem(result, label)
        if problem is not None:
            return problem
    if candidate.split_seed != comparator.split_seed:
        return "split_seed_mismatch"
    if len(candidate.fold_scores) != len(comparator.fold_scores):
        return "fold_count_mismatch"
    if candidate.fold_hash is None or candidate.fold_hash != comparator.fold_hash:
        return "unpaired_folds"
    if candidate.dataset_hash != comparator.dataset_hash:
        return "dataset_mismatch"
    if candidate.metric != comparator.metric:
        return "metric_mismatch"
    return None


def calibrate(
    protocol_hash: str, results: list[ExecutionResult], min_effect_floor: float
) -> CalibrationReport:
    if len(results) < 3:
        raise ValueError("calibration requires at least three split results")
    for result in results:
        problem = result_problem(result, result.experiment_id)
        if problem is not None:
            raise ValueError(f"invalid calibration result: {problem}")
    if len({(r.dataset_hash, r.metric) for r in results}) != 1:
        raise ValueError("calibration results disagree on data or metric")
    scores = tuple(float(result.mean_score) for result in results)  # type: ignore[arg-type]
    noise_floor = statistics.stdev(scores)
    return CalibrationReport(
        protocol_hash=protocol_hash,
        split_scores=scores,
        noise_floor=noise_floor,
        min_effect=max(min_effect_floor, noise_floor),
        evidence_refs=tuple(result.artifact_ref for result in results),
    )


def evaluate_candidate(
    candidate: ExecutionResult,
    baseline: ExecutionResult,
    min_effect: float,
    direction: Direction = "maximize",
) -> EvaluationRecord:
    """Paired same-fold comparison against ``baseline`` (any frozen comparator)."""
    evidence = (candidate.artifact_ref, baseline.artifact_ref)
    problem = comparison_problem(candidate, baseline)
    if problem is not None:
        if candidate.status != "ok":
            execution_status = candidate.status
        elif baseline.status != "ok":
            execution_status = baseline.status
        else:
            execution_status = "invalid"
        return EvaluationRecord(
            experiment_id=candidate.experiment_id,
            execution_status=execution_status,
            policy_status="invalid",
            mean_score=candidate.mean_score,
            comparator_experiment_id=baseline.experiment_id,
            invalid_reason=problem,
            evidence_refs=evidence,
        )
    deltas = tuple(
        candidate_score - baseline_score
        for candidate_score, baseline_score in zip(
            candidate.fold_scores, baseline.fold_scores, strict=True
        )
    )
    mean_delta = statistics.mean(deltas)
    passed = mean_delta >= min_effect if direction == "maximize" else mean_delta <= -min_effect
    return EvaluationRecord(
        experiment_id=candidate.experiment_id,
        execution_status="ok",
        policy_status="candidate_pass" if passed else "not_met",
        mean_score=candidate.mean_score,
        mean_paired_delta=mean_delta,
        fold_scores=candidate.fold_scores,
        comparator_experiment_id=baseline.experiment_id,
        evidence_refs=evidence,
    )


def evaluate_confirmation(
    experiment_id: str,
    deltas: list[float],
    min_effect: float,
    min_positive_fraction: float,
    evidence_refs: tuple[str, ...],
    *,
    expected_splits: int = 3,
    direction: Direction = "maximize",
) -> EvaluationRecord:
    if len(deltas) != expected_splits:
        return EvaluationRecord(
            experiment_id=experiment_id,
            execution_status="invalid",
            policy_status="inconclusive",
            confirmation_deltas=tuple(deltas),
            invalid_reason=f"only {len(deltas)} of {expected_splits} confirmation splits valid",
            evidence_refs=evidence_refs,
        )
    median_delta = statistics.median(deltas)
    if direction == "maximize":
        positive_fraction = sum(delta > 0 for delta in deltas) / len(deltas)
        passed = median_delta >= min_effect and positive_fraction >= min_positive_fraction
    else:
        positive_fraction = sum(delta < 0 for delta in deltas) / len(deltas)
        passed = median_delta <= -min_effect and positive_fraction >= min_positive_fraction
    return EvaluationRecord(
        experiment_id=experiment_id,
        execution_status="ok",
        policy_status="confirmed_pass" if passed else "not_met",
        mean_paired_delta=median_delta,
        confirmation_deltas=tuple(deltas),
        evidence_refs=evidence_refs,
    )
