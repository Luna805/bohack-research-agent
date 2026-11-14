from __future__ import annotations

import numpy as np
import pytest
from sklearn.metrics import accuracy_score, f1_score

from budgetlab.evaluation import bootstrap_ci, metric_value


def _sample(n: int = 2000, seed: int = 0):
    rng = np.random.default_rng(seed)
    y_true = (rng.random(n) < 0.2).astype(int)
    noise = rng.random(n) < 0.15
    y_pred = np.where(noise, 1 - y_true, y_true)
    y_score = np.clip(y_pred * 0.7 + rng.random(n) * 0.3, 0, 1)
    return y_true, y_pred, y_score


def test_metric_matches_training_time_definitions() -> None:
    y_true, y_pred, y_score = _sample()
    assert metric_value("f1_macro", y_true, y_pred, y_score) == pytest.approx(
        f1_score(y_true, y_pred, average="macro", labels=[0, 1], zero_division=0)
    )
    assert metric_value("accuracy", y_true, y_pred, y_score) == pytest.approx(
        accuracy_score(y_true, y_pred)
    )
    all_negative = np.zeros_like(y_pred)
    assert metric_value("f1_macro", y_true, all_negative, None) == pytest.approx(
        f1_score(y_true, all_negative, average="macro", labels=[0, 1], zero_division=0)
    )


def test_bootstrap_ci_is_deterministic_and_brackets_the_score() -> None:
    y_true, y_pred, y_score = _sample()
    first = bootstrap_ci("f1_macro", y_true, y_pred, y_score, resamples=300, seed=7)
    second = bootstrap_ci("f1_macro", y_true, y_pred, y_score, resamples=300, seed=7)
    assert first == second
    score = metric_value("f1_macro", y_true, y_pred, y_score)
    assert first[0] < score < first[1]
    assert first[1] - first[0] < 0.1
    auc = bootstrap_ci("roc_auc", y_true, y_pred, y_score, resamples=100, seed=7)
    assert 0.5 < auc[0] < auc[1] <= 1.0
