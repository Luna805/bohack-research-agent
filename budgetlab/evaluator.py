from __future__ import annotations

import statistics

from .schemas import CalibrationReport, EvaluationRecord, ExecutionResult


def calibrate(
    protocol_hash: str, results: list[ExecutionResult], min_effect_floor: float
) -> CalibrationReport:
    if len(results) < 3 or any(result.status != "ok" for result in results):
        raise ValueError("calibration requires at least three successful split results")
    scores = tuple(float(result.mean_score) for result in results if result.mean_score is not None)
    if len(scores) != len(results):
        raise ValueError("calibration result is missing a score")
    noise_floor = statistics.stdev(scores)
    return CalibrationReport(
        protocol_hash=protocol_hash,
        split_scores=scores,
        noise_floor=noise_floor,
        min_effect=max(min_effect_floor, noise_floor),
        evidence_refs=tuple(result.artifact_ref for result in results),
    )


def evaluate_candidate(
    candidate: ExecutionResult, baseline: ExecutionResult, min_effect: float
) -> EvaluationRecord:
    """Paired same-fold comparison against ``baseline`` (any frozen comparator)."""
    evidence = (candidate.artifact_ref, baseline.artifact_ref)
    if candidate.status != "ok" or baseline.status != "ok":
        status = candidate.status if candidate.status != "ok" else baseline.status
        return EvaluationRecord(
            experiment_id=candidate.experiment_id,
            execution_status=status,
            policy_status="invalid",
            comparator_experiment_id=baseline.experiment_id,
            evidence_refs=evidence,
        )
    if len(candidate.fold_scores) != len(baseline.fold_scores):
        return EvaluationRecord(
            experiment_id=candidate.experiment_id,
            execution_status="invalid",
            policy_status="invalid",
            comparator_experiment_id=baseline.experiment_id,
            evidence_refs=evidence,
        )
    deltas = tuple(
        candidate_score - baseline_score
        for candidate_score, baseline_score in zip(
            candidate.fold_scores, baseline.fold_scores, strict=True
        )
    )
    mean_delta = statistics.mean(deltas)
    return EvaluationRecord(
        experiment_id=candidate.experiment_id,
        execution_status="ok",
        policy_status="candidate_pass" if mean_delta >= min_effect else "not_met",
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
) -> EvaluationRecord:
    if len(deltas) != 3:
        return EvaluationRecord(
            experiment_id=experiment_id,
            execution_status="invalid",
            policy_status="inconclusive",
            confirmation_deltas=tuple(deltas),
            evidence_refs=evidence_refs,
        )
    median_delta = statistics.median(deltas)
    positive_fraction = sum(delta > 0 for delta in deltas) / len(deltas)
    passed = median_delta >= min_effect and positive_fraction >= min_positive_fraction
    return EvaluationRecord(
        experiment_id=experiment_id,
        execution_status="ok",
        policy_status="confirmed_pass" if passed else "not_met",
        mean_paired_delta=median_delta,
        confirmation_deltas=tuple(deltas),
        evidence_refs=evidence_refs,
    )
