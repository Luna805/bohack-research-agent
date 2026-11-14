"""Exercise the real OpenAI-compatible HTTP path against a local fake server (no network)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip("pydantic_ai")

from budgetlab.proposers import LLMSettings, PydanticAIProposer  # noqa: E402
from budgetlab.schemas import ProposalBatch  # noqa: E402

BATCH = {
    "previous_result_interpretation": "Baseline only.",
    "intent": "explore",
    "direction": "class weighting",
    "candidates": [
        {
            "candidate_id": f"c{index}",
            "hypothesis": {
                "statement": "Balanced weights raise minority-class F1.",
                "evidence_refs": ["baseline", "eda"],
                "comparator_experiment_id": "baseline",
                "decision_policy_id": "practical_gain_v2",
                "proposed_change": "class_weight=balanced",
                "predicted_metric_delta": 0.01,
            },
            "experiment": {
                "model": {"family": family, "class_weight": "balanced"},
            },
        }
        for index, family in enumerate(("logistic_regression", "random_forest"))
    ],
}
CONTEXT = {"mode": "normal", "experiments": [{"id": "baseline"}], "best_id": "baseline"}


class FakeOpenAI:
    """Minimal /v1/chat/completions endpoint answering in tool, native or prompted form."""

    def __init__(self, *, status: int = 200, include_usage: bool = True) -> None:
        self.calls: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - http.server API
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.calls.append(body)
                if status != 200:
                    payload = {"error": {"message": "fake failure", "type": "server_error"}}
                else:
                    message: dict = {"role": "assistant", "content": json.dumps(BATCH)}
                    finish = "stop"
                    if body.get("tools") and body.get("tool_choice") != "none":
                        name = body["tools"][0]["function"]["name"]
                        message = {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": name, "arguments": json.dumps(BATCH)},
                                }
                            ],
                        }
                        finish = "tool_calls"
                    payload = {
                        "id": "fake",
                        "object": "chat.completion",
                        "created": 1,
                        "model": body.get("model", "fake"),
                        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                    }
                    if include_usage:
                        payload["usage"] = {
                            "prompt_tokens": 40,
                            "completion_tokens": 30,
                            "total_tokens": 70,
                        }
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fake_openai(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    servers: list[FakeOpenAI] = []

    def start(**kwargs) -> FakeOpenAI:
        server = FakeOpenAI(**kwargs)
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.close()


def _proposer(server: FakeOpenAI, mode: str = "tool") -> PydanticAIProposer:
    return PydanticAIProposer(
        LLMSettings(
            model_name="fake-model",
            base_url=server.base_url,
            api_key="test-key",
            output_mode=mode,
            max_output_tokens=500,
            timeout_seconds=10,
        )
    )


@pytest.mark.parametrize("mode", ["tool", "native", "prompted"])
def test_http_output_modes_use_raw_provider_usage(fake_openai, mode) -> None:
    server = fake_openai()
    outcome = _proposer(server, mode).propose(CONTEXT)
    assert outcome.error is None
    assert isinstance(outcome.output, ProposalBatch)
    assert len(server.calls) == 1
    assert outcome.details["usage_source"] == "http"
    assert (outcome.details["input_tokens"], outcome.details["output_tokens"]) == (40, 30)
    assert outcome.usage.llm_tokens == 70
    assert outcome.usage.llm_requests == 1
    assert outcome.unknown.llm_tokens == 0


def test_missing_usage_is_booked_as_unknown(fake_openai) -> None:
    server = fake_openai(include_usage=False)
    outcome = _proposer(server).propose(CONTEXT)
    assert outcome.error is None
    assert outcome.usage.llm_requests == 1
    assert outcome.usage.llm_tokens == 0
    assert outcome.details["requests_without_usage"] == 1
    assert outcome.unknown.llm_tokens >= 500


def test_provider_errors_are_not_retried_silently(fake_openai) -> None:
    server = fake_openai(status=500)
    outcome = _proposer(server).propose(CONTEXT)
    assert outcome.output is None
    assert outcome.error is not None
    assert len(server.calls) == 1  # SDK retries are off: exactly one billable attempt
    assert outcome.usage.llm_requests == 1
    assert outcome.unknown.llm_tokens > 0


def test_extra_body_is_forwarded_to_provider(fake_openai) -> None:
    server = fake_openai()
    settings = LLMSettings(
        model_name="fake-model",
        base_url=server.base_url,
        api_key="test-key",
        output_mode="tool",
        max_output_tokens=500,
        timeout_seconds=10,
        extra_body={"enable_thinking": False},
    )
    outcome = PydanticAIProposer(settings).propose(CONTEXT)
    assert outcome.error is None
    assert len(server.calls) == 1
    assert server.calls[0].get("enable_thinking") is False
