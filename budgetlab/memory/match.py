"""Deterministic lesson matching against a new run's development profile."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

MAX_LESSONS = 3
STATUS_RANK = {"supported_in_sources": 0, "candidate": 1}


def target_facts(profile: dict[str, Any]) -> dict[str, Any]:
    """Facts about the new task, computed only from its development profile."""
    available = [c for c in profile["columns"] if c.get("availability") == "available"]
    kinds = set()
    for column in available:
        if "possible_sentinel" in column:
            kinds.update({"possible_sentinel", "has_missing"})
        if (column.get("missing_rate") or 0) > 0:
            kinds.add("has_missing")
        if column.get("kind") == "numeric" and abs(column.get("skew") or 0) > 1:
            if (column.get("min") or 0) > -1:
                kinds.add("skewed_numeric")
    positive_rate = float(profile.get("positive_rate", profile.get("target_mean", 0.5)))
    return {
        "rows": int(profile["rows"]),
        "minority_rate": min(positive_rate, 1.0 - positive_rate),
        "columns": {c["name"] for c in available},
        "column_kinds": kinds,
    }


def mismatch(
    lesson: dict[str, Any],
    facts: dict[str, Any],
    *,
    primary_metric: str | None,
    allowed_families: Sequence[str] | None,
) -> str | None:
    """Reason a lesson does not apply, or None when every stated condition holds."""
    cond = lesson["conditions"]
    if lesson["status"] == "deprecated":
        return "deprecated"
    if primary_metric is not None and cond["primary_metric"] != primary_metric:
        return "different primary metric"
    low, high = cond["rows_range"]
    if not low <= facts["rows"] <= high:
        return "row count outside range"
    low_rate, high_rate = cond["minority_rate_range"]
    if not low_rate <= facts["minority_rate"] <= high_rate:
        return "class balance outside range"
    if allowed_families is not None and not set(cond["requires_families"]) <= set(allowed_families):
        return "model family not allowed"
    if cond["source_columns"]:
        same_columns = set(cond["source_columns"]) <= facts["columns"]
        same_kinds = (
            bool(cond["requires_column_kinds"])
            and set(cond["requires_column_kinds"]) <= facts["column_kinds"]
        )
        if not (same_columns or same_kinds):
            return "no column with the required property"
    return None


def match_lessons(
    profile: dict[str, Any],
    card: dict[str, Any],
    snapshot: list[dict[str, Any]],
    *,
    primary_metric: str | None = None,
    allowed_families: Sequence[str] | None = None,
    limit: int = MAX_LESSONS,
) -> list[dict[str, Any]]:
    """At most ``limit`` applicable lessons, best supported first, in a deterministic order.

    ``card`` is accepted for interface stability; availability is already applied to the
    profile's columns, so lessons can never point the proposer at an excluded field.
    """
    del card
    facts = target_facts(profile)
    applicable = [
        lesson
        for lesson in snapshot
        if mismatch(lesson, facts, primary_metric=primary_metric, allowed_families=allowed_families)
        is None
    ]
    applicable.sort(
        key=lambda lesson: (
            STATUS_RANK.get(lesson["status"], 9),
            -(lesson["support"] - len(lesson["counterexamples"])),
            -lesson["observed_effect"]["delta"],
            lesson["lesson_id"],
        )
    )
    return applicable[:limit]


def context_view(lesson: dict[str, Any]) -> dict[str, Any]:
    """The compact form the proposer sees (no raw evidence lists)."""
    effect = lesson["observed_effect"]
    return {
        "lesson_id": lesson["lesson_id"],
        "evidence_ref": f"lesson:{lesson['lesson_id']}",
        "status": lesson["status"],
        "source_tasks": list(lesson["conditions"]["source_task_ids"]),
        "action": lesson["action"]["summary"],
        "action_scope": lesson["action"]["scope"],
        "spec": lesson["action"]["spec"],
        "observed_effect": {
            "metric": effect["metric"],
            "delta": effect["delta"],
            "comparator": effect["comparator"],
            "min_effect_there": effect["min_effect"],
        },
        "support": lesson["support"],
        "counterexamples": len(lesson["counterexamples"]),
        "limitations": list(lesson["limitations"]),
    }
