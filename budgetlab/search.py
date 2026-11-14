from __future__ import annotations

import random

from .schemas import ExperimentSpec, ForestSpec, HistBoostSpec, LogisticSpec, PreprocessingSpec


def baseline_spec() -> ExperimentSpec:
    return ExperimentSpec(
        model=LogisticSpec(family="logistic_regression", c=1.0, max_iter=500),
        preprocessing=PreprocessingSpec(numeric_scaler="standard"),
    )


def sample_specs(seed: int, count: int) -> list[ExperimentSpec]:
    rng = random.Random(seed)
    candidates: list[ExperimentSpec] = []
    seen: set[str] = set()
    while len(candidates) < count:
        family = rng.choice(["logistic_regression", "random_forest", "hist_gradient_boosting"])
        if family == "logistic_regression":
            model = LogisticSpec(
                family=family,
                c=rng.choice([0.05, 0.2, 0.5, 2.0, 10.0]),
                class_weight=rng.choice([None, "balanced"]),
                max_iter=500,
            )
            preprocessing = PreprocessingSpec(numeric_scaler="standard")
        elif family == "random_forest":
            model = ForestSpec(
                family=family,
                n_estimators=rng.choice([60, 100, 160]),
                max_depth=rng.choice([None, 4, 8, 12]),
                min_samples_leaf=rng.choice([1, 2, 4]),
                class_weight=rng.choice([None, "balanced"]),
            )
            preprocessing = PreprocessingSpec()
        else:
            model = HistBoostSpec(
                family=family,
                learning_rate=rng.choice([0.03, 0.06, 0.1]),
                max_iter=rng.choice([60, 100, 140]),
                max_leaf_nodes=rng.choice([15, 31]),
                min_samples_leaf=rng.choice([10, 20, 30]),
            )
            preprocessing = PreprocessingSpec()
        spec = ExperimentSpec(model=model, preprocessing=preprocessing)
        key = spec.model_dump_json()
        if key not in seen and spec != baseline_spec():
            seen.add(key)
            candidates.append(spec)
    return candidates
