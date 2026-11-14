"""Protocol-drafting agent for the conversational research page.

Given a one-line task description plus a development-data profile *without* availability
labels, it drafts the ``DraftProtocol`` a human confirms before any model is trained
(INTERFACES 8.1). The draft is only a suggestion: field availability enters the frozen
contract only after a human confirms (and may edit) it, so these models stay mutable.

The agent reuses ``proposers._PydanticAIRole`` - the same metered, single-``httpx``-client
role as ``PydanticAIProposer`` - so every token is reported through a ``CallOutcome``. The
UI records these tokens separately from the research budget (``ui_state/llm_calls.jsonl``).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..proposers import CallOutcome, LLMSettings, _PydanticAIRole


class FieldDecision(BaseModel):
    """One field's suggested availability plus a one-sentence reason shown to a human."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    availability: Literal["available", "post_outcome", "identifier"]
    reason: str = Field(min_length=1)


class DraftProtocol(BaseModel):
    """A draft research protocol (INTERFACES 8.1). Mutable so a human can edit before confirm."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    business_question: str = Field(min_length=1)
    prediction_time: str = Field(min_length=1)
    target_column: str = Field(min_length=1)
    positive_label: str = Field(min_length=1)
    primary_metric: Literal["f1_macro", "accuracy", "roc_auc", "r2", "rmse", "mae"]
    fields: list[FieldDecision] = Field(min_length=1)
    questions_for_user: list[str] = Field(default_factory=list)
    source: Literal["llm", "card", "manual"] = "llm"


PROTOCOL_INSTRUCTIONS = """\
You are the Protocol Agent inside BudgetLab. Given a one-line task description plus a
development-data profile WITHOUT any availability labels, draft the research protocol a human
will confirm before any model is trained. Return exactly one DraftProtocol.

Decide:
- title: a short name for the task; business_question: one sentence restating what to predict.
- prediction_time: the moment before which predictions must be made (e.g. "before the outbound
  call is placed").
- target_column and positive_label: infer them from the description (e.g. the "yes"/"1" class).
- primary_metric: for a categorical target, f1_macro when classes are imbalanced, roc_auc for
  ranking, accuracy only when the description says the classes are balanced. For a continuous
  target, r2 (higher is better) or rmse/mae (lower is better).
- fields: one FieldDecision for EVERY column except target_column. availability is one of:
  * "identifier": a row id or key with no predictive value.
  * "post_outcome": only known after the outcome is known (e.g. call duration, a "days since"
    counter measured after the event), or otherwise leaks the label at prediction time.
  * "available": usable before prediction time.
  Give a one-sentence reason for each field, especially the post_outcome and identifier ones.
- questions_for_user: anything you are unsure about (target, positive class, metric, or a field
  you could not classify). Empty list is fine when nothing is ambiguous.

Use the column names, descriptions, types and statistics to decide. Never invent columns; cover
only the columns listed under `columns`.
"""


def build_protocol_context(
    description: str,
    columns: list[str],
    profile: dict[str, Any],
) -> dict[str, Any]:
    """Build the LLM input for a protocol draft.

    ``profile`` is ``profile_development`` output; availability labels are stripped here so the
    agent reasons from the data alone (INTERFACES 8.1). ``columns`` is every column including
    the target. The context never contains holdout information because ``profile`` comes from
    the development set.
    """
    data_profile = []
    for entry in profile.get("columns", []):
        row = {key: value for key, value in entry.items() if key != "availability"}
        data_profile.append(row)
    return {
        "task_description": " ".join(str(description).split()),
        "columns": list(columns),
        "rows": profile.get("rows"),
        "positive_rate": profile.get("positive_rate"),
        "data_profile": data_profile,
    }


def score_draft(draft: DraftProtocol, card: dict[str, Any]) -> dict[str, Any]:
    """Compare a draft's field availability against a scenario card's ground truth.

    Returns first-pass accuracy over every non-target field, plus the list of disagreements and
    any missing/extra fields. Cost is measured separately on the ``CallOutcome`` returned by the
    agent.
    """
    target = card["target"]["column"]
    ground_truth = {
        field["name"]: field["availability"]
        for field in card.get("fields", [])
        if field["name"] != target
    }
    decided = {field.name: field.availability for field in draft.fields}
    errors: list[dict[str, str]] = []
    correct = 0
    for name, truth in ground_truth.items():
        if name not in decided:
            continue
        if decided[name] == truth:
            correct += 1
        else:
            errors.append({"name": name, "expected": truth, "got": decided[name]})
    total = len(ground_truth)
    return {
        "task_id": card.get("task_id"),
        "first_pass_accuracy": round(correct / total, 4) if total else None,
        "fields_total": total,
        "fields_correct": correct,
        "errors": errors,
        "missing_fields": sorted(set(ground_truth) - set(decided)),
        "extra_fields": sorted(set(decided) - set(ground_truth)),
    }


class ProtocolAgent(_PydanticAIRole):
    """One strict-output role that drafts a ``DraftProtocol`` with full metering."""

    source = "llm"

    def __init__(self, settings: LLMSettings, *, model: Any | None = None) -> None:
        super().__init__(settings, DraftProtocol, PROTOCOL_INSTRUCTIONS, model=model)

    def draft(self, context: dict[str, Any]) -> CallOutcome:
        outcome = self._call(context)
        if outcome.output is not None:
            # The label is decided by the caller of the agent, never by the model itself.
            outcome.output.source = "llm"
        return outcome
