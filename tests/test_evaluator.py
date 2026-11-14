from __future__ import annotations

import statistics

from budgetlab.evaluator import calibrate, evaluate_confirmation
from budgetlab.schemas import ExecutionResult


def result(name: str, score: float) -> ExecutionResult:
    return ExecutionResult(
        experiment_id=name,
        purpose="calibration",
        status="ok",
        split_seed=1,
        fold_scores=(score,),
        mean_score=score,
        fit_attempts=1,
        fit_completed=1,
        duration_seconds=0.1,
        artifact_ref=f"experiments/{name}.json",
    )


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
