"""Workbench data: confined file listing, experiment status, progress and history."""

import json
from datetime import UTC, datetime

from budgetlab.ui.workbench import (
    describe_spec,
    experiment_table,
    history_rows,
    list_entries,
    progress,
    project_groups,
    round_started_at,
    run_strategy,
    sort_entries,
    strategy_title,
    when_text,
)

RUN_ID = "20261114T091425Z-budgetlab-abc123"


def event(seq, kind, ts, action=None, **details):
    return {
        "seq": seq,
        "event_type": kind,
        "action_id": action,
        "timestamp": f"2026-11-14T09:{ts}+00:00",
        "details": details,
    }


def experiment(base, experiment_id, origin, score, delta, elapsed, round_index=0, spec=None):
    payload = {
        "experiment_id": experiment_id,
        "origin": origin,
        "round": round_index,
        "delta_vs_previous_best": delta,
        "best_score_after": score,
        "elapsed_seconds": elapsed,
        "spec": spec or {"model": {"family": "logistic_regression"}},
        "result": {"status": "ok", "mean_score": score, "duration_seconds": 3.0},
    }
    (base / "experiments" / f"{experiment_id}.json").write_text(json.dumps(payload))


def make_run(tmp_path, *, finished=False):
    base = tmp_path / RUN_ID
    (base / "experiments").mkdir(parents=True)
    (base / "logs").mkdir()
    (base / ".hidden").write_text("x")
    (base / "run_config.json").write_text(json.dumps({"proposal_source": "llm"}))
    (base / "contract.json").write_text(
        json.dumps({"budgets": {"max_experiments": 40}, "decision_policy": {"min_effect": 0.002}})
    )
    (base / "scenario_card.json").write_text(json.dumps({"title": "Bank term-deposit"}))
    experiment(base, "baseline", "baseline", 0.6412, None, 20)
    (base / "experiments" / "calibration-11.json").write_text(json.dumps({"result": {}}))
    experiment(base, "r01-c1", "proposer", 0.7052, 0.0336, 66, 1)
    experiment(base, "r03-c1", "proposer", 0.7102, 0.0004, 174, 3)
    events = [
        event(1, "run_created", "14:25"),
        event(2, "protocol_accepted", "14:26"),
        event(3, "llm_call_started", "17:31", role="proposer"),
        event(4, "experiment_started", "17:40", action="train:r04-c1"),
    ]
    (base / "events.jsonl").write_text("\n".join(json.dumps(item) for item in events) + "\n")
    if finished:
        (base / "summary.json").write_text(
            json.dumps(
                {
                    "delivered_experiment_id": "r03-c1",
                    "delivered_dev_score": 0.7102,
                    "proposal_source": "llm",
                    "task_id": "bank_marketing",
                }
            )
        )
    return base, events


def test_experiment_table_marks_running_new_highs_and_baseline(tmp_path):
    base, events = make_run(tmp_path)
    rows = experiment_table(base, events)
    assert [row["id"] for row in rows] == ["r04-c1", "r03-c1", "r01-c1", "baseline"]
    assert rows[0]["kind"] == "run" and rows[0]["status"] == "训练中"
    assert rows[1]["kind"] == "warn" and "0.002" in rows[1]["status"]  # +0.0004 < min effect
    assert rows[2]["kind"] == "best" and rows[3]["kind"] == "base"
    assert rows[2]["source"] == "LLM 提案" and rows[1]["path"] == "experiments/r03-c1.json"


def test_finished_run_marks_delivery_and_progress(tmp_path):
    base, events = make_run(tmp_path, finished=True)
    rows = experiment_table(base, events)
    assert next(row for row in rows if row["id"] == "r03-c1")["kind"] == "delivered"
    state = progress(base, events)
    assert state["round"] == 3 and state["experiments"] == 3 and state["max_experiments"] == 40
    assert state["best_id"] == "r03-c1" and state["running"] == "r04-c1"
    assert state["stages"][0] == ("规划", True) and state["stages"][-1] == ("修正再探索", False)


def test_list_entries_stays_inside_the_run_and_sorts_folders_first(tmp_path):
    make_run(tmp_path)
    (tmp_path / "outside.json").write_text("{}")
    entries = list_entries(tmp_path, RUN_ID)
    names = [entry["name"] for entry in sort_entries(entries, "name")]
    assert names[:2] == ["experiments/", "logs/"] and ".hidden" not in names
    assert next(entry for entry in entries if entry["name"] == "experiments/")["items"] == 4
    assert list_entries(tmp_path, RUN_ID, "..") is None
    assert list_entries(tmp_path, "../" + RUN_ID) is None
    inner = list_entries(tmp_path, RUN_ID, "experiments")
    assert {entry["path"] for entry in inner} >= {"experiments/baseline.json"}


