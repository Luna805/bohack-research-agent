from __future__ import annotations

import json

from budgetlab.controller import replay_run, reproduce_run, run_research


def test_scripted_two_round_real_training_refit_reproduce_and_replay(tmp_path) -> None:
    config = {
        "dataset_ref": "sklearn:breast_cancer",
        "cv_folds": 2,
        "split_seed": 42,
        "calibration_split_seeds": [11, 23, 37],
        "confirmation_split_seeds": [137, 2026, 31415],
        "training_seed": 42,
        "search_seed": 2026,
        "search_candidates": 2,
        "min_effect_floor": 0.002,
        "budget": {
            "max_experiments": 20,
            "max_fits": 40,
            "max_total_seconds": 600,
            "experiment_timeout_seconds": 30,
        },
    }
    summary = run_research(config, "scripted_smoke", tmp_path)
    run_id = summary["run_id"]
    run_dir = tmp_path / run_id
    assert (run_dir / "delivery" / "model.joblib").exists()
    assert (run_dir / "report.md").exists()
    assert summary["proposal_source"] == "scripted"
    assert summary["budget"]["used"]["fits"] > 0
    assert summary["budget"]["used"]["llm_requests"] == 0

    second = json.loads((run_dir / "proposals" / "round-2.json").read_text(encoding="utf-8"))
    refs = second["candidates"][0]["hypothesis"]["evidence_refs"]
    assert "evaluations/scripted-r1-c1.json" in refs

    reproduction = reproduce_run(run_id, tmp_path)
    assert reproduction["status"] == "ok"
    assert reproduction["fit_attempts"] == 1

    budget_before = (run_dir / "budget.json").read_text(encoding="utf-8")
    replay = replay_run(run_id, tmp_path)
    budget_after = (run_dir / "budget.json").read_text(encoding="utf-8")
    assert replay["fit_attempts_started_by_replay"] == 0
    assert replay["llm_requests_started_by_replay"] == 0
    assert budget_before == budget_after
