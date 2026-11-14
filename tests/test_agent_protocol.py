"""Offline tests for the protocol-drafting agent (role A). No network, no API key."""

from __future__ import annotations

import pytest

from budgetlab.agents.protocol_agent import (
    DraftProtocol,
    FieldDecision,
    ProtocolAgent,
    build_protocol_context,
    score_draft,
)
from budgetlab.proposers import LLMSettings
from budgetlab.tasks import load_card


def test_build_protocol_context_strips_availability() -> None:
    profile = {
        "rows": 10,
        "positive_rate": 0.5,
        "columns": [{"name": "age", "availability": "available", "kind": "numeric"}],
    }
    context = build_protocol_context("classify the rows", ["age", "y"], profile)
    assert context["task_description"] == "classify the rows"
    assert context["columns"] == ["age", "y"]
    assert context["data_profile"] == [{"name": "age", "kind": "numeric"}]


def test_score_draft_against_bank_card() -> None:
    card = load_card("bank_marketing")
    target = card["target"]["column"]
    ground_truth = {
        field["name"]: field["availability"] for field in card["fields"] if field["name"] != target
    }
    draft = DraftProtocol(
        title="Bank telemarketing",
        business_question="Predict term-deposit subscription.",
        prediction_time="before the outbound call is placed",
        target_column=target,
        positive_label="yes",
        primary_metric="f1_macro",
        fields=[
            FieldDecision(name=name, availability=availability, reason="matched the card")
            for name, availability in ground_truth.items()
        ],
        source="llm",
    )
    result = score_draft(draft, card)
    assert result["first_pass_accuracy"] == 1.0
    assert result["fields_total"] == len(ground_truth)
    assert result["errors"] == []
    assert result["missing_fields"] == []

    # Mark the post-outcome `duration` as available -> exactly one error, 100% minus one field.
    for field in draft.fields:
        if field.name == "duration":
            field.availability = "available"
    result = score_draft(draft, card)
    assert result["errors"] == [
        {"name": "duration", "expected": "post_outcome", "got": "available"}
    ]
    assert result["first_pass_accuracy"] == (result["fields_total"] - 1) / result["fields_total"]


def _fake_agent(columns: list[str], target: str = "y") -> ProtocolAgent:
    pytest.importorskip("pydantic_ai")
    from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    def respond(messages, info: AgentInfo) -> ModelResponse:
        next(
            part.content
            for message in messages
            for part in getattr(message, "parts", [])
            if isinstance(part, UserPromptPart)
        )
        fields = []
        for name in columns:
            if name == target:
                continue
            if name == "duration":
                fields.append(
                    {
                        "name": name,
                        "availability": "post_outcome",
                        "reason": "duration is only known after the call ends.",
                    }
                )
            else:
                fields.append(
                    {
                        "name": name,
                        "availability": "available",
                        "reason": f"{name} is usable before prediction.",
                    }
                )
        draft = {
            "title": "Bank telemarketing",
            "business_question": "Predict term-deposit subscription.",
            "prediction_time": "before the outbound call is placed",
            "target_column": target,
            "positive_label": "yes",
            "primary_metric": "f1_macro",
            "fields": fields,
            "questions_for_user": [],
        }
        return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=draft)])

    settings = LLMSettings(model_name="fixture", base_url=None, api_key=None, max_output_tokens=800)
    return ProtocolAgent(settings, model=FunctionModel(respond))


def test_protocol_agent_drafts_and_meters_offline() -> None:
    columns = ["age", "job", "duration", "y"]
    profile = {
        "rows": 1000,
        "positive_rate": 0.11,
        "columns": [
            {"name": "age", "availability": "available", "kind": "numeric"},
            {"name": "job", "availability": "available", "kind": "categorical"},
            {"name": "duration", "availability": "post_outcome", "kind": "numeric"},
        ],
    }
    agent = _fake_agent(columns)
    context = build_protocol_context("Predict the subscription before the call.", columns, profile)
    outcome = agent.draft(context)

    assert outcome.error is None
    assert isinstance(outcome.output, DraftProtocol)
    draft = outcome.output
    assert draft.source == "llm"
    assert draft.target_column == "y"
    assert {field.name for field in draft.fields} == {"age", "job", "duration"}
    assert {field.name: field.availability for field in draft.fields}["duration"] == "post_outcome"
    assert outcome.details["usage_source"] == "framework"
    assert outcome.usage.llm_requests == 1
    assert outcome.usage.llm_tokens > 0
