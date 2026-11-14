"""Schema-rejected proposer outputs stay readable and reach the next round.

Live qwen3.7-plus calls sometimes wrote ``hypothesis`` as a sentence, flattened its fields into
the candidate and left out ``experiment``; one such round was lost with only
"Exceeded maximum output retries (1)" on record.
"""

from __future__ import annotations

import json

import pytest

from budgetlab.controller import run_research

pytest.importorskip("pydantic_ai")


def _candidate(index: int, *, flat: bool) -> dict:
    hypothesis = {
        "statement": f"Regularisation C={index + 0.5} changes the fit.",
        "evidence_refs": ["baseline"],
        "comparator_experiment_id": "baseline",
        "decision_policy_id": "practical_gain_v2",
        "proposed_change": f"C={index + 0.5}",
        "predicted_metric_delta": 0.001,
    }
    if flat:  # the observed failure: sentence as hypothesis, fields flattened, no experiment
        return {"candidate_id": f"c{index}", **hypothesis, "hypothesis": hypothesis["statement"]}
    return {
        "candidate_id": f"c{index}",
        "hypothesis": hypothesis,
        "experiment": {"model": {"family": "logistic_regression", "c": index + 0.5}},
    }


def _proposer(flat_answers: int, contexts: list[dict] | None = None):
    """FunctionModel that answers flat ``flat_answers`` times, then correctly."""
    from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    from budgetlab.proposers import LLMSettings, PydanticAIProposer

    answers = {"n": 0}

    def respond(messages, info: AgentInfo) -> ModelResponse:
        if contexts is not None and len(messages) == 1:
            prompt = next(
                part.content for part in messages[0].parts if isinstance(part, UserPromptPart)
            )
            contexts.append(json.loads(prompt))
        flat = answers["n"] < flat_answers
        answers["n"] += 1
        batch = {
            "previous_result_interpretation": "fixture",
            "intent": "explore",
            "direction": "regularisation",
            "candidates": [_candidate(i, flat=flat) for i in range(2)],
        }
        return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=batch)])

    settings = LLMSettings(model_name="fixture", base_url=None, api_key=None, max_output_tokens=800)
    return PydanticAIProposer(settings, model=FunctionModel(respond))


def test_schema_descriptions_spell_out_the_candidate_nesting() -> None:
    from budgetlab.schemas import ProposalBatch

    candidate = ProposalBatch.model_json_schema()["$defs"]["Candidate"]["properties"]
    assert "not a string" in candidate["hypothesis"]["description"]
    assert "Required" in candidate["experiment"]["description"]


def test_flat_output_is_retried_and_the_transcript_kept() -> None:
    outcome = _proposer(flat_answers=1).propose({"best_id": "baseline"})
    assert outcome.error is None
    assert outcome.usage.llm_requests == 2
    assert outcome.details["rejected_outputs"] == 1
    assert "candidates.*.experiment: Field required" in outcome.details["validation_errors"]
    # JSON args say "an object", dict args "a valid dictionary": only the location is stable.
    assert any(
        line.startswith("candidates.*.hypothesis: Input should be")
        for line in outcome.details["validation_errors"]
    )
    assert outcome.transcript and len(outcome.transcript) >= 4


def test_clean_output_keeps_no_transcript() -> None:
    outcome = _proposer(flat_answers=0).propose({"best_id": "baseline"})
    assert outcome.error is None
    assert outcome.details["rejected_outputs"] == 0
    assert "validation_errors" not in outcome.details
    assert outcome.transcript is None


def test_exhausted_retries_report_the_last_schema_errors() -> None:
    outcome = _proposer(flat_answers=99).propose({"best_id": "baseline"})
    assert outcome.output is None
    assert "Exceeded maximum output retries (2)" in outcome.error
    assert outcome.usage.llm_requests == 3
    assert outcome.details["rejected_outputs"] == 3
    assert "candidates.*.experiment: Field required" in outcome.details["validation_errors"]
    assert outcome.transcript


def test_failed_round_saves_transcript_and_feeds_errors_back(
    tmp_path, data_root, smoke_config
) -> None:
    smoke_config["budget"].update(max_llm_requests=10, max_llm_tokens=200_000)
    smoke_config["loop"] = {"max_rounds": 2, "initial_tool_search": 0, "stagnation_stop": 5}
    contexts: list[dict] = []
    summary = run_research(
        smoke_config,
        "budgetlab_no_schedule",
        tmp_path / "runs",
        data_root,
        proposer=_proposer(flat_answers=99, contexts=contexts),
    )
    run_dir = tmp_path / "runs" / summary["run_id"]
    first = json.loads((run_dir / "llm_calls.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert first["transcript_ref"] == "llm/proposer-r01.transcript.json"
    assert (run_dir / first["transcript_ref"]).is_file()
    assert len(contexts) == 2
    feedback = contexts[1]["controller_feedback"]
    assert feedback[0].startswith("previous proposal failed")
    assert "schema error at candidates.*.experiment: Field required" in feedback
    assert contexts[0]["decision_rule"]["policy_id"]
