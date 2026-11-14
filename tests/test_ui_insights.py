"""Evidence checks for the research workspace panels."""

import json

from budgetlab.ui.insights import (
    branch_activity,
    branch_tree,
    cycle_status,
    experiment_label,
    experiment_rows,
    selection_reason,
    token_ledger,
)


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
    assert "初始方案" in tree["name"]
    assert "0.600" in tree["value"]
    assert {node["id"] for node in tree["children"]} == {"c1", "c2"}
    assert (
        next(node for node in tree["children"] if node["id"] == "c1")["itemStyle"]["color"]
        == "#16A34A"
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


def _event(kind, experiment_id, purpose="exploration"):
    return {
        "event_type": kind,
        "action_id": f"train:{experiment_id}",
        "details": {"purpose": purpose},
    }


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _nodes(tree):
    result = {tree["id"]: tree}
    for child in tree["children"]:
        result.update(_nodes(child))
    return result


def test_live_attempt_exists_before_result_and_keeps_its_hypothesis_parent(tmp_path):
    _write(
        tmp_path / "llm/proposer-r01.output.json",
        {
            "candidates": [
                {
                    "candidate_id": "c1",
                    "hypothesis": {
                        "comparator_experiment_id": "baseline",
                        "statement": "Try a different model.",
                    },
                }
            ]
        },
    )
    events = [
        _event("experiment_started", "baseline", "initial_baseline"),
        _event("experiment_completed", "baseline"),
        _event("experiment_started", "tool-01"),
        _event("experiment_completed", "tool-01"),
        {
            "event_type": "evaluation_recorded",
            "action_id": "train:tool-01",
            "details": {"new_best": True},
        },
        {
            "event_type": "candidate_selected",
            "details": {"candidate_id": "c1", "experiment_id": "r01-c1"},
        },
        _event("experiment_started", "r01-c1"),
    ]
    rows = experiment_rows(tmp_path, {}, events)
    assert [row["id"] for row in rows] == ["baseline", "tool-01", "r01-c1"]
    assert rows[-1]["score"] is None  # no invented result for a running experiment
    assert rows[-1]["parent"] == "baseline"  # comparator, not current best
    assert rows[-1]["hypothesis"] == "Try a different model."
    assert branch_activity(tmp_path, events, rows) == ("r01-c1", "正在执行")


def test_execution_highlight_moves_to_new_sibling_and_extinguishes_on_finish(tmp_path):
    rows = [
        {"id": "baseline"},
        {"id": "r01-c1", "parent": "baseline"},
        {"id": "r01-c2", "parent": "baseline"},
    ]
    events = [_event("experiment_started", "r01-c1")]
    active, label = branch_activity(tmp_path, events, rows)
    first = _nodes(branch_tree(rows, None, active, label))
    assert first["r01-c1"]["lineStyle"]["color"] == "#2563EB"
    assert first["r01-c2"]["lineStyle"]["color"] != "#2563EB"
    events += [
        _event("experiment_completed", "r01-c1"),
        _event("experiment_started", "r01-c2"),
    ]
    active, label = branch_activity(tmp_path, events, rows)
    second = _nodes(branch_tree(rows, None, active, label))
    assert "正在执行" in second["r01-c2"]["name"]
    assert second["r01-c2"]["lineStyle"]["color"] == "#2563EB"
    assert second["r01-c1"]["lineStyle"]["color"] != "#2563EB"
    assert "正在执行" not in second["r01-c1"]["name"]
    events.append(_event("experiment_completed", "r01-c2"))
    assert branch_activity(tmp_path, events, rows) == (None, "")
    # A different run has its own empty event history, not the previous run's focus.
    assert branch_activity(tmp_path, [], rows) == (None, "")


def test_failed_or_stopped_runs_cannot_keep_an_active_path(tmp_path):
    rows = [{"id": "baseline"}]
    events = [_event("experiment_started", "baseline", "initial_baseline")]
    assert branch_activity(tmp_path, events, rows, running=False) == (None, "")
    assert branch_activity(tmp_path, events, rows, finished=True) == (None, "")
    for kind in ("experiment_failed", "run_failed", "run_terminal", "delivery_frozen"):
        assert branch_activity(tmp_path, [*events, _event(kind, "baseline")], rows) == (None, "")


def test_unrelated_completion_does_not_turn_off_the_active_experiment(tmp_path):
    rows = [{"id": "r01-c2"}]
    events = [
        _event("experiment_started", "r01-c2"),
        _event("experiment_completed", "r01-c1"),
    ]
    assert branch_activity(tmp_path, events, rows)[0] == "r01-c2"


def test_final_path_is_green_and_unrelated_branches_stay_dim():
    # Parents can occur after their children in legacy/alphabetically sorted evidence.
    rows = [
        {"id": "baseline"},
        {"id": "r01-c1", "parent": "tool-01"},
        {"id": "r01-c2", "parent": "tool-01"},
        {"id": "tool-01", "parent": "baseline"},
    ]
    nodes = _nodes(branch_tree(rows, "r01-c2"))
    for node_id in ("baseline", "tool-01", "r01-c2"):
        assert nodes[node_id]["itemStyle"]["borderColor"] == "#16A34A"
    assert nodes["r01-c2"]["lineStyle"]["color"] == "#16A34A"
    assert nodes["r01-c1"]["lineStyle"]["color"] != "#16A34A"
    assert "最终采用" in nodes["r01-c2"]["name"]
    assert not any("正在执行" in node["name"] for node in nodes.values())


def test_confirmation_and_refit_highlight_the_matching_saved_spec(tmp_path):
    rows = [{"id": "baseline"}, {"id": "r01-c1", "parent": "baseline"}]
    _write(tmp_path / "experiments/baseline.json", {"spec": {"model": "baseline"}})
    _write(tmp_path / "experiments/r01-c1.json", {"spec": {"model": "candidate"}})
    for experiment_id, purpose in (
        ("confirm-candidate-137", "confirmation_candidate"),
        ("final-refit", "final_refit"),
    ):
        _write(tmp_path / f"work/{experiment_id}.job.json", {"spec": {"model": "candidate"}})
        events = [_event("experiment_started", experiment_id, purpose)]
        assert branch_activity(tmp_path, events, rows)[0] == "r01-c1"
    for purpose in ("calibration", "confirmation_baseline"):
        events = [_event("experiment_started", "special-baseline-137", purpose)]
        assert branch_activity(tmp_path, events, rows)[0] == "baseline"


def test_proposal_activity_uses_recorded_context_and_closes_on_completion(tmp_path):
    rows = [{"id": "baseline"}, {"id": "tool-01", "parent": "baseline"}]
    _write(tmp_path / "llm/proposer-r01.context.json", {"best_id": "tool-01"})
    events = [{"event_type": "llm_call_started", "action_id": "llm:proposer:r01"}]
    assert branch_activity(tmp_path, events, rows) == ("tool-01", "正在提出假设")
    events.append({"event_type": "llm_call_completed", "action_id": "llm:proposer:r01"})
    assert branch_activity(tmp_path, events, rows) == (None, "")


def test_completed_raw_result_is_visible_before_controller_enrichment(tmp_path):
    _write(
        tmp_path / "experiments/baseline.json",
        {"result": {"experiment_id": "baseline", "mean_score": 0.6}},
    )
    events = [_event("experiment_started", "baseline", "initial_baseline")]
    rows = experiment_rows(tmp_path, {}, events)
    assert rows[0]["id"] == "baseline"
    assert rows[0]["score"] == 0.6
    assert rows[0]["origin"] == "baseline"


def test_cyclic_parent_evidence_still_produces_a_finite_tree():
    rows = [{"id": "a", "parent": "b"}, {"id": "b", "parent": "a"}]
    nodes = _nodes(branch_tree(rows, None, "a"))
    assert set(nodes) == {"root", "a", "b"}


def test_readable_names_keep_round_and_candidate_order():
    assert experiment_label({"id": "baseline"}) == "初始方案"
    assert experiment_label({"id": "r01-c2"}) == "第1轮·方案2"
    assert experiment_label({"id": "r12-c1"}) == "第12轮·方案1"


def test_search_scheme_numbers_follow_search_order_not_engine_counter(tmp_path):
    rows = experiment_rows(
        tmp_path,
        {
            "experiments": [
                {"id": "baseline", "origin": "baseline"},
                {"id": "tool-01", "origin": "tool_search"},
                {"id": "r01-c1", "origin": "proposer"},
                {"id": "tool-09", "origin": "tool_search"},
            ]
        },
    )
    assert rows[-1]["label"] == "自动搜索·方案2"
    assert rows[-1]["id"] == "tool-09"


def test_successful_unselected_candidate_explains_lower_score():
    rows = [
        {"id": "baseline", "score": 0.6},
        {"id": "r01-c1", "score": 0.7, "verdict": "candidate_pass", "parent": "baseline"},
        {"id": "r01-c2", "score": 0.75, "verdict": "candidate_pass", "parent": "baseline"},
    ]
    summary = {"finalist_id": "r01-c2", "confirmation_status": "confirmed_pass"}
    reason = selection_reason(rows[1], "r01-c2", rows, summary)
    assert "有足够提升" in reason and "分数低于" in reason
    assert "第1轮·方案2" in reason and "0.7500" in reason
    nodes = _nodes(branch_tree(rows, "r01-c2", summary=summary))
    assert "已改善·未选" in nodes["r01-c1"]["name"]
    assert "r01-c1" not in nodes["r01-c1"]["name"]
    assert "失败" not in nodes["r01-c1"]["value"]
    assert nodes["r01-c2"]["symbol"] == "diamond"
    assert nodes["baseline"]["symbol"] == "circle"
    assert nodes["baseline"]["itemStyle"]["color"] != nodes["r01-c2"]["itemStyle"]["color"]


def test_comparison_ancestor_is_not_labelled_as_final_selection():
    rows = [
        {"id": "baseline"},
        {"id": "r01-c1", "parent": "baseline", "verdict": "candidate_pass"},
        {"id": "r02-c1", "parent": "r01-c1", "verdict": "candidate_pass"},
    ]
    nodes = _nodes(branch_tree(rows, "r02-c1"))
    assert "对照步骤" in nodes["r01-c1"]["name"]
    assert "最终采用" not in nodes["r01-c1"]["name"]
    assert "继续探索" not in nodes["baseline"]["name"]


def test_failed_confirmation_does_not_claim_candidate_was_outscored():
    rows = [
        {"id": "baseline", "score": 0.6},
        {"id": "r01-c1", "score": 0.75, "verdict": "candidate_pass"},
    ]
    summary = {"finalist_id": "r01-c1", "confirmation_status": "not_met"}
    reason = selection_reason(rows[1], "baseline", rows, summary)
    assert "未通过新切分复核" in reason
    assert "分数低于" not in reason
    assert "保留初始方案" in selection_reason(rows[0], "baseline", rows, summary)
    assert "复核未通过" in _nodes(branch_tree(rows, "baseline", summary=summary))["r01-c1"]["name"]


def test_score_ties_use_recorded_time_without_inventing_reason():
    rows = [
        {"id": "r01-c1", "score": 0.7, "seconds": 15, "verdict": "candidate_pass"},
        {"id": "r01-c2", "score": 0.7, "seconds": 10, "verdict": "candidate_pass"},
    ]
    summary = {"finalist_id": "r01-c2"}
    assert "耗时更短" in selection_reason(rows[0], "r01-c2", rows, summary)
    rows[0].pop("seconds")
    assert "耗时更短" not in selection_reason(rows[0], "r01-c2", rows, summary)
    assert "分数低于" not in selection_reason(rows[0], "r01-c2", rows, summary)


def test_live_eligible_candidate_is_not_prematurely_rejected():
    row = {"id": "r01-c1", "verdict": "candidate_pass", "score": 0.7}
    node = branch_tree([row], None)
    assert "有提升·候选" in node["name"]
    assert "未入选" not in node["name"]
    assert "最终方案尚未确定" in node["value"]
