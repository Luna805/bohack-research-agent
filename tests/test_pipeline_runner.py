from __future__ import annotations

import json

import pandas as pd

from budgetlab.budget import Budget
from budgetlab.data import load_dataset, split_manifest
from budgetlab.ledger import EventLedger
from budgetlab.pipeline import build_pipeline, score_predictions
from budgetlab.runner import Runner
from budgetlab.schemas import (
    ExperimentSpec,
    LogisticSpec,
    PreprocessingSpec,
    ResourceVector,
    TextTfidfSpec,
)
from budgetlab.search import baseline_spec


def test_split_manifest_is_deterministic() -> None:
    bundle = load_dataset()
    first, first_hash = split_manifest(bundle, [42], 3)
    second, second_hash = split_manifest(bundle, [42], 3)
    assert first == second
    assert first_hash == second_hash
    assert set(first["splits"][0]["folds"][0]) == {"fold", "train_row_ids", "valid_row_ids"}


def test_real_pipeline_fit_and_text_branch() -> None:
    bundle = load_dataset()
    pipeline = build_pipeline(baseline_spec(), bundle.features, 42)
    pipeline.fit(bundle.features.iloc[:400], bundle.target.iloc[:400])
    score = score_predictions(
        "f1_macro", bundle.target.iloc[400:], pipeline, bundle.features.iloc[400:]
    )
    assert 0 <= score <= 1

    features = pd.DataFrame(
        {"value": [0.0, 1.0, 0.1, 0.9], "text": ["cold blue", "hot red", "blue", "red hot"]}
    )
    target = pd.Series([0, 1, 0, 1])
    spec = ExperimentSpec(
        model=LogisticSpec(family="logistic_regression"),
        preprocessing=PreprocessingSpec(
            numeric_scaler="standard",
            text=TextTfidfSpec(columns=("text",), max_features=200),
        ),
    )
    text_pipeline = build_pipeline(spec, features, 42)
    text_pipeline.fit(features, target)
    assert len(text_pipeline.predict(features)) == 4


def test_runner_timeout_preserves_unknown_fit_usage(tmp_path, make_contract) -> None:
    contract = make_contract(timeout=1, cv_folds=2, max_fits=10)
    ledger = EventLedger("timeout-run", tmp_path)
    budget = Budget(
        contract.budgets, tmp_path / "budget.json", ledger, tail_reserve=ResourceVector()
    )
    result = Runner(tmp_path, ledger, budget).execute(
        baseline_spec(),
        contract,
        purpose="timeout-test",
        split_seed=42,
        experiment_id="timeout",
        simulate_sleep_seconds=2,
    )
    assert result.status == "timeout"
    summary = json.loads((tmp_path / "budget.json").read_text(encoding="utf-8"))
    assert summary["unknown"]["fits"] == 2
    assert summary["used"]["experiments"] == 1
