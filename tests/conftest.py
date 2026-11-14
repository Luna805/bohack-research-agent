from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from budgetlab.contracts import spec_hash, stable_hash
from budgetlab.data import load_development, prepare_task, split_manifest
from budgetlab.proposers import CallOutcome
from budgetlab.schemas import (
    AddMissingIndicators,
    BudgetLimits,
    Candidate,
    DecisionPolicy,
    ExperimentSpec,
    ForestSpec,
    HistBoostSpec,
    Hypothesis,
    LogisticSpec,
    PreprocessingSpec,
    ProposalBatch,
    ResourceVector,
    SentinelToMissing,
    TaskContract,
)


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


class RuleProposer:
    """Test double for the LLM proposer: deterministic, zero-token rules (weight classes,
    switch family, fix sentinels, tune). Product code has no rule-based proposer."""

    source = "fixture"

    def estimate(self, context: dict[str, Any]) -> ResourceVector:
        return ResourceVector()

    def _moves(self, best: ExperimentSpec, context: dict[str, Any]) -> list[tuple[str, Any]]:
        moves: list[tuple[str, ExperimentSpec]] = []
        model = best.model
        if getattr(model, "class_weight", None) is None:
            moves.append(
                (
                    "Balanced class weights should raise minority-class F1 on an imbalanced task.",
                    best.model_copy(
                        update={"model": model.model_copy(update={"class_weight": "balanced"})}
                    ),
                )
            )
        families = context["legal_space"]["model_families"]
        for family in families:
            if family == model.family:
                continue
            new_model: Any
            if family == "logistic_regression":
                new_model = LogisticSpec(family=family, class_weight="balanced", max_iter=500)
                prep = PreprocessingSpec(numeric_scaler="standard")
            elif family == "random_forest":
                new_model = ForestSpec(family=family, class_weight="balanced", min_samples_leaf=5)
                prep = PreprocessingSpec()
            else:
                new_model = HistBoostSpec(family=family, class_weight="balanced")
                prep = PreprocessingSpec()
            moves.append(
                (
                    f"A {family} model may capture structure the current best misses.",
                    ExperimentSpec(
                        model=new_model, preprocessing=prep, feature_actions=best.feature_actions
                    ),
                )
            )
        for column in context["data_profile"]:
            if "possible_sentinel" in column and not best.feature_actions:
                actions = (
                    SentinelToMissing(
                        kind="sentinel_to_missing",
                        columns=(column["name"],),
                        value=column["possible_sentinel"],
                    ),
                    AddMissingIndicators(kind="missing_indicator", columns=(column["name"],)),
                )
                moves.append(
                    (
                        f"{column['name']} uses {column['possible_sentinel']} as a placeholder; "
                        "an explicit flag may help.",
                        best.model_copy(update={"feature_actions": actions}),
                    )
                )
        tweaks: dict[str, list[dict[str, Any]]] = {
            "random_forest": [
                {"min_samples_leaf": 10},
                {"min_samples_leaf": 2},
                {"n_estimators": 200},
            ],
            "hist_gradient_boosting": [
                {"learning_rate": 0.05, "max_iter": 200},
                {"min_samples_leaf": 50},
            ],
            "logistic_regression": [{"c": 0.2}, {"c": 5.0}],
        }
        for update in tweaks[model.family]:
            moves.append(
                (
                    f"Tuning {', '.join(update)} may trade bias and variance better.",
                    best.model_copy(update={"model": model.model_copy(update=update)}),
                )
            )
        return moves

    def propose(self, context: dict[str, Any]) -> CallOutcome:
        rows = {row["id"]: row for row in context["experiments"]}
        best_id = context["best_id"]
        best = ExperimentSpec.model_validate(rows[best_id]["spec"])
        seen = {spec_hash(ExperimentSpec.model_validate(row["spec"])) for row in rows.values()}
        chosen: list[tuple[str, ExperimentSpec]] = []
        for statement, spec in self._moves(best, context):
            digest = spec_hash(spec)
            if digest in seen:
                continue
            seen.add(digest)
            chosen.append((statement, spec))
            if len(chosen) == 2:
                break
        if len(chosen) < 2:
            return CallOutcome(output=None, error="rule proposer has no untried moves left")
        candidates = tuple(
            Candidate(
                candidate_id=f"s{index + 1}",
                hypothesis=Hypothesis(
                    statement=statement,
                    evidence_refs=(best_id, "eda"),
                    comparator_experiment_id=best_id,
                    decision_policy_id="practical_gain_v2",
                    proposed_change=json.dumps(spec.model.model_dump(mode="json"))[:200],
                ),
                experiment=spec,
            )
            for index, (statement, spec) in enumerate(chosen)
        )
        batch = ProposalBatch(
            previous_result_interpretation=f"Current best is {best_id}.",
            intent="replan" if context["mode"] == "replan" else "refine",
            direction=f"improve on {best_id}",
            candidates=candidates,
        )
        return CallOutcome(output=batch, details={"source": "fixture"})


@pytest.fixture
def rule_proposer() -> RuleProposer:
    return RuleProposer()
