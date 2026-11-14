from __future__ import annotations

import statistics

import pytest

from budgetlab.evaluator import calibrate, evaluate_candidate, evaluate_confirmation
from budgetlab.schemas import ExecutionResult


def result(name: str, score: float, **overrides) -> ExecutionResult:
    values = dict(
        experiment_id=name,
        purpose="calibration",
        status="ok",
        split_seed=1,
        fold_scores=(score,),
        mean_score=score,
        fit_attempts=1,
        fit_completed=1,
        fold_hash="folds-a",
        dataset_hash="data-a",
        metric="f1_macro",
        duration_seconds=0.1,
        artifact_ref=f"experiments/{name}.json",
    )
    values.update(overrides)
    return ExecutionResult(**values)


def paired(name: str, scores: tuple[float, ...], **overrides) -> ExecutionResult:
    values = dict(
        fold_scores=scores,
        fit_attempts=len(scores),
        fit_completed=len(scores),
        purpose="exploration",
    )
    values.update(overrides)
    return result(name, statistics.mean(scores), **values)


def test_calibration_uses_sample_standard_deviation() -> None:
    scores = [0.80, 0.82, 0.81]
    report = calibrate("protocol", [result(str(i), score) for i, score in enumerate(scores)], 0.002)
    assert report.ddof == 1
    assert report.noise_floor == statistics.stdev(scores)
    assert report.min_effect == max(0.002, statistics.stdev(scores))


def test_confirmation_requires_median_threshold_and_positive_fraction() -> None:
    record = evaluate_confirmation(
        "candidate",
        [0.004, 0.003, -0.001],
        0.004,
        2 / 3,
        ("a", "b", "c"),
    )
    assert record.policy_status == "not_met"
    passed = evaluate_confirmation(
        "candidate",
        [0.005, 0.004, -0.001],
        0.004,
        2 / 3,
        ("a", "b", "c"),
    )
    assert passed.policy_status == "confirmed_pass"


def test_valid_pair_is_judged_on_same_fold_deltas() -> None:
    base = paired("baseline", (0.60, 0.62, 0.61))
    cand = paired("cand", (0.63, 0.64, 0.62))
    record = evaluate_candidate(cand, base, 0.005)
    assert record.policy_status == "candidate_pass"
    assert record.invalid_reason is None
    assert abs(record.mean_paired_delta - statistics.mean([0.03, 0.02, 0.01])) < 1e-12


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"split_seed": 2}, "split_seed_mismatch"),
        ({"fold_hash": "folds-b"}, "unpaired_folds"),
        ({"fold_hash": None}, "unpaired_folds"),
        ({"dataset_hash": "data-b"}, "dataset_mismatch"),
        ({"metric": "accuracy"}, "metric_mismatch"),
        ({"fit_completed": 2}, "candidate_incomplete_fits"),
        ({"mean_score": 0.9}, "candidate_mean_fold_mismatch"),
        (
            {"fold_scores": (0.63, 1.5, 0.62), "mean_score": 0.9166666666666666},
            "candidate_invalid_fold_score",
        ),
        ({"status": "timeout", "fold_scores": (), "mean_score": None}, "candidate_timeout"),
    ],
)
def test_unpaired_or_broken_evidence_is_invalid(overrides, reason) -> None:
    base = paired("baseline", (0.60, 0.62, 0.61))
    cand = paired("cand", (0.63, 0.64, 0.62), **overrides)
    record = evaluate_candidate(cand, base, 0.005)
    assert record.policy_status == "invalid"
    assert record.invalid_reason == reason


def test_confirmation_with_missing_split_is_inconclusive() -> None:
    record = evaluate_confirmation("cand", [0.01, 0.02], 0.004, 2 / 3, ("a",))
    assert record.policy_status == "inconclusive"
    assert "2 of 3" in record.invalid_reason
