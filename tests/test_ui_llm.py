"""The page's LLM wiring: settings come from the official matrix, calls are logged with usage."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from budgetlab.proposers import CallOutcome
from budgetlab.schemas import ResourceVector
from budgetlab.ui.llm import llm_overrides, llm_problem, log_call, research_config

ROOT = Path(__file__).resolve().parents[1]


def test_llm_runs_use_the_official_matrix_settings() -> None:
    base = yaml.safe_load((ROOT / "configs" / "bank_marketing.yaml").read_text(encoding="utf-8"))
    config = research_config(base, ROOT)
    overrides = llm_overrides(ROOT)
    assert config["proposer"] == "llm"
    assert config["budget"]["max_llm_requests"] == overrides["budget"]["max_llm_requests"] > 0
    assert config["llm"]["extra_body"] == overrides["llm"]["extra_body"]
    assert config["budget"]["max_experiments"] == base["budget"]["max_experiments"]
    assert base["budget"]["max_llm_requests"] == 0  # the shared config is not modified


def test_missing_credentials_are_reported(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    problem = llm_problem(tmp_path)  # no .env in tmp_path
    assert problem is not None


def test_log_call_records_usage_and_errors(tmp_path) -> None:
    outcome = CallOutcome(
        output=None,
        usage=ResourceVector(llm_tokens=70, llm_requests=1),
        details={"model": "fixture"},
        error="RuntimeError: provider down",
    )
    path = tmp_path / "ui_state" / "qa_calls.jsonl"
    log_call(path, "qa", outcome, run_id="r1", question="为什么？")
    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["kind"] == "qa" and row["run_id"] == "r1" and row["question"] == "为什么？"
    assert row["usage"]["llm_tokens"] == 70 and row["error"].startswith("RuntimeError")
