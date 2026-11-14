from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


Metric = Literal["f1_macro", "accuracy", "roc_auc"]
ModelFamily = Literal["logistic_regression", "random_forest", "hist_gradient_boosting"]


class TextTfidfSpec(StrictModel):
    columns: tuple[str, ...] = Field(min_length=1, max_length=3)
    max_features: int = Field(default=2000, ge=200, le=5000)
    ngram_max: Literal[1, 2] = 1
    svd_components: int | None = Field(default=None, ge=2, le=200)


class PreprocessingSpec(StrictModel):
    numeric_imputer: Literal["median", "mean"] = "median"
    numeric_scaler: Literal["none", "standard"] = "none"
    categorical_imputer: Literal["most_frequent", "constant"] = "most_frequent"
    categorical_encoder: Literal["onehot"] = "onehot"
    text: TextTfidfSpec | None = None


class DropColumns(StrictModel):
    kind: Literal["drop_columns"]
    columns: tuple[str, ...] = Field(min_length=1)


class Log1pColumns(StrictModel):
    kind: Literal["log1p"]
    columns: tuple[str, ...] = Field(min_length=1)


class AddMissingIndicators(StrictModel):
    kind: Literal["missing_indicator"]
    columns: tuple[str, ...] = Field(min_length=1)


class SentinelToMissing(StrictModel):
    """Replace a documented placeholder value (for example 999) with a missing value."""

    kind: Literal["sentinel_to_missing"]
    columns: tuple[str, ...] = Field(min_length=1, max_length=4)
    value: float


FeatureAction = Annotated[
    DropColumns | Log1pColumns | AddMissingIndicators | SentinelToMissing,
    Field(discriminator="kind"),
]


class LogisticSpec(StrictModel):
    family: Literal["logistic_regression"]
    c: float = Field(default=1.0, gt=0, le=100)
    class_weight: Literal["balanced"] | None = None
    max_iter: int = Field(default=300, ge=50, le=1000)


class ForestSpec(StrictModel):
    family: Literal["random_forest"]
    n_estimators: int = Field(default=100, ge=20, le=300)
    max_depth: int | None = Field(default=None, ge=2, le=32)
    min_samples_leaf: int = Field(default=1, ge=1, le=50)
    class_weight: Literal["balanced"] | None = None


class HistBoostSpec(StrictModel):
    family: Literal["hist_gradient_boosting"]
    learning_rate: float = Field(default=0.1, gt=0, le=1)
    max_iter: int = Field(default=100, ge=20, le=300)
    max_leaf_nodes: int = Field(default=31, ge=2, le=63)
    min_samples_leaf: int = Field(default=20, ge=2, le=100)
    class_weight: Literal["balanced"] | None = None


ModelSpec = Annotated[LogisticSpec | ForestSpec | HistBoostSpec, Field(discriminator="family")]


class ExperimentSpec(StrictModel):
    model: ModelSpec
    preprocessing: PreprocessingSpec = PreprocessingSpec()
    feature_actions: tuple[FeatureAction, ...] = Field(default=(), max_length=4)


class Hypothesis(StrictModel):
    statement: str = Field(min_length=1, description="The hypothesis sentence itself.")
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    comparator_experiment_id: str = Field(min_length=1)
    decision_policy_id: str = Field(min_length=1, description="Copy decision_rule.policy_id.")
    proposed_change: str = Field(min_length=1)
    predicted_metric_delta: float | None = Field(default=None, ge=-1, le=1)


# Live models sometimes wrote ``hypothesis`` as a sentence, flattened its fields into the
# candidate and left out ``experiment``; the descriptions below spell the nesting out.
class Candidate(StrictModel):
    candidate_id: str = Field(min_length=1)
    hypothesis: Hypothesis = Field(
        description="An object, not a string: the sentence goes in hypothesis.statement, next to "
        "evidence_refs, comparator_experiment_id, decision_policy_id, proposed_change and "
        "predicted_metric_delta."
    )
    experiment: ExperimentSpec = Field(
        description="Required for every candidate: the model, preprocessing and feature_actions "
        "the program will train."
    )


class ProposalBatch(StrictModel):
    previous_result_interpretation: str
    intent: Literal["explore", "refine", "pivot", "replan"]
    direction: str = Field(min_length=1)
    candidates: tuple[Candidate, ...] = Field(min_length=2, max_length=2)


class CriticAdvice(StrictModel):
    """Advisory only: it never changes metrics, verdicts, budgets or stop rules."""

    explanation: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    next_focus: str = Field(min_length=1)
    avoid: tuple[str, ...] = Field(default=(), max_length=5)
    lesson_drafts: tuple[str, ...] = Field(default=(), max_length=3)


class EvaluationRecord(StrictModel):
    experiment_id: str
    execution_status: Literal["ok", "failed", "timeout", "invalid"]
    policy_status: Literal["candidate_pass", "confirmed_pass", "not_met", "inconclusive", "invalid"]
    mean_score: float | None = None
    mean_paired_delta: float | None = None
    fold_scores: tuple[float, ...] = ()
    confirmation_deltas: tuple[float, ...] = ()
    comparator_experiment_id: str | None = None
    invalid_reason: str | None = None
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    computed_by: Literal["evaluator"] = "evaluator"


class ResourceVector(StrictModel):
    llm_tokens: int = Field(default=0, ge=0)
    llm_requests: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)
    experiments: int = Field(default=0, ge=0)
    fits: int = Field(default=0, ge=0)
    seconds: float = Field(default=0.0, ge=0)


