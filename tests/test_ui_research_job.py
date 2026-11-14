"""Page workflow tests use fake engines and never open sealed evaluation data."""

import json
from unittest.mock import Mock

import pytest

from budgetlab.ledger import EventLedger
from budgetlab.ui import research_job


def test_page_research_finishes_before_final_test(monkeypatch, tmp_path):
    calls = []

    def research(config, system, runs_root, data_root, *, proposer_kind):
        calls.append("research_and_freeze")
        assert config == {"task_id": "fixture"}
        assert proposer_kind == "llm"
        assert runs_root == tmp_path
        assert data_root == tmp_path / "data"
        return {"run_id": "r1"}

    def evaluate(run_id, runs_root):
        assert calls == ["research_and_freeze"]
        calls.append("final_test")
        return {"run_id": run_id}

    monkeypatch.setattr(research_job, "run_research", research)
    monkeypatch.setattr(research_job, "evaluate_frozen_run", evaluate)
    result = research_job.run_page_research(
        {"task_id": "fixture"}, "budgetlab", tmp_path, tmp_path / "data", "llm"
    )
    assert calls == ["research_and_freeze", "final_test"]
    assert result["run_id"] == "r1"
    state = json.loads((tmp_path / "r1/ui_final_test.json").read_text())
    assert state["status"] == "completed"


def test_failed_research_never_runs_final_test(monkeypatch, tmp_path):
    monkeypatch.setattr(research_job, "run_research", Mock(side_effect=RuntimeError("failed")))
    evaluate = Mock()
    monkeypatch.setattr(research_job, "evaluate_frozen_run", evaluate)
    with pytest.raises(RuntimeError, match="failed"):
        research_job.run_page_research({}, "budgetlab", tmp_path, tmp_path, "llm")
    evaluate.assert_not_called()
    assert not list(tmp_path.glob("*/ui_final_test.json"))


def test_saved_final_test_is_reused_without_second_evaluation(monkeypatch, tmp_path):
    run = tmp_path / "r1"
    run.mkdir()
    saved = {"run_id": "r1", "holdout_score": 0.7}
    (run / "final_evaluation.json").write_text(json.dumps(saved))
    evaluate = Mock()
    monkeypatch.setattr(research_job, "evaluate_frozen_run", evaluate)
    assert research_job.finish_final_test("r1", tmp_path) == saved
    assert research_job.finish_final_test("r1", tmp_path) == saved
    evaluate.assert_not_called()


def test_failed_final_test_keeps_an_explicit_recoverable_state(monkeypatch, tmp_path):
    evaluate = Mock(side_effect=ValueError("frozen model hash mismatch"))
    monkeypatch.setattr(research_job, "evaluate_frozen_run", evaluate)
    with pytest.raises(ValueError, match="hash mismatch"):
        research_job.finish_final_test("r1", tmp_path)
    state = json.loads((tmp_path / "r1/ui_final_test.json").read_text())
    assert state == {"status": "failed", "error": "ValueError: frozen model hash mismatch"}
    assert not (tmp_path / "r1/final_evaluation.json").exists()
    evaluate.assert_called_once()


def test_ui_status_events_do_not_reuse_evaluator_sequence_numbers(monkeypatch, tmp_path):
    def evaluate(run_id, runs_root):
        ledger = EventLedger(run_id, runs_root / run_id)
        result = {"run_id": run_id, "holdout_score": 0.7}
        ledger.write_artifact("final_evaluation.json", result)
        ledger.append("final_evaluation_recorded", artifact_ref="final_evaluation.json")
        return result

    evaluate_mock = Mock(side_effect=evaluate)
    monkeypatch.setattr(research_job, "evaluate_frozen_run", evaluate_mock)
    research_job.finish_final_test("r1", tmp_path)
    research_job.finish_final_test("r1", tmp_path)
    events = EventLedger("r1", tmp_path / "r1").read_events()
    assert [e["seq"] for e in events] == [1, 2, 3]
    assert [e["event_type"] for e in events] == [
        "ui_final_test_running",
        "final_evaluation_recorded",
        "ui_final_test_completed",
    ]
    evaluate_mock.assert_called_once()


def test_explicit_retry_can_complete_after_failed_test(monkeypatch, tmp_path):
    evaluate = Mock(side_effect=[ValueError("missing model"), {"run_id": "r1"}])
    monkeypatch.setattr(research_job, "evaluate_frozen_run", evaluate)
    with pytest.raises(ValueError):
        research_job.finish_final_test("r1", tmp_path)
    assert research_job.finish_final_test("r1", tmp_path) == {"run_id": "r1"}
    state = json.loads((tmp_path / "r1/ui_final_test.json").read_text())
    assert state == {"status": "completed", "error": None}


def test_page_entrypoint_forwards_research_options(monkeypatch, tmp_path, capsys):
    config = tmp_path / "config.yaml"
    config.write_text("task_id: fixture\n")
    workflow = Mock(return_value={"run_id": "r1"})
    monkeypatch.setattr(research_job, "run_page_research", workflow)
    assert (
        research_job.main(
            [
                "--config",
                str(config),
                "--proposer",
                "llm",
                "--runs-root",
                str(tmp_path),
                "--data-root",
                str(tmp_path / "data"),
            ]
        )
        == 0
    )
    workflow.assert_called_once_with(
        {"task_id": "fixture"}, "budgetlab", tmp_path, tmp_path / "data", "llm"
    )
    assert json.loads(capsys.readouterr().out) == {"run_id": "r1"}


def test_legacy_evaluation_entrypoint_does_not_restart_research(monkeypatch, tmp_path):
    evaluate = Mock(return_value={"run_id": "r1"})
    research = Mock()
    monkeypatch.setattr(research_job, "finish_final_test", evaluate)
    monkeypatch.setattr(research_job, "run_page_research", research)
    assert research_job.main(["--evaluate-run-id", "r1", "--runs-root", str(tmp_path)]) == 0
    evaluate.assert_called_once_with("r1", tmp_path)
    research.assert_not_called()
