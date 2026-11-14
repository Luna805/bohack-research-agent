from __future__ import annotations

import pytest

from budgetlab.budget import Budget, BudgetExceeded
from budgetlab.ledger import EventLedger
from budgetlab.schemas import BudgetLimits, ResourceVector


def make_budget(tmp_path, *, max_fits: int = 5) -> Budget:
    ledger = EventLedger("test-run", tmp_path)
    return Budget(
        BudgetLimits(
            max_experiments=3,
            max_fits=max_fits,
            max_total_seconds=30,
            experiment_timeout_seconds=10,
        ),
        tmp_path / "budget.json",
        ledger,
    )


def test_budget_blocks_before_execution(tmp_path) -> None:
    budget = make_budget(tmp_path, max_fits=2)
    with pytest.raises(BudgetExceeded):
        budget.reserve("too-large", ResourceVector(experiments=1, fits=3, seconds=1))
    assert budget.summary()["reservations"] == {}


def test_unknown_usage_is_not_zero_and_duplicate_settlement_is_rejected(tmp_path) -> None:
    budget = make_budget(tmp_path)
    budget.reserve("train-1", ResourceVector(experiments=1, fits=3, seconds=10))
    budget.settle(
        "train-1",
        ResourceVector(experiments=1, fits=1, seconds=2),
        unknown=ResourceVector(fits=2),
    )
    summary = budget.summary()
    assert summary["used"]["fits"] == 1
    assert summary["unknown"]["fits"] == 2
    with pytest.raises(ValueError, match="already finalized"):
        budget.settle("train-1", ResourceVector())


def test_event_ledger_is_contiguous_and_reloads(tmp_path) -> None:
    ledger = EventLedger("test-run", tmp_path)
    ledger.append("run_created")
    ledger.append("budget_reserved", action_id="a")
    reloaded = EventLedger("test-run", tmp_path).read_events()
    assert [event["seq"] for event in reloaded] == [1, 2]
