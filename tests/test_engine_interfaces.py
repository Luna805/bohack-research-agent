from __future__ import annotations

import json

from budgetlab.controller import replay_run, reproduce_run, run_research


def test_run_artifacts_summary_and_replay_contract(tmp_path, data_root, smoke_config) -> None:
    smoke_config["random_search_experiments"] = 1
    summary = run_research(smoke_config, "random_search", tmp_path / "runs", data_root)
    run_dir = tmp_path / "runs" / summary["run_id"]

    assert summary["summary_version"] == 1
    assert json.loads((run_dir / "summary.json").read_text(encoding="utf-8")) == summary
    for relative_path in (
        "summary.json",
        "report.md",
        "events.jsonl",
        "run_config.json",
        "protocol.json",
        "contract.json",
        "calibration.json",
        "budget.json",
        "delivery/frozen_delivery.json",
        "delivery/model.joblib",
    ):
        assert (run_dir / relative_path).is_file(), relative_path

    events = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert events[-1]["event_type"] == "run_terminal"

    assert {"system", "proposal_source", "stop_reason", "budget"}.issubset(summary)
    assert summary["system"] == "random_search"
    assert summary["proposal_source"] == "none"
    assert summary["stop_reason"]

    budget_before = (run_dir / "budget.json").read_bytes()
    replay = replay_run(summary["run_id"], tmp_path / "runs")
    assert replay["fit_attempts_started_by_replay"] == 0
    assert replay["llm_requests_started_by_replay"] == 0
    assert budget_before == (run_dir / "budget.json").read_bytes()

    reproduced = reproduce_run(summary["run_id"], tmp_path / "runs")
    delivery = json.loads(
        (run_dir / "delivery" / "frozen_delivery.json").read_text(encoding="utf-8")
    )
    assert reproduced["dataset_hash"] == delivery["dataset_hash"]
    assert reproduced["spec_hash"] == delivery["delivered_spec_hash"]
