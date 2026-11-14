"""SpecSampler must only produce specs the contract accepts (tool search and random_search)."""

from __future__ import annotations

from types import SimpleNamespace

from budgetlab.contracts import validate_experiment_spec
from budgetlab.search import SpecSampler

FAMILIES = ("logistic_regression", "random_forest", "hist_gradient_boosting")


def _sampler(columns: list[dict]) -> tuple[SimpleNamespace, SpecSampler]:
    contract = SimpleNamespace(
        approved_feature_columns=tuple(column["name"] for column in columns),
        allowed_model_families=FAMILIES,
        text_columns=(),
    )
    return contract, SpecSampler(7, contract, {"columns": columns})


def _numeric(name: str) -> dict:
    return {"name": name, "kind": "numeric", "min": 0.0, "skew": 0.2}


def test_single_approved_column_is_never_dropped() -> None:
    # Regression: an uploaded CSV with one usable column crashed tool search and random_search.
    contract, sampler = _sampler([_numeric("score")])
    for _ in range(300):
        spec = sampler.sample()
        validate_experiment_spec(spec, contract)
        assert all(action.kind != "drop_columns" for action in spec.feature_actions)


def test_drop_is_still_sampled_when_other_columns_remain() -> None:
    contract, sampler = _sampler([_numeric("score"), _numeric("age")])
    kinds = set()
    for _ in range(300):
        spec = sampler.sample()
        validate_experiment_spec(spec, contract)
        kinds.update(action.kind for action in spec.feature_actions)
    assert "drop_columns" in kinds
