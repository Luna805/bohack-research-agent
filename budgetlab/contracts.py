from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from .schemas import (
    CalibrationReport,
    DecisionPolicy,
    ExperimentSpec,
    ProposalBatch,
    ProtocolSpec,
    TaskContract,
)


def canonical_json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def freeze_contract(
    protocol: ProtocolSpec,
    calibration: CalibrationReport,
    *,
    split_manifest_hash: str,
    memory_snapshot_hash: str,
) -> TaskContract:
    protocol_hash = stable_hash(protocol)
    if calibration.protocol_hash != protocol_hash:
        raise ValueError("calibration does not belong to this protocol")
    expected = max(protocol.min_effect_floor, calibration.noise_floor)
    if abs(calibration.min_effect - expected) > 1e-12:
        raise ValueError("calibration min_effect does not match the frozen rule")
    return TaskContract(
        parent_protocol_hash=protocol_hash,
        task_id=protocol.task_id,
        dataset_ref=protocol.dataset_ref,
        dataset_hash=protocol.dataset_hash,
        scenario_card_hash=protocol.scenario_card_hash,
        target_column=protocol.target_column,
        primary_metric=protocol.primary_metric,
        prediction_time=protocol.prediction_time,
        approved_feature_columns=protocol.approved_feature_columns,
        text_columns=protocol.text_columns,
        split_seed=protocol.split_seed,
        split_manifest_hash=split_manifest_hash,
        cv_folds=protocol.cv_folds,
        search_training_seed=protocol.search_training_seed,
        allowed_model_families=protocol.allowed_model_families,
        decision_policy=DecisionPolicy(
            metric=protocol.primary_metric,
            min_effect_floor=protocol.min_effect_floor,
            noise_floor=calibration.noise_floor,
            min_effect=calibration.min_effect,
            calibration_split_seeds=protocol.calibration_split_seeds,
            confirmation_split_seeds=protocol.confirmation_split_seeds,
        ),
        budgets=protocol.budgets,
        loop_policy=protocol.loop_policy,
        sealed_holdout_sha256=protocol.sealed_holdout_sha256,
        memory_snapshot_hash=memory_snapshot_hash,
    )


def canonical_spec(spec: ExperimentSpec) -> dict[str, Any]:
    """Spec dump with column lists sorted, so reordered columns count as the same experiment."""
    value = spec.model_dump(mode="json")
    for action in value["feature_actions"]:
        action["columns"] = sorted(action["columns"])
    if value["preprocessing"].get("text"):
        value["preprocessing"]["text"]["columns"] = sorted(
            value["preprocessing"]["text"]["columns"]
        )
    return value


def spec_hash(spec: ExperimentSpec) -> str:
    return stable_hash(canonical_spec(spec))


def validate_experiment_spec(
    spec: ExperimentSpec,
    contract: TaskContract | ProtocolSpec,
    *,
    numeric_minima: dict[str, float] | None = None,
) -> None:
    approved = set(contract.approved_feature_columns)
    if spec.model.family not in contract.allowed_model_families:
        raise ValueError("model family is not allowed by the contract")
    present = set(approved)
    for index, action in enumerate(spec.feature_actions):
        unknown = set(action.columns) - present
        if unknown:
            raise ValueError(
                f"feature action {index} ({action.kind}) references columns that are not approved"
                f" or were already dropped: {sorted(unknown)}"
            )
        numeric_only = action.kind in {"log1p", "sentinel_to_missing"}
        if numeric_only and numeric_minima is not None:
            non_numeric = [column for column in action.columns if column not in numeric_minima]
            if non_numeric:
                raise ValueError(f"{action.kind} requires numeric columns: {non_numeric}")
        if action.kind == "log1p" and numeric_minima is not None:
            invalid = [column for column in action.columns if numeric_minima.get(column, -2) <= -1]
            if invalid:
                raise ValueError(f"log1p domain violation (values <= -1): {invalid}")
        if action.kind == "drop_columns":
            present -= set(action.columns)
            if not present:
                raise ValueError("feature actions drop every approved column")
    text = spec.preprocessing.text
    if text is not None:
        if not set(text.columns).issubset(set(contract.text_columns)):
            raise ValueError("text specification references a non-whitelisted text column")
        if spec.model.family == "hist_gradient_boosting" and text.svd_components is None:
            raise ValueError("hist_gradient_boosting with text requires explicit SVD")


def validate_proposal_batch(
    batch: ProposalBatch,
    *,
    allowed_evidence_refs: Iterable[str],
    known_experiment_ids: Iterable[str],
) -> None:
    evidence = set(allowed_evidence_refs)
    experiments = set(known_experiment_ids)
    ids = [candidate.candidate_id for candidate in batch.candidates]
    if len(set(ids)) != 2:
        raise ValueError("candidate IDs must be distinct")
    hashes = [stable_hash(candidate.experiment) for candidate in batch.candidates]
    if len(set(hashes)) != 2:
        raise ValueError("candidate experiment specifications must be distinct")
    for candidate in batch.candidates:
        hypothesis = candidate.hypothesis
        if not set(hypothesis.evidence_refs).issubset(evidence):
            raise ValueError("candidate cites unavailable evidence")
        if hypothesis.comparator_experiment_id not in experiments:
            raise ValueError("candidate comparator does not exist")
