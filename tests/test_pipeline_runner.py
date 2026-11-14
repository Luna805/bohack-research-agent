from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from budgetlab.budget import Budget
from budgetlab.data import load_development, split_manifest
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


def test_split_manifest_is_deterministic(data_root) -> None:
    bundle = load_development("breast_cancer", data_root)
    first, first_hash = split_manifest(bundle, [42], 3)
    second, second_hash = split_manifest(bundle, [42], 3)
    assert first == second
    assert first_hash == second_hash
    assert set(first["splits"][0]["folds"][0]) == {"fold", "train_rows", "valid_row_ids"}


def test_real_pipeline_fit_and_text_branch(data_root) -> None:
    bundle = load_development("breast_cancer", data_root)
    pipeline = build_pipeline(baseline_spec(), bundle.features, 42)
    pipeline.fit(bundle.features.iloc[:300], bundle.target.iloc[:300])
    score = score_predictions(
        "f1_macro", bundle.target.iloc[300:], pipeline, bundle.features.iloc[300:]
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


def test_runner_timeout_preserves_unknown_fit_usage(tmp_path, make_contract, data_root) -> None:
    contract = make_contract(timeout=1, cv_folds=2, max_fits=10)
    ledger = EventLedger("timeout-run", tmp_path)
    budget = Budget(
        contract.budgets, tmp_path / "budget.json", ledger, tail_reserve=ResourceVector()
    )
    result = Runner(tmp_path, ledger, budget, data_root).execute(
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


def test_runner_oserror_settles_reservation_and_writes_error_logs(
    tmp_path, make_contract, data_root, monkeypatch
) -> None:
    contract = make_contract(cv_folds=2, max_fits=10)
    ledger = EventLedger("oserror-run", tmp_path)
    budget = Budget(
        contract.budgets, tmp_path / "budget.json", ledger, tail_reserve=ResourceVector()
    )

    def raise_oserror(*args, **kwargs):
        raise OSError("worker executable unavailable")

    monkeypatch.setattr("budgetlab.runner.subprocess.run", raise_oserror)
    result = Runner(tmp_path, ledger, budget, data_root).execute(
        baseline_spec(), contract, purpose="exploration", split_seed=42, experiment_id="oserror"
    )

    summary = budget.summary()
    assert result.status == "failed"
    assert "failed to start worker" in (result.error or "")
    assert summary["unknown"]["fits"] == 2
    assert summary["reservations"]["train:oserror"]["status"] == "unknown"
    assert not any(item["status"] == "reserved" for item in summary["reservations"].values())
    assert (tmp_path / "logs" / "oserror.stderr.log").read_text(encoding="utf-8")


def test_runner_missing_or_corrupt_result_settles_unknown_fits(
    tmp_path, make_contract, data_root, monkeypatch
) -> None:
    contract = make_contract(cv_folds=2, max_fits=20)

    def run_missing(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], returncode=3, stdout="out", stderr="err")

    monkeypatch.setattr("budgetlab.runner.subprocess.run", run_missing)
    missing_ledger = EventLedger("missing-result", tmp_path / "missing")
    missing_budget = Budget(
        contract.budgets,
        tmp_path / "missing" / "budget.json",
        missing_ledger,
        tail_reserve=ResourceVector(),
    )
    missing = Runner(tmp_path / "missing", missing_ledger, missing_budget, data_root).execute(
        baseline_spec(), contract, purpose="exploration", split_seed=42, experiment_id="missing"
    )
    assert missing.status == "failed"
    assert "without a result" in (missing.error or "")
    assert missing_budget.summary()["reservations"]["train:missing"]["status"] == "unknown"

    def run_corrupt(args, **kwargs):
        result_path = args[args.index("--result") + 1]
        Path(result_path).write_text("{not-json", encoding="utf-8")
        return subprocess.CompletedProcess(args, returncode=0, stdout="out", stderr="err")

    monkeypatch.setattr("budgetlab.runner.subprocess.run", run_corrupt)
    corrupt_ledger = EventLedger("corrupt-result", tmp_path / "corrupt")
    corrupt_budget = Budget(
        contract.budgets,
        tmp_path / "corrupt" / "budget.json",
        corrupt_ledger,
        tail_reserve=ResourceVector(),
    )
    corrupt = Runner(tmp_path / "corrupt", corrupt_ledger, corrupt_budget, data_root).execute(
        baseline_spec(), contract, purpose="exploration", split_seed=42, experiment_id="corrupt"
    )
    assert corrupt.status == "failed"
    assert "invalid worker result" in (corrupt.error or "")
    assert corrupt_budget.summary()["reservations"]["train:corrupt"]["status"] == "unknown"


def test_runner_missing_fit_counters_is_not_accounted_as_zero(
    tmp_path, make_contract, data_root, monkeypatch
) -> None:
    contract = make_contract(cv_folds=2, max_fits=10)

    def run_without_counters(args, **kwargs):
        result_path = args[args.index("--result") + 1]
        Path(result_path).write_text(
            json.dumps({"status": "failed", "error": "worker stopped early"}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args, returncode=2, stdout="", stderr="")

    monkeypatch.setattr("budgetlab.runner.subprocess.run", run_without_counters)
    ledger = EventLedger("missing-counters", tmp_path)
    budget = Budget(
        contract.budgets, tmp_path / "budget.json", ledger, tail_reserve=ResourceVector()
    )

    result = Runner(tmp_path, ledger, budget, data_root).execute(
        baseline_spec(), contract, purpose="exploration", split_seed=42, experiment_id="broken"
    )

    assert result.status == "failed"
    assert "invalid worker result" in (result.error or "")
    summary = budget.summary()
    assert summary["used"]["fits"] == 0
    assert summary["unknown"]["fits"] == 2
    assert summary["reservations"]["train:broken"]["status"] == "unknown"


def test_runner_unexpected_exception_closes_reservation_and_propagates(
    tmp_path, make_contract, data_root, monkeypatch
) -> None:
    contract = make_contract(cv_folds=2, max_fits=10)
    ledger = EventLedger("unexpected-runner-error", tmp_path)
    budget = Budget(
        contract.budgets, tmp_path / "budget.json", ledger, tail_reserve=ResourceVector()
    )

    def raise_programming_error(*args, **kwargs):
        raise RuntimeError("unexpected fixture bug")

    monkeypatch.setattr("budgetlab.runner.subprocess.run", raise_programming_error)
    with pytest.raises(RuntimeError, match="unexpected fixture bug"):
        Runner(tmp_path, ledger, budget, data_root).execute(
            baseline_spec(),
            contract,
            purpose="exploration",
            split_seed=42,
            experiment_id="unexpected",
        )

    summary = budget.summary()
    assert summary["reservations"]["train:unexpected"]["status"] == "unknown"
    assert not any(item["status"] == "reserved" for item in summary["reservations"].values())
