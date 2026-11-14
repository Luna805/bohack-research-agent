from __future__ import annotations

import csv
import json

import pytest
import yaml

from budgetlab import benchmark
from budgetlab.benchmark import COLUMNS, MatrixError, load_matrix, plan_slots, run_matrix


def _write_matrix(tmp_path, smoke_config, **matrix_overrides):
    task_config = tmp_path / "task.yaml"
    task_config.write_text(yaml.safe_dump(smoke_config), encoding="utf-8")
    matrix = {
        "kind": "dev",
        "tasks": [{"name": "breast_cancer", "config": "task.yaml"}],
        "systems": ["random_search", "budgetlab_no_schedule"],
        "repeats": 1,
        "proposer": "scripted",
        "overrides": {"random_search_experiments": 2, "loop": {"max_rounds": 1}},
    }
    matrix.update(matrix_overrides)
    path = tmp_path / "matrix.yaml"
    path.write_text(yaml.safe_dump(matrix), encoding="utf-8")
    return path, task_config


def _run(tmp_path, data_root, matrix_path, **kwargs):
    return run_matrix(
        matrix_path,
        runs_root=tmp_path / "runs",
        data_root=data_root,
        results_root=tmp_path / "results",
        base_dir=tmp_path,
        log=lambda *_: None,
        **kwargs,
    )


def test_matrix_writes_interface_files(tmp_path, data_root, smoke_config) -> None:
    matrix_path, _ = _write_matrix(tmp_path, smoke_config)
    out_dir = _run(tmp_path, data_root, matrix_path)
    assert out_dir.name.startswith("dev-")
    record = json.loads((out_dir / "matrix.json").read_text(encoding="utf-8"))
    assert record["code_version"]
    assert [slot["system"] for slot in record["slots"]] == [
        "random_search",
        "budgetlab_no_schedule",
    ]
    with (out_dir / "aggregate.csv").open(encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        assert tuple(reader.fieldnames) == COLUMNS
        rows = list(reader)
    assert [row["status"] for row in rows] == ["ok", "ok"]
    for row in rows:
        assert 0 <= float(row["holdout_score"]) <= 1
        run_dir = out_dir / "runs" / row["run_id"]
        assert {path.name for path in run_dir.iterdir()} == {
            "summary.json",
            "final_evaluation.json",
            "report.md",
        }
    assert rows[0]["proposal_source"] == "none"
    assert rows[1]["proposal_source"] == "scripted"
    assert "budgetlab_no_schedule" in (out_dir / "aggregate.md").read_text(encoding="utf-8")


def test_repeats_change_only_the_search_seed(tmp_path, smoke_config) -> None:
    matrix_path, _ = _write_matrix(tmp_path, smoke_config, repeats=2, systems=["budgetlab"])
    slots = plan_slots(load_matrix(matrix_path), tmp_path)
    assert [slot["slot_id"] for slot in slots] == [
        "breast_cancer/r1/budgetlab",
        "breast_cancer/r2/budgetlab",
    ]
    first, second = (slot["config"] for slot in slots)
    assert second["search_seed"] - first["search_seed"] == 1000
    assert first["split_seed"] == second["split_seed"]
    assert first["training_seed"] == second["training_seed"]


def test_resume_skips_finished_slots_and_rejects_changed_configs(
    tmp_path, data_root, smoke_config
) -> None:
    matrix_path, task_config = _write_matrix(tmp_path, smoke_config, systems=["random_search"])
    out_dir = _run(tmp_path, data_root, matrix_path)
    runs_before = sorted((tmp_path / "runs").iterdir())
    _run(tmp_path, data_root, None, resume=out_dir.name)
    assert sorted((tmp_path / "runs").iterdir()) == runs_before
    changed = dict(smoke_config, min_effect_floor=0.01)
    task_config.write_text(yaml.safe_dump(changed), encoding="utf-8")
    with pytest.raises(MatrixError, match="changed"):
        _run(tmp_path, data_root, None, resume=out_dir.name)


def test_failed_slot_is_recorded_and_the_rest_continues(tmp_path, data_root, smoke_config) -> None:
    matrix_path, _ = _write_matrix(tmp_path, smoke_config)

    def factory(slot):
        if slot["system"] == "budgetlab_no_schedule":
            raise RuntimeError("proposer unavailable")
        return None

    out_dir = _run(tmp_path, data_root, matrix_path, proposer_factory=factory)
    rows = {row["system"]: row for row in json.loads((out_dir / "aggregate.json").read_text())}
    assert rows["random_search"]["status"] == "ok"
    assert rows["budgetlab_no_schedule"]["status"] == "error"
    assert "proposer unavailable" in rows["budgetlab_no_schedule"]["error"]


def test_final_matrix_requires_a_clean_checkout(
    tmp_path, data_root, smoke_config, monkeypatch
) -> None:
    matrix_path, _ = _write_matrix(tmp_path, smoke_config, kind="final")
    monkeypatch.setattr(
        benchmark, "git_info", lambda root: {"commit": "a" * 40, "short": "aaaaaaa", "dirty": True}
    )
    with pytest.raises(MatrixError, match="clean git checkout"):
        _run(tmp_path, data_root, matrix_path)
    monkeypatch.setattr(benchmark, "git_info", lambda root: None)
    with pytest.raises(MatrixError, match="clean git checkout"):
        _run(tmp_path, data_root, matrix_path)
    assert not (tmp_path / "results").exists()


def test_unknown_system_is_rejected(tmp_path, smoke_config) -> None:
    matrix_path, _ = _write_matrix(tmp_path, smoke_config, systems=["automl"])
    with pytest.raises(MatrixError, match="unknown systems"):
        load_matrix(matrix_path)


def test_untracked_code_makes_checkout_dirty_but_outputs_do_not(tmp_path) -> None:
    import subprocess

    from budgetlab.provenance import git_info

    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (tmp_path / "a.py").write_text("x = 1\n")
    git("add", "a.py")
    git("commit", "-q", "-m", "init")
    assert git_info(tmp_path)["dirty"] is False
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "aggregate.csv").write_text("a\n")
    (tmp_path / "notes.md").write_text("n\n")
    assert git_info(tmp_path)["dirty"] is False
    (tmp_path / "new_module.py").write_text("y = 2\n")
    info = git_info(tmp_path)
    assert info["dirty"] is True
    assert info["dirty_files"] == ["new_module.py"]


