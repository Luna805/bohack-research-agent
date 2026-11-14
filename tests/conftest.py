from __future__ import annotations

from pathlib import Path

import pytest

from budgetlab.contracts import stable_hash
from budgetlab.data import load_development, prepare_task, split_manifest
from budgetlab.schemas import BudgetLimits, DecisionPolicy, TaskContract


@pytest.fixture(scope="session")
def data_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("data")
    prepare_task("breast_cancer", root)
    return root


@pytest.fixture
def make_contract(data_root):
    def _make_contract(*, timeout: int = 10, cv_folds: int = 3, max_fits: int = 60) -> TaskContract:
        bundle = load_development("breast_cancer", data_root)
        _, manifest_hash = split_manifest(bundle, [42, 11, 23, 37, 137, 2026, 31415], cv_folds)
        return TaskContract(
            parent_protocol_hash=stable_hash({"protocol": 1}),
            task_id="breast_cancer",
            dataset_ref="breast_cancer",
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
            allowed_model_families=(
                "logistic_regression",
                "random_forest",
                "hist_gradient_boosting",
            ),
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
            sealed_holdout_sha256="test",
            memory_snapshot_hash=stable_hash([]),
        )

    return _make_contract


SMOKE_CONFIG = {
    "task_id": "breast_cancer",
    "cv_folds": 2,
    "split_seed": 42,
    "calibration_split_seeds": [11, 23, 37],
    "confirmation_split_seeds": [137, 2026, 31415],
    "training_seed": 42,
    "search_seed": 2026,
    "min_effect_floor": 0.002,
    "budget": {
        "max_experiments": 30,
        "max_fits": 80,
        "max_tool_search_fits": 10,
        "max_total_seconds": 900,
        "experiment_timeout_seconds": 60,
    },
    "loop": {"max_rounds": 2, "initial_tool_search": 1, "stagnation_stop": 3},
}


@pytest.fixture
def smoke_config() -> dict:
    import copy

    return copy.deepcopy(SMOKE_CONFIG)
