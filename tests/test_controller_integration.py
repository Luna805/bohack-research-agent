from __future__ import annotations

import json

import pytest

from budgetlab.controller import replay_run, reproduce_run, run_research
from budgetlab.evaluation import evaluate_frozen_run


def test_scripted_loop_real_training_holdout_reproduce_and_replay(
    tmp_path, data_root, smoke_config
) -> None:
    summary = run_research(smoke_config, "budgetlab", tmp_path / "runs", data_root)
    run_id = summary["run_id"]
    run_dir = tmp_path / "runs" / run_id
    assert summary["proposal_source"] == "scripted"
    assert summary["counts"]["rounds"] >= 1
    assert summary["counts"]["proposer_experiments"] >= 2
    assert summary["counts"]["tool_search_experiments"] >= 1
    assert summary["llm"]["requests"] == 0
    assert summary["stop_reason"] in {"max_rounds", "diminishing_returns", "no_valid_candidates"}
    assert (run_dir / "delivery" / "model.joblib").exists()
    assert (run_dir / "rounds" / "round-01.json").exists()
    record = json.loads((run_dir / "experiments" / "r01-c1.json").read_text(encoding="utf-8"))
    assert record["hypothesis_check"]["computed_by"] == "evaluator"
    assert record["vs_baseline"]["comparator_experiment_id"] == "baseline"

    final = evaluate_frozen_run(run_id, tmp_path / "runs")
    assert 0 <= final["holdout_score"] <= 1
    with pytest.raises(RuntimeError, match="already evaluated"):
        evaluate_frozen_run(run_id, tmp_path / "runs")
    assert "sealed holdout score" in (run_dir / "report.md").read_text(encoding="utf-8")

    reproduction = reproduce_run(run_id, tmp_path / "runs")
    assert reproduction["status"] == "ok"

    budget_before = (run_dir / "budget.json").read_text(encoding="utf-8")
    replay = replay_run(run_id, tmp_path / "runs")
    assert replay["fit_attempts_started_by_replay"] == 0
    assert budget_before == (run_dir / "budget.json").read_text(encoding="utf-8")


def test_random_search_uses_zero_tokens(tmp_path, data_root, smoke_config) -> None:
    smoke_config["random_search_experiments"] = 2
    summary = run_research(smoke_config, "random_search", tmp_path / "runs", data_root)
    assert summary["counts"]["tool_search_experiments"] == 2
    assert summary["counts"]["rounds"] == 0
    assert summary["llm"]["calls"] == 0


def _fake_llm_proposer(calls: list[dict]):
    """PydanticAI FunctionModel that answers through the real output tool."""
    from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
    from pydantic_ai.models.function import AgentInfo, FunctionModel

    from budgetlab.proposers import LLMSettings, PydanticAIProposer

    def respond(messages, info: AgentInfo) -> ModelResponse:
        prompt = next(
            part.content
            for message in messages
            for part in getattr(message, "parts", [])
            if isinstance(part, UserPromptPart)
        )
        context = json.loads(prompt)
        calls.append(context)
        best = context["best_id"]
        round_no = len(calls)
        candidates = []
        for index, c_value in enumerate((0.1 * round_no, 5.0 * round_no)):
            candidates.append(
                {
                    "candidate_id": f"llm-{round_no}-{index}",
                    "hypothesis": {
                        "statement": f"Regularisation C={c_value} changes the fit.",
                        "evidence_refs": [best, "not-a-real-ref"],
                        "comparator_experiment_id": best,
                        "decision_policy_id": "practical_gain_v2",
                        "proposed_change": f"C={c_value}",
                        "predicted_metric_delta": 0.001,
                    },
                    "experiment": {
                        "model": {
                            "family": "logistic_regression",
                            "c": c_value,
                            "max_iter": 500,
                        },
                        "preprocessing": {"numeric_scaler": "standard"},
                    },
                }
            )
        # Round 2 resubmits the baseline spec to exercise the duplicate guard.
        if round_no == 2:
            candidates[1]["experiment"] = {
                "model": {"family": "logistic_regression", "c": 1.0, "max_iter": 500},
                "preprocessing": {"numeric_scaler": "standard"},
            }
        batch = {
            "previous_result_interpretation": "fixture",
            "intent": "explore",
            "direction": "regularisation",
            "candidates": candidates,
        }
        return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=batch)])

    settings = LLMSettings(model_name="fixture", base_url=None, api_key=None, max_output_tokens=800)
    return PydanticAIProposer(settings, model=FunctionModel(respond))


def test_llm_proposer_is_metered_and_duplicates_are_blocked(
    tmp_path, data_root, smoke_config
) -> None:
    pytest.importorskip("pydantic_ai")
    smoke_config["budget"].update(max_llm_requests=10, max_llm_tokens=200_000)
    smoke_config["loop"] = {"max_rounds": 2, "initial_tool_search": 0, "stagnation_stop": 5}
    calls: list[dict] = []
    summary = run_research(
        smoke_config,
        "budgetlab_no_schedule",
        tmp_path / "runs",
        data_root,
        proposer=_fake_llm_proposer(calls),
    )
    run_dir = tmp_path / "runs" / summary["run_id"]
    assert summary["proposal_source"] == "llm"
    assert len(calls) == 2
    assert summary["llm"]["requests"] == 2
    assert summary["llm"]["tokens"] > 0
    assert summary["counts"]["duplicates_blocked"] == 1
    lines = (run_dir / "llm_calls.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["details"]["input_tokens"] > 0
    # the second context tells the proposer what the controller rejected
    assert calls[1]["experiments"][-1]["id"].startswith("r01")


def test_zero_llm_budget_stops_before_any_request(tmp_path, data_root, smoke_config) -> None:
    pytest.importorskip("pydantic_ai")
    calls: list[dict] = []
    summary = run_research(
        smoke_config,
        "budgetlab_no_schedule",
        tmp_path / "runs",
        data_root,
        proposer=_fake_llm_proposer(calls),
    )
    assert calls == []
    assert summary["stop_reason"] == "llm_budget_exhausted"
    assert summary["llm"]["requests"] == 0