def test_llm_matrix_preflight_catches_zero_budget_and_missing_model(
    tmp_path, smoke_config, monkeypatch
) -> None:
    matrix_path, _ = _write_matrix(tmp_path, smoke_config, proposer="llm", systems=["budgetlab"])
    slots = plan_slots(load_matrix(matrix_path), tmp_path)

    def broken(config, kind):
        raise RuntimeError("LLM model name is not configured")

    monkeypatch.setattr(benchmark, "make_agents", broken)
    problems = benchmark.preflight(slots)
    assert any("must be positive" in problem for problem in problems)
    assert any("model name is not configured" in problem for problem in problems)
    with pytest.raises(MatrixError, match="preflight failed"):
        run_matrix(
            matrix_path,
            runs_root=tmp_path / "runs",
            data_root=tmp_path / "data",
            results_root=tmp_path / "results",
            base_dir=tmp_path,
            log=lambda *_: None,
        )
    assert not (tmp_path / "results").exists()

    monkeypatch.setattr(benchmark, "make_agents", lambda config, kind: (object(), None))
    funded = dict(smoke_config)
    funded["budget"] = dict(smoke_config["budget"], max_llm_requests=10, max_llm_tokens=50_000)
    matrix_path, _ = _write_matrix(tmp_path, funded, proposer="llm", systems=["budgetlab"])
    assert benchmark.preflight(plan_slots(load_matrix(matrix_path), tmp_path)) == []
    scripted_path, _ = _write_matrix(tmp_path, smoke_config)
    assert benchmark.preflight(plan_slots(load_matrix(scripted_path), tmp_path)) == []
