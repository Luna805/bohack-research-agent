"""Zero-token random search over the same legal space the proposer can use.

The same sampler is the ``random_search`` comparison system and the controller's
``tool_search`` action, so both always share one implementation.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any

from .schemas import (
    AddMissingIndicators,
    DropColumns,
    ExperimentSpec,
    FeatureAction,
    ForestRegressorSpec,
    ForestSpec,
    HistBoostRegressorSpec,
    HistBoostSpec,
    Log1pColumns,
    LogisticSpec,
    PreprocessingSpec,
    RidgeSpec,
    SentinelToMissing,
    TaskContract,
    TextTfidfSpec,
)


def baseline_spec(task_type: str = "binary") -> ExperimentSpec:
    if task_type == "regression":
        return ExperimentSpec(
            model=RidgeSpec(family="ridge", alpha=1.0),
            preprocessing=PreprocessingSpec(numeric_scaler="standard"),
        )
    return ExperimentSpec(
        model=LogisticSpec(family="logistic_regression", c=1.0, max_iter=500),
        preprocessing=PreprocessingSpec(numeric_scaler="standard"),
    )


class SpecSampler:
    def __init__(self, seed: int, contract: TaskContract, profile: dict[str, Any]) -> None:
        self.rng = random.Random(seed)
        self.contract = contract
        approved = set(contract.approved_feature_columns)
        columns = [entry for entry in profile["columns"] if entry["name"] in approved]
        self.droppable = [entry["name"] for entry in columns if entry["kind"] != "text"]
        self.skewed = [
            entry["name"]
            for entry in columns
            if entry["kind"] == "numeric" and entry["min"] > -1 and abs(entry["skew"]) > 1
        ]
        self.sentinels = {
            entry["name"]: entry["possible_sentinel"]
            for entry in columns
            if entry["kind"] == "numeric" and "possible_sentinel" in entry
        }
        self.text_columns = tuple(contract.text_columns)

    def _model(self) -> Any:
        family = self.rng.choice(list(self.contract.allowed_model_families))
        weight = self.rng.choice([None, "balanced"])
        if family == "logistic_regression":
            return LogisticSpec(
                family=family,
                c=self.rng.choice([0.05, 0.2, 0.5, 1.0, 2.0, 10.0]),
                class_weight=weight,
                max_iter=500,
            )
        if family == "random_forest":
            return ForestSpec(
                family=family,
                n_estimators=self.rng.choice([60, 100, 200]),
                max_depth=self.rng.choice([None, 6, 10, 16]),
                min_samples_leaf=self.rng.choice([1, 3, 5, 10, 20]),
                class_weight=weight,
            )
        if family == "hist_gradient_boosting":
            return HistBoostSpec(
                family=family,
                learning_rate=self.rng.choice([0.03, 0.06, 0.1, 0.2]),
                max_iter=self.rng.choice([60, 100, 200]),
                max_leaf_nodes=self.rng.choice([15, 31, 63]),
                min_samples_leaf=self.rng.choice([10, 20, 50]),
                class_weight=weight,
            )
        if family == "ridge":
            return RidgeSpec(family=family, alpha=self.rng.choice([0.1, 1.0, 10.0, 100.0]))
        if family == "random_forest_regressor":
            return ForestRegressorSpec(
                family=family,
                n_estimators=self.rng.choice([60, 100, 200]),
                max_depth=self.rng.choice([None, 6, 10, 16]),
                min_samples_leaf=self.rng.choice([1, 3, 5, 10, 20]),
            )
        return HistBoostRegressorSpec(
            family=family,
            learning_rate=self.rng.choice([0.03, 0.06, 0.1, 0.2]),
            max_iter=self.rng.choice([60, 100, 200]),
            max_leaf_nodes=self.rng.choice([15, 31, 63]),
            min_samples_leaf=self.rng.choice([10, 20, 50]),
        )

    def _actions(self) -> tuple[FeatureAction, ...]:
        if self.rng.random() >= 0.5:
            return ()
        options: list[str] = []
        # Dropping the only approved column would leave no features (the contract rejects it).
        if self.droppable and len(self.contract.approved_feature_columns) > 1:
            options.append("drop")
        if self.skewed:
            options.append("log1p")
        if self.sentinels:
            options.append("sentinel")
        if not options:
            return ()
        choice = self.rng.choice(options)
        if choice == "drop":
            return (DropColumns(kind="drop_columns", columns=(self.rng.choice(self.droppable),)),)
        if choice == "log1p":
            return (Log1pColumns(kind="log1p", columns=(self.rng.choice(self.skewed),)),)
        column = self.rng.choice(sorted(self.sentinels))
        return (
            SentinelToMissing(
                kind="sentinel_to_missing", columns=(column,), value=self.sentinels[column]
            ),
            AddMissingIndicators(kind="missing_indicator", columns=(column,)),
        )

    def sample(self) -> ExperimentSpec:
        model = self._model()
        scaler = "standard" if model.family in ("logistic_regression", "ridge") else "none"
        text = None
        if self.text_columns and self.rng.random() < 0.5:
            text = TextTfidfSpec(
                columns=self.text_columns[:3],
                max_features=self.rng.choice([500, 2000]),
                ngram_max=self.rng.choice([1, 2]),
                svd_components=50 if model.family == "hist_gradient_boosting" else None,
            )
        return ExperimentSpec(
            model=model,
            preprocessing=PreprocessingSpec(numeric_scaler=scaler, text=text),
            feature_actions=self._actions(),
        )

    def sample_new(
        self, is_seen: Callable[[ExperimentSpec], bool], max_tries: int = 200
    ) -> ExperimentSpec | None:
        for _ in range(max_tries):
            spec = self.sample()
            if not is_seen(spec):
                return spec
        return None
