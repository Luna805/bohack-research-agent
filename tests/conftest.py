from __future__ import annotations

import pytest

from budgetlab.contracts import stable_hash
from budgetlab.data import load_dataset, split_manifest
from budgetlab.schemas import BudgetLimits, DecisionPolicy, TaskContract


def _make_contract(*, timeout: int = 10, cv_folds: int = 3, max_fits: int = 60) -> TaskContract:
    bundle = load_dataset()
    _, manifest_hash = split_manifest(bundle, [42, 11, 23, 37, 137, 2026, 31415], cv_folds)
    return TaskContract(
        parent_protocol_hash=stable_hash({"protocol": 1}),
        task_id="test-task",
        dataset_ref=bundle.dataset_ref,
        dataset_hash=bundle.dataset_hash,
        scenario_card_hash=stable_hash({"scenario": 1}),
        target_column="target",
        primary_metric="f1_macro",
        prediction_time="test time",
        approved_feature_columns=tuple(bundle.features.columns),
        split_seed=42,
        split_manifest_hash=manifest_hash,
        cv_folds=cv_folds,
        search_training_seed=42,
        allowed_model_families=("logistic_regression", "random_forest", "hist_gradient_boosting"),
        decision_policy=DecisionPolicy(
            metric="f1_macro",
            min_effect_floor=0.002,
            noise_floor=0.003,
            min_effect=0.003,
            calibration_split_seeds=(11, 23, 37),
            confirmation_split_seeds=(137, 2026, 31415),
        ),
        budgets=BudgetLimits(
            max_experiments=20,
            max_fits=max_fits,
            max_total_seconds=300,
            experiment_timeout_seconds=timeout,
        ),
        memory_snapshot_hash=stable_hash([]),
    )


@pytest.fixture
def make_contract():
    return _make_contract
