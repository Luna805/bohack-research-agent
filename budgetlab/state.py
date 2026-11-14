"""In-memory research state. Every field is derived from program-computed results."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Literal

from .contracts import canonical_spec, spec_hash
from .schemas import EvaluationRecord, ExecutionResult, ExperimentSpec

Origin = Literal["baseline", "proposer", "tool_search"]


@dataclass
class ExperimentRecord:
    experiment_id: str
    origin: Origin
    round_index: int
    spec: ExperimentSpec
    spec_hash: str
    result: ExecutionResult
    vs_baseline: EvaluationRecord | None
    vs_previous_best: float | None
    previous_best_id: str | None
    hypothesis_check: EvaluationRecord | None = None
    candidate_id: str | None = None
    hypothesis: str | None = None
    elapsed_seconds: float = 0.0
    llm_tokens_so_far: int = 0
    best_score_after: float | None = None

    @property
    def ok(self) -> bool:
        return self.result.status == "ok" and self.result.mean_score is not None

    def summary(self) -> dict[str, Any]:
        """Compact row used in proposer context, reports and the UI."""
        row: dict[str, Any] = {
            "id": self.experiment_id,
            "origin": self.origin,
            "round": self.round_index,
            "spec": compact_spec(self.spec),
            "status": self.result.status,
            "mean_score": _r(self.result.mean_score),
            "fold_std": _r(statistics.pstdev(self.result.fold_scores))
            if len(self.result.fold_scores) > 1
            else None,
            "delta_vs_baseline": _r(self.vs_baseline.mean_paired_delta)
            if self.vs_baseline
            else None,
            "baseline_verdict": self.vs_baseline.policy_status if self.vs_baseline else None,
            "delta_vs_previous_best": _r(self.vs_previous_best),
            "seconds": _r(self.result.duration_seconds, 1),
        }
        if self.hypothesis_check is not None:
            row["hypothesis_comparator"] = self.hypothesis_check.comparator_experiment_id
            row["hypothesis_verdict"] = self.hypothesis_check.policy_status
            row["delta_vs_hypothesis_comparator"] = _r(self.hypothesis_check.mean_paired_delta)
        if self.vs_baseline is not None and self.vs_baseline.invalid_reason:
            row["invalid_reason"] = self.vs_baseline.invalid_reason
        if self.result.error:
            row["error"] = self.result.error[:300]
        if self.hypothesis:
            row["hypothesis"] = self.hypothesis[:240]
        return row


def _r(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(float(value), digits)


def compact_spec(spec: ExperimentSpec) -> dict[str, Any]:
    """Spec without default-valued noise, so prompts stay short."""
    value = canonical_spec(spec)
    model = {key: val for key, val in value["model"].items() if val is not None}
    preprocessing = {
        key: val
        for key, val in value["preprocessing"].items()
        if val is not None and val != _PREPROCESSING_DEFAULTS.get(key)
    }
    out: dict[str, Any] = {"model": model}
    if preprocessing:
        out["preprocessing"] = preprocessing
    if value["feature_actions"]:
        out["feature_actions"] = value["feature_actions"]
    return out


_PREPROCESSING_DEFAULTS = {
    "numeric_imputer": "median",
    "numeric_scaler": "none",
    "categorical_imputer": "most_frequent",
    "categorical_encoder": "onehot",
}


@dataclass
class RoundRecord:
    round_index: int
    mode: str
    trigger_source: Literal["agent", "rule", "error"]
    intent: str | None = None
    direction: str | None = None
    direction_changed: bool = False
    proposal_error: str | None = None
    selected: list[str] = field(default_factory=list)
    rejected: list[dict[str, str]] = field(default_factory=list)
    not_run: list[dict[str, str]] = field(default_factory=list)
    improved: bool = False


@dataclass
class ResearchState:
    baseline: ExperimentRecord
    min_effect: float
    optimize: str = "maximize"
    experiments: list[ExperimentRecord] = field(default_factory=list)
    rounds: list[RoundRecord] = field(default_factory=list)
    seen: dict[str, str] = field(default_factory=dict)
    best_id: str = ""
    stagnation: int = 0
    empty_rounds: int = 0
    direction: str | None = None
    tool_search_fits: int = 0
    tool_search_since_improvement: bool = False
    critic_since_improvement: bool = False
    critic_advice: dict[str, Any] | None = None
    feedback: list[str] = field(default_factory=list)
    stop_reason: str | None = None
    duplicates_blocked: int = 0
    invalid_rejected: int = 0
    lessons: list[dict[str, Any]] = field(default_factory=list)

    def lesson_refs(self) -> list[str]:
        """Evidence refs a proposal may cite for lessons matched before the contract froze."""
        return [f"lesson:{lesson['lesson_id']}" for lesson in self.lessons]

    def __post_init__(self) -> None:
        self.experiments.append(self.baseline)
        self.seen[self.baseline.spec_hash] = self.baseline.experiment_id
        self.best_id = self.baseline.experiment_id
        self.baseline.best_score_after = self.baseline.result.mean_score

    @property
    def best(self) -> ExperimentRecord:
        return self.get(self.best_id)

    def get(self, experiment_id: str) -> ExperimentRecord:
        for record in self.experiments:
            if record.experiment_id == experiment_id:
                return record
        raise KeyError(experiment_id)

    def known_ids(self) -> list[str]:
        return [record.experiment_id for record in self.experiments]

    def duplicate_of(self, spec: ExperimentSpec) -> str | None:
        return self.seen.get(spec_hash(spec))

    def add(self, record: ExperimentRecord) -> bool:
        """Store a finished experiment; return True when it beats the best by min_effect."""
        self.experiments.append(record)
        self.seen[record.spec_hash] = record.experiment_id
        improved = False
        best_mean = self.best.result.mean_score
        if record.ok and record.result.mean_score is not None and best_mean is not None:
            better = (
                record.result.mean_score < best_mean
                if self.optimize == "minimize"
                else record.result.mean_score > best_mean
            )
            if better:
                delta = record.vs_previous_best
                if self.optimize == "minimize":
                    improved = delta is not None and delta <= -self.min_effect
                else:
                    improved = (delta or 0.0) >= self.min_effect
                self.best_id = record.experiment_id
        record.best_score_after = self.best.result.mean_score
        return improved

    def family_seconds(self, family: str) -> float | None:
        durations = [
            record.result.duration_seconds
            for record in self.experiments
            if record.spec.model.family == family and record.result.status == "ok"
        ]
        return statistics.mean(durations) if durations else None

    def max_seconds(self) -> float | None:
        durations = [record.result.duration_seconds for record in self.experiments]
        return max(durations) if durations else None
