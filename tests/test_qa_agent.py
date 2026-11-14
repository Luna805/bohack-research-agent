"""Offline tests for the open-question agent (role A). No network, no API key."""

from __future__ import annotations

import json

import pytest

from budgetlab.proposers import LLMSettings
from budgetlab.qa import EvidenceRef
from budgetlab.qa.agent import answer_open, extract_numbers, gather_evidence, number_in_evidence
from budgetlab.qa.evidence import EvidenceStore

RUN_ID = "20261114T081804Z-budgetlab-test01"
SETTINGS = LLMSettings(model_name="fixture", base_url=None, api_key=None, max_output_tokens=3000)


def _write(path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture
def store(tmp_path) -> EvidenceStore:
    run = tmp_path / "runs" / RUN_ID
    _write(
        run / "summary.json",
        {
            "run_id": RUN_ID,
            "baseline_score": 0.6412489489377238,
            "delivered_dev_score": 0.7097981281650848,
            "delivered_experiment_id": "r01-c1",
            "confirmation_status": "confirmed_pass",
            "llm": {"requests": 10, "tokens": 84514},
            "budget": {"used": {"llm_tokens": 84514}, "reservations": {"x": {"big": 1}}},
            "experiments": [
                {"id": "baseline", "mean_score": 0.6412},
                {"id": "r01-c1", "mean_score": 0.7098, "delta_vs_baseline": 0.0686},
            ],
            "trajectory": [{"experiment_id": "r01-c1", "best_score_after": 0.7098}],
        },
    )
    _write(run / "experiments" / "r01-c1.json", {"experiment_id": "r01-c1"})
    _write(run / "rounds" / "round-01.json", {"round_index": 1, "proposal": {"candidates": []}})
    (run / "events.jsonl").write_text("", encoding="utf-8")
    (run / "llm_calls.jsonl").write_text(
        json.dumps({"action_id": "llm:proposer:r01", "role": "proposer", "details": {}}) + "\n",
        encoding="utf-8",
    )
    return EvidenceStore(tmp_path / "runs", tmp_path / "results")


def _model(answer: str, evidence: list[dict], seen: list | None = None):
    pytest.importorskip("pydantic_ai")
    from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    def respond(messages, info: AgentInfo) -> ModelResponse:
        if seen is not None:
            seen.extend(
                json.loads(part.content)
                for message in messages
                for part in getattr(message, "parts", [])
                if isinstance(part, UserPromptPart)
            )
        payload = {"answer": answer, "evidence": evidence}
        return ModelResponse(
            parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=payload)]
        )

    return FunctionModel(respond)


def test_numbers_and_citations_are_checked_by_code(store) -> None:
    final = store.runs_root / RUN_ID / "final_evaluation.json"
    _write(final, {"holdout_score": 0.7127013638700477, "holdout_ci95": [0.698, 0.7278]})
    answer = (
        "交付实验 r01-c1 的开发集分数 0.7098，比基线 0.6412 高 6.9%；holdout 0.7127。"
        "共用 84,514 Token。另一个数 0.9999 是编的。"
    )
    cited = [
        {"kind": "summary", "ref_id": "summary"},
        {"kind": "experiment", "ref_id": "r01-c1"},
        {"kind": "experiment", "ref_id": "r09-c9"},
        {"kind": "round", "ref_id": "round-01"},
        {"kind": "round", "ref_id": "7"},
        {"kind": "llm_call", "ref_id": "llm:proposer:r01"},
        {"kind": "final_evaluation", "ref_id": "final_evaluation.json"},
    ]
    seen: list = []
    result, outcome = answer_open(
        "提升了多少？",
        RUN_ID,
        [],
        store=store,
        settings=SETTINGS,
        model=_model(answer, cited, seen),
    )
    assert outcome.error is None
    assert result.source == "llm"
    assert result.numbers == ["0.7098", "0.6412", "6.9%", "0.7127", "84,514", "0.9999"]
    assert result.verified_numbers == ["0.7098", "0.6412", "6.9%", "0.7127", "84,514"]
    assert [(ref.kind, ref.ref_id) for ref in result.evidence] == [
        ("summary", "summary.json"),
        ("experiment", "r01-c1"),
        ("round", "1"),
        ("llm_call", "llm:proposer:r01"),
        ("final_evaluation", "final_evaluation.json"),
    ]
    assert all(isinstance(ref, EvidenceRef) and ref.run_id == RUN_ID for ref in result.evidence)
    assert outcome.details["evidence_dropped"] == 2
    assert outcome.usage.llm_requests == 1 and outcome.usage.llm_tokens > 0
    # The model saw rounded evidence, without the raw budget reservations.
    evidence = seen[0]["evidence"]
    assert evidence["summary"]["baseline_score"] == 0.6412
    assert "reservations" not in evidence["summary"]["budget"]


def test_unevaluated_holdout_cannot_be_cited(store) -> None:
    assert gather_evidence(store, RUN_ID)["final_evaluation"] is None
    cited = [{"kind": "final_evaluation", "ref_id": "final_evaluation.json"}]
    result, _ = answer_open(
        "holdout 多少？",
        RUN_ID,
        [{"question": "上一问", "answer": "上一答"}],
        store=store,
        settings=SETTINGS,
        model=_model("holdout 还没有评测。", cited),
    )
    assert result.evidence == []
    assert result.numbers == []


def test_model_failure_is_reported_not_hidden(store) -> None:
    pytest.importorskip("pydantic_ai")
    from pydantic_ai.models.function import FunctionModel

    def broken(messages, info):
        raise RuntimeError("provider down")

    result, outcome = answer_open(
        "为什么？", RUN_ID, [], store=store, settings=SETTINGS, model=FunctionModel(broken)
    )
    assert outcome.error is not None and "provider down" in outcome.error
    assert result.answer == "" and result.evidence == []


def test_number_extraction_skips_ids() -> None:
    text = "r05-c2 在 20261114T081804Z-budgetlab-bf2580 里得到 0.71，第 3 轮。"
    assert extract_numbers(text) == ["0.71", "3"]
    assert number_in_evidence("0.71", [0.7098])
    assert not number_in_evidence("0.7100", [0.7098])
    assert number_in_evidence("71%", [0.7098])
