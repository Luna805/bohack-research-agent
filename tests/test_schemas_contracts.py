from __future__ import annotations

import pytest
from pydantic import ValidationError

from budgetlab.contracts import validate_experiment_spec, validate_proposal_batch
from budgetlab.schemas import (
    Candidate,
    ExperimentSpec,
    HistBoostSpec,
    Hypothesis,
    Log1pColumns,
    LogisticSpec,
    PreprocessingSpec,
    ProposalBatch,
    TextTfidfSpec,
)


def candidate(candidate_id: str, c_value: float = 1.0) -> Candidate:
    return Candidate(
        candidate_id=candidate_id,
        hypothesis=Hypothesis(
            statement="test",
            evidence_refs=("baseline.json",),
            comparator_experiment_id="baseline",
            decision_policy_id="policy",
            proposed_change="change C",
        ),
        experiment=ExperimentSpec(model=LogisticSpec(family="logistic_regression", c=c_value)),
    )


def test_strict_schema_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        LogisticSpec(family="logistic_regression", c=1.0, surprise=True)


def test_proposal_requires_two_distinct_specs() -> None:
    batch = ProposalBatch(
        previous_result_interpretation="none",
        intent="explore",
        direction="test",
        candidates=(candidate("one"), candidate("two")),
    )
    with pytest.raises(ValueError, match="specifications must be distinct"):
        validate_proposal_batch(
            batch, allowed_evidence_refs=["baseline.json"], known_experiment_ids=["baseline"]
        )


def test_log1p_domain_and_hgb_text_are_rejected(make_contract) -> None:
    contract = make_contract()
    log_spec = ExperimentSpec(
        model=LogisticSpec(family="logistic_regression"),
        feature_actions=(Log1pColumns(kind="log1p", columns=("mean radius",)),),
    )
    with pytest.raises(ValueError, match="domain"):
        validate_experiment_spec(log_spec, contract, numeric_minima={"mean radius": -1.0})
    text_contract = contract.model_copy(update={"text_columns": ("mean radius",)})
    hgb_text = ExperimentSpec(
        model=HistBoostSpec(family="hist_gradient_boosting"),
        preprocessing=PreprocessingSpec(
            text=TextTfidfSpec(columns=("mean radius",), max_features=200)
        ),
    )
    with pytest.raises(ValueError, match="requires explicit SVD"):
        validate_experiment_spec(hgb_text, text_contract)


def test_sentinel_and_drop_order_are_validated(make_contract) -> None:
    from budgetlab.contracts import spec_hash
    from budgetlab.schemas import AddMissingIndicators, DropColumns, SentinelToMissing

    contract = make_contract()
    minima = {"mean radius": 6.9, "mean texture": 9.7}
    dropped_then_used = ExperimentSpec(
        model=LogisticSpec(family="logistic_regression"),
        feature_actions=(
            DropColumns(kind="drop_columns", columns=("mean radius",)),
            Log1pColumns(kind="log1p", columns=("mean radius",)),
        ),
    )
    with pytest.raises(ValueError, match="already dropped"):
        validate_experiment_spec(dropped_then_used, contract, numeric_minima=minima)
    first = ExperimentSpec(
        model=LogisticSpec(family="logistic_regression"),
        feature_actions=(
            SentinelToMissing(
                kind="sentinel_to_missing", columns=("mean radius", "mean texture"), value=0
            ),
            AddMissingIndicators(kind="missing_indicator", columns=("mean radius",)),
        ),
    )
    validate_experiment_spec(first, contract, numeric_minima=minima)
    reordered = first.model_copy(
        update={
            "feature_actions": (
                SentinelToMissing(
                    kind="sentinel_to_missing", columns=("mean texture", "mean radius"), value=0
                ),
                first.feature_actions[1],
            )
        }
    )
    assert spec_hash(first) == spec_hash(reordered)
