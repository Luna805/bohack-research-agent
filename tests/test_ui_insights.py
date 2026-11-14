"""Evidence checks for the research workspace panels."""

import json

from budgetlab.ui.insights import branch_tree, cycle_status, experiment_rows, token_ledger


def test_token_ledger_keeps_unknown_usage_separate(tmp_path):
    (tmp_path / "budget.json").write_text(
        json.dumps(
            {
                "limits": {"max_llm_tokens": 5000},
                "used": {"llm_tokens": 120},
                "unknown": {"llm_tokens": 30},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "llm_calls.jsonl").write_text(
        json.dumps(
            {
                "role": "proposer",
                "round": 1,
                "source": "llm",
                "usage": {"llm_tokens": 120},
                "unknown": {"llm_tokens": 30},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    ledger = token_ledger(tmp_path)
    assert (ledger["used"], ledger["unknown"], ledger["limit"]) == (120, 30, 5000)
    assert ledger["by_role"]["proposer"] == {"tokens": 120, "unknown": 30, "calls": 1}


def test_branch_tree_keeps_sibling_attempts_and_saved_scores(tmp_path):
    experiments = tmp_path / "experiments"
    experiments.mkdir()
    for experiment_id, parent in (("baseline", None), ("c1", "baseline"), ("c2", "baseline")):
        (experiments / f"{experiment_id}.json").write_text(
            json.dumps({"previous_best_id": parent}), encoding="utf-8"
        )
    rows = experiment_rows(
        tmp_path,
        {
            "experiments": [
                {"id": "baseline", "mean_score": 0.60, "origin": "baseline"},
                {"id": "c1", "mean_score": 0.64, "origin": "proposer"},
                {"id": "c2", "mean_score": 0.63, "origin": "proposer"},
            ]
        },
    )
    tree = branch_tree(rows, "c1")
    assert "baseline" in tree["name"]
    assert "0.600" in tree["value"]
    assert {node["name"].split(" · ")[-1].split("\n")[0] for node in tree["children"]} == {
        "c1",
        "c2",
    }
    assert (
        next(node for node in tree["children"] if "c1" in node["name"])["itemStyle"]["color"]
        == "#B8FF65"
    )


def test_cycle_status_counts_only_recorded_steps():
    stages = cycle_status(
        [
            {"event_type": "protocol_accepted"},
            {"event_type": "profile_written"},
            {"event_type": "llm_call_completed", "details": {"role": "proposer"}},
            {"event_type": "experiment_completed"},
            {"event_type": "evaluation_recorded"},
        ]
    )
    assert dict(stages)["验证"] == 1
    assert dict(stages)["修正再探索"] == 0
