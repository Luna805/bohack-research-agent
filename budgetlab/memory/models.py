"""Strict lesson models for the cross-run lesson bank (internal to ``budgetlab.memory``).

A lesson is "condition -> action -> observed effect -> evidence". Every number in it is copied
from program-written development artifacts (experiment verdicts, confirmation); no LLM text is
ever stored as a fact, and no holdout score is ever read.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from ..schemas import StrictModel

LessonStatus = Literal["candidate", "supported_in_sources", "deprecated"]
ActionKind = Literal[
    "model_family",
    "class_weight",
    "hyperparameters",
    "preprocessing",
    "feature_actions",
    "combined",
]
ColumnKind = Literal["possible_sentinel", "has_missing", "skewed_numeric"]


class LessonConditions(StrictModel):
    """When a lesson may be shown: development-profile ranges and structural prerequisites."""

    primary_metric: str
    rows_range: tuple[int, int]
    minority_rate_range: tuple[float, float]
    requires_families: tuple[str, ...] = ()
    requires_column_kinds: tuple[ColumnKind, ...] = ()
    source_columns: tuple[str, ...] = ()
    source_task_ids: tuple[str, ...] = Field(min_length=1)


class LessonAction(StrictModel):
    """The program-computed difference between a tested spec and its comparator."""

    kind: ActionKind
    scope: Literal["single_comparison", "confirmed_recipe"]
    parts: tuple[dict[str, Any], ...] = Field(min_length=1)
    summary: str
    spec: dict[str, Any]
    spec_hash: str


class Observation(StrictModel):
    """One verdict from one source run; positive ones support, not_met ones count against."""

    task_id: str
    run_id: str
    experiment_id: str
    comparator: str
    metric: str
    delta: float
    min_effect: float
    verdict: Literal["candidate_pass", "confirmed_pass", "not_met"]


class ObservedEffect(StrictModel):
    metric: str
    delta: float
    comparator: str
    run_id: str
    experiment_ids: tuple[str, ...] = Field(min_length=1)
    min_effect: float


class Lesson(StrictModel):
    lesson_id: str
    version: int = Field(default=1, ge=1)
    action_key: str
    conditions: LessonConditions
    action: LessonAction
    observed_effect: ObservedEffect
    support: int = Field(ge=0)
    counterexamples: tuple[Observation, ...] = ()
    evidence: tuple[Observation, ...] = Field(min_length=1)
    status: LessonStatus
    limitations: tuple[str, ...] = ()