def test_round_start_history_and_spec_text(tmp_path):
    _, events = make_run(tmp_path, finished=True)
    assert round_started_at(events) is not None
    rows = history_rows(tmp_path, [{"run_id": RUN_ID, "finished": True, "task_id": "x"}])
    assert rows[0]["title"] == "Bank term-deposit" and rows[0]["score"] == "0.7102"
    assert rows[0]["source"] == "LLM"
    text = describe_spec(
        {
            "model": {"family": "random_forest", "n_estimators": 300, "class_weight": "balanced"},
            "feature_actions": [{"kind": "log1p", "columns": ["campaign", "previous"]}],
        }
    )
    assert text == "随机森林 · 300 棵 · 平衡权重；log1p campaign、previous"


def test_project_groups_nest_runs_under_their_task():
    def row(run_id, task_id, hour):
        started = datetime(2026, 11, 14, hour, tzinfo=UTC)
        return {
            "run_id": run_id,
            "task_id": task_id,
            "title": f"card {task_id}",
            "started": started,
        }

    rows = [
        row("c", "breast_cancer", 11),
        row("b", "bank_marketing", 10),
        row("a", "bank_marketing", 9),
    ]
    groups = project_groups(rows, {"bank_marketing": "Bank Marketing", "adult": "Adult Income"})
    assert [g["task_id"] for g in groups] == ["breast_cancer", "bank_marketing", "adult"]
    assert groups[0]["name"] == "card breast_cancer"  # unknown task falls back to the card title
    assert [r["run_id"] for r in groups[1]["runs"]] == ["b", "a"]
    assert groups[2]["runs"] == []  # known projects show up even without runs

    now = datetime(2026, 11, 14, 12, tzinfo=UTC)
    assert when_text(None, now) == ""
    assert ":" in when_text(datetime(2026, 11, 14, 11, 30, tzinfo=UTC), now)
    assert when_text(datetime(2026, 11, 1, 12, tzinfo=UTC), now) == "11月1日"


def test_strategy_title_names_the_delivered_moves(tmp_path):
    forest = {
        "model": {"family": "random_forest", "class_weight": "balanced", "n_estimators": 300},
        "feature_actions": [
            {"kind": "sentinel_to_missing", "columns": ["pdays"], "value": 999},
            {"kind": "missing_indicator", "columns": ["pdays"]},
            {"kind": "log1p", "columns": ["campaign", "previous"]},
        ],
    }
    assert strategy_title(forest) == "平衡随机森林 + pdays 哨兵值处理 + campaign、previous 取对数"
    tuned = {"model": {"family": "hist_gradient_boosting", "learning_rate": 0.05}}
    assert strategy_title(tuned) == "梯度提升树 · 学习率 0.05"
    wide = {
        "model": {"family": "logistic_regression"},
        "feature_actions": [{"kind": "drop", "columns": ["a", "b", "c"]}],
    }
    assert strategy_title(wide) == "逻辑回归 + 去掉 a 等 3 列"

    base = tmp_path / "run"
    (base / "experiments").mkdir(parents=True)
    assert run_strategy(base) == {"title": "", "detail": ""}  # still running: nothing delivered
    (base / "summary.json").write_text(
        json.dumps({"delivered_experiment_id": "baseline", "exploration_best_id": "r02-c2"})
    )
    (base / "experiments" / "baseline.json").write_text(
        json.dumps({"origin": "baseline", "spec": {"model": {"family": "logistic_regression"}}})
    )
    assert run_strategy(base)["title"] == "保留基线：逻辑回归（候选提升不够显著）"
    (base / "summary.json").write_text(json.dumps({"delivered_experiment_id": "r05-c1"}))
    (base / "experiments" / "r05-c1.json").write_text(
        json.dumps({"origin": "proposer", "spec": forest, "hypothesis": "Flag pdays."})
    )
    strategy = run_strategy(base)
    assert strategy["title"].startswith("平衡随机森林")
    assert "交付 r05-c1" in strategy["detail"] and "假设：Flag pdays." in strategy["detail"]