class BudgetLimits(StrictModel):
    max_llm_tokens: int = Field(default=0, ge=0)
    max_llm_requests: int = Field(default=0, ge=0)
    max_cost_usd: float | None = Field(default=None, ge=0)
    max_experiments: int = Field(gt=0)
    max_fits: int = Field(gt=0)
    max_tool_search_fits: int = Field(default=30, ge=0)
    max_total_seconds: int = Field(gt=0)
    experiment_timeout_seconds: int = Field(default=120, gt=0, le=600)
    max_repairs_per_spec: Literal[1] = 1
    max_empty_proposal_rounds: int = Field(default=2, ge=1)


class LoopPolicy(StrictModel):
    """Frozen research-loop rules. Every trigger reads development results only."""

    max_rounds: int = Field(default=8, ge=1, le=50)
    initial_tool_search: int = Field(default=2, ge=0, le=10)
    tool_search_batch: int = Field(default=2, ge=1, le=10)
    stagnation_tool_search: int = Field(default=2, ge=1)
    stagnation_replan: int = Field(default=2, ge=1)
    stagnation_stop: int = Field(default=4, ge=1)
    cheap_experiment_seconds: float = Field(default=30.0, gt=0)
    critic_on_stagnation: bool = True
    target_score: float | None = Field(default=None, gt=0, le=1)


class ProtocolSpec(StrictModel):
    schema_version: str = "1.0"
    policy_version: str = "practical_gain_v2"
    task_id: str
    dataset_ref: str
    dataset_hash: str
    scenario_card_hash: str
    target_column: str
    task_type: Literal["binary"] = "binary"
    primary_metric: Metric = "f1_macro"
    prediction_time: str
    approved_feature_columns: tuple[str, ...] = Field(min_length=1)
    text_columns: tuple[str, ...] = ()
    split_seed: int = 42
    calibration_split_seeds: tuple[int, ...] = Field(
        default=(11, 23, 37), min_length=3, max_length=5
    )
    confirmation_split_seeds: tuple[int, ...] = Field(
        default=(137, 2026, 31415), min_length=3, max_length=3
    )
    cv_folds: int = Field(default=5, ge=2, le=5)
    search_training_seed: int = 42
    allowed_model_families: tuple[ModelFamily, ...] = Field(min_length=1)
    min_effect_floor: float = Field(default=0.002, gt=0, le=1)
    budgets: BudgetLimits
    loop_policy: LoopPolicy = LoopPolicy()
    sealed_holdout_sha256: str
    final_grader: Literal["local_holdout"] = "local_holdout"

    @model_validator(mode="after")
    def validate_protocol(self) -> ProtocolSpec:
        features = set(self.approved_feature_columns)
        if self.target_column in features:
            raise ValueError("target_column must not be an approved feature")
        if not set(self.text_columns).issubset(features):
            raise ValueError("text_columns must be approved features")
        seeds = (
            {self.split_seed}
            | set(self.calibration_split_seeds)
            | set(self.confirmation_split_seeds)
        )
        expected = 1 + len(self.calibration_split_seeds) + len(self.confirmation_split_seeds)
        if len(seeds) != expected:
            raise ValueError("search, calibration, and confirmation seeds must be disjoint")
        return self


class CalibrationReport(StrictModel):
    protocol_hash: str
    split_scores: tuple[float, ...] = Field(min_length=3, max_length=5)
    ddof: Literal[1] = 1
    noise_floor: float = Field(ge=0, le=1)
    min_effect: float = Field(gt=0, le=1)
    evidence_refs: tuple[str, ...] = Field(min_length=3)


class DecisionPolicy(StrictModel):
    policy_id: str = "practical_gain_v2"
    metric: Metric
    direction: Literal["maximize"] = "maximize"
    final_comparator: Literal["initial_valid_baseline"] = "initial_valid_baseline"
    min_effect_floor: float = Field(gt=0, le=1)
    noise_floor: float = Field(ge=0, le=1)
    min_effect: float = Field(gt=0, le=1)
    calibration_split_seeds: tuple[int, ...] = Field(min_length=3, max_length=5)
    confirmation_split_seeds: tuple[int, ...] = Field(min_length=3, max_length=3)
    min_positive_fraction: float = Field(default=2 / 3, gt=0, le=1)


class TaskContract(StrictModel):
    schema_version: str = "1.0"
    parent_protocol_hash: str
    task_id: str
    dataset_ref: str
    dataset_hash: str
    scenario_card_hash: str
    target_column: str
    task_type: Literal["binary"] = "binary"
    primary_metric: Metric
    prediction_time: str
    approved_feature_columns: tuple[str, ...] = Field(min_length=1)
    text_columns: tuple[str, ...] = ()
    split_seed: int
    split_manifest_hash: str
    cv_folds: int = Field(ge=2, le=5)
    search_training_seed: int
    allowed_model_families: tuple[ModelFamily, ...] = Field(min_length=1)
    decision_policy: DecisionPolicy
    budgets: BudgetLimits
    loop_policy: LoopPolicy = LoopPolicy()
    sealed_holdout_sha256: str
    memory_snapshot_hash: str
    allow_custom_features: Literal[False] = False
    final_grader: Literal["local_holdout"] = "local_holdout"


class ExecutionResult(StrictModel):
    experiment_id: str
    purpose: str
    status: Literal["ok", "failed", "timeout", "invalid"]
    split_seed: int | None = None
    fold_scores: tuple[float, ...] = ()
    mean_score: float | None = None
    fit_attempts: int = Field(default=0, ge=0)
    fit_completed: int = Field(default=0, ge=0)
    fold_hash: str | None = None
    dataset_hash: str | None = None
    metric: str | None = None
    duration_seconds: float = Field(default=0, ge=0)
    artifact_ref: str
    error: str | None = None
