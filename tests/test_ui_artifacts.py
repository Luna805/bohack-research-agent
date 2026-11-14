"""Evidence links under QA answers point only at files that exist inside one run."""

import json

from budgetlab.ui.artifacts import (
    CURVE,
    FINAL,
    INTERMEDIATE,
    answer_links,
    curve_rows,
    links_markdown,
    resolve_artifact,
)

RUN_ID = "20261114T000000Z-budgetlab-abc123"


def make_run(tmp_path):
    run = tmp_path / RUN_ID
    for folder in ("experiments", "evaluations", "logs", "rounds", "llm", "delivery"):
        (run / folder).mkdir(parents=True)
    summary = {
        "primary_metric": "f1_macro",
        "baseline_score": 0.64,
        "delivered_experiment_id": "r05-c1",
        "experiments": [
            {"id": "baseline", "mean_score": 0.64},
            {"id": "r05-c1", "mean_score": 0.71},
        ],
        "trajectory": [
            {"experiment_id": "baseline", "best_score_after": 0.64, "origin": "baseline"},
            {"experiment_id": "r05-c1", "best_score_after": 0.71, "round": 5},
        ],
    }
    (run / "summary.json").write_text(json.dumps(summary))
    for name in ("r05-c1", "r03-c1"):
        (run / "experiments" / f"{name}.json").write_text("{}")
        (run / "evaluations" / f"{name}.json").write_text("{}")
        (run / "logs" / f"{name}.stdout.log").write_text("ok")
        (run / "logs" / f"{name}.stderr.log").write_text("")  # empty: not linked
    (run / "rounds" / "round-05.json").write_text("{}")
    (run / "llm" / "proposer-r05.output.json").write_text("{}")
    (run / "llm" / "proposer-r05.context.json").write_text("{}")
    call = {
        "action_id": "llm:proposer:r05",
        "role": "proposer",
        "round": 5,
        "output_ref": "llm/proposer-r05.output.json",
        "context_ref": "llm/proposer-r05.context.json",
    }
    (run / "llm_calls.jsonl").write_text(json.dumps(call) + "\n")
    (run / "confirmation.json").write_text("{}")
    (run / "report.md").write_text("# report")
    (run / "delivery" / "model.joblib").write_bytes(b"binary")
    return run


def test_links_cover_cited_named_and_delivered_files_that_exist(tmp_path):
    make_run(tmp_path)
    evidence = [
        {"kind": "experiment", "ref_id": "r05-c1"},
        {"kind": "round", "ref_id": "5"},
        {"kind": "llm_call", "ref_id": "llm:proposer:r05"},
        {"kind": "experiment", "ref_id": "r99-c9"},  # cited but missing: no link
    ]
    links = answer_links(tmp_path, RUN_ID, evidence, "r05-c1 胜过 r03-c1 与 tool-07")
    paths = [link.path for link in links]
    assert paths[:3] == [
        "experiments/r05-c1.json",
        "evaluations/r05-c1.json",
        "logs/r05-c1.stdout.log",
    ]
    assert "experiments/r03-c1.json" in paths  # named in the answer text
    assert "rounds/round-05.json" in paths
    assert "llm/proposer-r05.output.json" in paths and "llm/proposer-r05.context.json" in paths
    assert not any("r99-c9" in path or "tool-07" in path for path in paths)
    assert not any(path.endswith(".stderr.log") for path in paths)
    assert CURVE in paths
    final = [link.path for link in links if link.group == FINAL]
    assert final == ["summary.json", "confirmation.json", "report.md"]  # missing files skipped
    assert len(paths) == len(set(paths))
    assert links[0].group == INTERMEDIATE and "交付模型" in links[0].item
    text = links_markdown(RUN_ID, links)
    assert f"(?run={RUN_ID}&file=experiments/r05-c1.json" in text
    assert f"(?run={RUN_ID}&file=curve" in text


def test_viewer_paths_stay_inside_one_run_and_text_files(tmp_path):
    run = make_run(tmp_path)
    (tmp_path / "secret.json").write_text("{}")
    assert resolve_artifact(tmp_path, RUN_ID, "summary.json") == (run / "summary.json").resolve()
    assert resolve_artifact(tmp_path, RUN_ID, "../secret.json") is None
    assert resolve_artifact(tmp_path, "..", "secret.json") is None
    assert resolve_artifact(tmp_path, RUN_ID, "delivery/model.joblib") is None
    assert resolve_artifact(tmp_path, RUN_ID, "missing.json") is None
    assert answer_links(tmp_path, "../" + RUN_ID, [], "") == []


def test_curve_rows_use_saved_scores(tmp_path):
    run = make_run(tmp_path)
    rows = curve_rows(json.loads((run / "summary.json").read_text()))
    assert [row["实验"] for row in rows] == ["baseline", "r05-c1"]
    assert rows[1]["本实验分数"] == 0.71 and rows[1]["历史最优"] == 0.71
