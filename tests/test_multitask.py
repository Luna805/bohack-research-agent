"""Offline unit tests for multiclass and regression task support.

These tests never spawn a training subprocess or touch the network; the end-to-end path is
exercised by the ``iris`` (multiclass) and ``diabetes`` (regression) demo tasks via the CLI.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

from budgetlab.evaluator import evaluate_candidate, result_problem
from budgetlab.pipeline import build_pipeline, score_predictions
from budgetlab.schemas import (
    ExecutionResult,
    ExperimentSpec,
    ForestRegressorSpec,
    ForestSpec,
    RidgeSpec,
    metric_direction,
)
from budgetlab.tasks import TASKS, get_task


def _result(name: str, scores: tuple[float, ...], metric: str, **overrides) -> ExecutionResult:
    values = dict(
        experiment_id=name,
        purpose="exploration",
        status="ok",
        split_seed=1,
        fold_scores=scores,
        mean_score=float(np.mean(scores)),
        fit_attempts=len(scores),
        fit_completed=len(scores),
        fold_hash="folds-a",
        dataset_hash="data-a",
        metric=metric,
        duration_seconds=0.1,
        artifact_ref=f"experiments/{name}.json",
    )
    values.update(overrides)
    return ExecutionResult(**values)


def test_metric_direction() -> None:
    assert metric_direction("f1_macro") == "maximize"
    assert metric_direction("accuracy") == "maximize"
    assert metric_direction("r2") == "maximize"
    assert metric_direction("rmse") == "minimize"
    assert metric_direction("mae") == "minimize"


def test_minimize_direction_flips_verdict() -> None:
    base = _result("baseline", (1.0, 1.1, 0.9), "rmse")
    cand = _result("cand", (0.8, 0.9, 0.7), "rmse")
    record = evaluate_candidate(cand, base, 0.1, direction="minimize")
    assert record.policy_status == "candidate_pass"
    assert record.mean_paired_delta is not None and record.mean_paired_delta < 0


def test_regression_scores_may_leave_zero_one_interval() -> None:
    assert result_problem(_result("ok", (50.0, 52.0, 51.0), "rmse")) is None


def test_classification_scores_still_bounded() -> None:
    bad = _result("bad", (0.6, 1.5, 0.7), "f1_macro")
    assert result_problem(bad) == "result_invalid_fold_score"


def test_score_predictions_regression() -> None:
    frame = pd.DataFrame({"x": [0.0, 1.0, 2.0, 3.0, 4.0]})
    target = pd.Series([0.0, 2.0, 4.0, 6.0, 8.0])
    spec = ExperimentSpec(model=RidgeSpec(family="ridge"))
    pipe = build_pipeline(spec, frame, training_seed=0)
    pipe.fit(frame, target)
    assert score_predictions("r2", target, pipe, frame) > 0.9
    assert score_predictions("rmse", target, pipe, frame) >= 0.0


def test_score_predictions_multiclass() -> None:
    rng = np.random.default_rng(0)
    frame = pd.DataFrame(rng.normal(size=(60, 2)), columns=["a", "b"])
    target = pd.Series(np.repeat([0, 1, 2], 20))
    spec = ExperimentSpec(model=ForestSpec(family="random_forest", n_estimators=20))
    pipe = build_pipeline(spec, frame, training_seed=0)
    pipe.fit(frame, target)
    assert 0.0 <= score_predictions("f1_macro", target, pipe, frame) <= 1.0
    assert 0.0 <= score_predictions("accuracy", target, pipe, frame) <= 1.0


def test_build_pipeline_picks_regressor() -> None:
    frame = pd.DataFrame({"x": [0.0, 1.0, 2.0]})
    spec = ExperimentSpec(model=ForestRegressorSpec(family="random_forest_regressor"))
    pipe = build_pipeline(spec, frame, training_seed=0)
    assert isinstance(pipe.named_steps["model"], RandomForestRegressor)


def test_demo_tasks_registered() -> None:
    assert TASKS["iris"].task_type == "multiclass"
    assert TASKS["iris"].primary_metric == "f1_macro"
    assert TASKS["diabetes"].task_type == "regression"
    assert TASKS["diabetes"].primary_metric == "r2"
    assert get_task("iris").task_type == "multiclass"
