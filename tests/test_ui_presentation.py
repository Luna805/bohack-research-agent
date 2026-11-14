"""Checks for evidence-backed page summaries."""

import json

from budgetlab.ui.presentation import artifact_preview, event_card, load_matrix, trajectory_rows


def test_event_card_uses_event_evidence():
    card = event_card(
        {
            "seq": 2,
            "event_type": "protocol_accepted",
            "details": {"approved_features": 19, "excluded_features": ["duration"]},
        }
    )
    assert card["stage"] == "方案"
    assert "duration" in card["note"]
    assert event_card({"event_type": "budget_reserved"}) is None


def test_matrix_prefers_formal_and_trajectory_uses_saved_values(tmp_path):
    dev = tmp_path / "dev-1"
    dev.mkdir()
    (dev / "aggregate.json").write_text(json.dumps([{"system": "random_search"}]))
    assert load_matrix(tmp_path)[2] is False
    formal = tmp_path / "final-1"
    formal.mkdir()
    (formal / "aggregate.json").write_text(json.dumps([{"system": "budgetlab"}]))
    assert load_matrix(tmp_path)[2] is True
    rows = trajectory_rows({"trajectory": [{"best_score_after": 0.71, "llm_tokens_so_far": 0}]})
    assert rows == [{"实验": 1, "最优分": 0.71, "累计 Token": 0, "累计秒数": 0}]


def test_artifact_preview_shows_score_and_rejects_paths_outside_run(tmp_path):
    run = tmp_path / "run"
    experiments = run / "experiments"
    experiments.mkdir(parents=True)
    (experiments / "baseline.json").write_text(
        json.dumps(
            {"spec": {"model": {"family": "logistic_regression"}}, "result": {"mean_score": 0.641}}
        ),
        encoding="utf-8",
    )
    card = {"artifact": "experiments/baseline.json"}
    assert artifact_preview(run, card) == ["模型：logistic_regression", "开发集分数：0.641"]
    assert artifact_preview(run, {"artifact": "../outside.json"}) == []


def test_scripted_proposal_card_shows_both_hypotheses(tmp_path):
    proposal = tmp_path / "llm" / "proposer-r01.output.json"
    proposal.parent.mkdir()
    proposal.write_text(
        json.dumps(
            {
                "candidates": [
                    {"candidate_id": "s1", "hypothesis": {"statement": "Try balanced weights"}},
                    {"candidate_id": "s2", "hypothesis": {"statement": "Try a forest"}},
                ]
            }
        ),
        encoding="utf-8",
    )
    card = event_card(
        {
            "seq": 42,
            "event_type": "llm_call_completed",
            "artifact_ref": "llm/proposer-r01.output.json",
            "details": {"role": "proposer", "source": "scripted"},
        }
    )
    assert "0 Token" in card["note"]
    assert artifact_preview(tmp_path, card) == ["s1：Try balanced weights", "s2：Try a forest"]
