"""Lesson bank: strict snapshots, program-only extraction, deterministic matching, loop wiring."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from budgetlab.contracts import spec_hash, stable_hash
from budgetlab.controller import run_research
from budgetlab.ledger import atomic_write_json
from budgetlab.memory import (
    EMPTY_SNAPSHOT_HASH,
    extract_run,
    load_snapshot,
    match_lessons,
    snapshot_hash,
    write_snapshot,
)
from budgetlab.memory.extract import action_key, spec_diff
from budgetlab.schemas import ForestSpec, PreprocessingSpec, SentinelToMissing
from budgetlab.search import baseline_spec

BASE = baseline_spec()
FOREST = BASE.model_copy(
    update={
        "model": ForestSpec(family="random_forest", class_weight="balanced", min_samples_leaf=5),
        "preprocessing": PreprocessingSpec(),
    }
)


def _check(experiment_id: str, comparator: str, delta: float, status: str) -> dict:
    return {
        "experiment_id": experiment_id,
        "execution_status": "ok",
        "policy_status": status,
        "mean_paired_delta": delta,
        "comparator_experiment_id": comparator,
        "evidence_refs": [f"experiments/{experiment_id}.json"],
        "computed_by": "evaluator",
    }


def _payload(experiment_id: str, origin: str, spec, check=None, hypothesis_check=None) -> dict:
    return {
        "experiment_id": experiment_id,
        "origin": origin,
        "spec": spec.model_dump(mode="json"),
        "result": {"status": "ok"},
        "vs_baseline": check,
        "hypothesis_check": hypothesis_check,
    }


def _fake_run(root: Path, name: str, *, rows: int = 30000, positive_rate: float = 0.11) -> Path:
    """A finished run directory holding only the development artifacts extraction may read."""
    run_dir = root / name
    atomic_write_json(
        run_dir / "contract.json",
        {
            "task_id": "source_task",
            "primary_metric": "f1_macro",
            "decision_policy": {"min_effect": 0.002},
        },
    )
    atomic_write_json(
        run_dir / "eda.json",
        {"rows": rows, "positive_rate": positive_rate, "columns": []},
    )
    sentinel = FOREST.model_copy(
        update={
            "feature_actions": (
                SentinelToMissing(kind="sentinel_to_missing", columns=("pdays",), value=999),
            )
        }
    )
    experiments = {
        "baseline": _payload("baseline", "baseline", BASE),
        "tool-01": _payload(
            "tool-01", "tool_search", FOREST, _check("tool-01", "baseline", 0.05, "candidate_pass")
        ),
        "r01-c1": _payload(
            "r01-c1",
            "proposer",
            sentinel,
            _check("r01-c1", "baseline", 0.051, "candidate_pass"),
            _check("r01-c1", "tool-01", 0.001, "not_met"),
        ),
        "r01-c2": _payload(
            "r01-c2", "proposer", BASE, _check("r01-c2", "baseline", 0.0, "invalid")
        ),
    }
    for experiment_id, payload in experiments.items():
        atomic_write_json(run_dir / "experiments" / f"{experiment_id}.json", payload)
    atomic_write_json(
        run_dir / "confirmation.json",
        {
            **_check("tool-01", "baseline", 0.048, "confirmed_pass"),
            "comparator_experiment_id": None,
        },
    )
    atomic_write_json(run_dir / "summary.json", {"run_id": name})
    return run_dir


def _lesson(lesson_id: str, *, status: str = "candidate", support: int = 1, delta: float = 0.01):
    observation = {
        "task_id": "source_task",
        "run_id": "run-a",
        "experiment_id": "tool-01",
        "comparator": "baseline",
        "metric": "f1_macro",
        "delta": delta,
        "min_effect": 0.002,
        "verdict": "candidate_pass",
    }
    parts = spec_diff(FOREST.model_dump(mode="json"), BASE.model_dump(mode="json"))
    return {
        "lesson_id": lesson_id,
        "version": 1,
        "action_key": action_key(parts),
        "conditions": {
            "primary_metric": "f1_macro",
            "rows_range": [100, 1000],
            "minority_rate_range": [0.35, 0.5],
            "requires_families": ["random_forest"],
            "requires_column_kinds": [],
            "source_columns": [],
            "source_task_ids": ["source_task"],
        },
        "action": {
            "kind": "combined",
            "scope": "single_comparison",
            "parts": parts,
            "summary": "random forest instead of logistic regression",
            "spec": FOREST.model_dump(mode="json"),
            "spec_hash": spec_hash(FOREST),
        },
        "observed_effect": {
            "metric": "f1_macro",
            "delta": delta,
            "comparator": "baseline",
            "run_id": "run-a",
            "experiment_ids": ["tool-01"],
            "min_effect": 0.002,
        },
        "support": support,
        "counterexamples": [],
        "evidence": [observation] * support,
        "status": status,
        "limitations": [],
    }


PROFILE = {
    "rows": 455,
    "positive_rate": 0.63,
    "columns": [{"name": "a", "availability": "available", "kind": "numeric"}],
}


def test_snapshot_roundtrip_hash_is_order_free_and_immutable(tmp_path) -> None:
    lessons = [_lesson("L-b"), _lesson("L-a")]
    path = tmp_path / "snap.json"
    digest = write_snapshot(path, lessons)
    assert digest == snapshot_hash(list(reversed(lessons)))
    assert [lesson["lesson_id"] for lesson in load_snapshot(path)] == ["L-a", "L-b"]
    with pytest.raises(FileExistsError):
        write_snapshot(path, lessons)
    assert snapshot_hash([]) == EMPTY_SNAPSHOT_HASH == stable_hash([])


def test_invalid_lessons_and_corrupt_json_are_rejected(tmp_path) -> None:
    bad = _lesson("L-a")
    bad["surprise"] = 1
    with pytest.raises(ValueError, match="invalid lesson"):
        snapshot_hash([bad])
    missing = _lesson("L-a")
    del missing["observed_effect"]
    with pytest.raises(ValueError, match="invalid lesson"):
        snapshot_hash([missing])
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_snapshot(corrupt)
    with pytest.raises(FileNotFoundError):
        load_snapshot(tmp_path / "absent.json")


def test_matching_excludes_deprecated_and_incompatible_and_caps_at_three() -> None:
    lessons = [
        _lesson("L-1", delta=0.01),
        _lesson("L-2", delta=0.03),
        _lesson("L-3", status="supported_in_sources", delta=0.005),
        _lesson("L-4", support=3, delta=0.002),
        _lesson("L-dep", status="deprecated", delta=0.5),
    ]
    far = _lesson("L-far", delta=0.9)
    far["conditions"]["rows_range"] = [10_000, 50_000]
    lessons.append(far)
    families = ("logistic_regression", "random_forest")
    matched = match_lessons(
        PROFILE, {}, lessons, primary_metric="f1_macro", allowed_families=families
    )
    assert [lesson["lesson_id"] for lesson in matched] == ["L-3", "L-4", "L-2"]
    assert matched == match_lessons(
        PROFILE, {}, list(reversed(lessons)), primary_metric="f1_macro", allowed_families=families
    )
    assert match_lessons(PROFILE, {}, lessons, allowed_families=("logistic_regression",)) == []
    assert match_lessons(PROFILE, {}, lessons, primary_metric="roc_auc") == []
    assert match_lessons(PROFILE, {}, []) == []


def test_extraction_uses_program_verdicts_only(tmp_path) -> None:
    run_dir = _fake_run(tmp_path, "run-a")
    draft = extract_run(run_dir)
    assert draft["observations"] == 3  # the invalid verdict is ignored
    by_scope = {lesson["action"]["scope"]: lesson for lesson in draft["lessons"]}
    recipe = by_scope["confirmed_recipe"]
    assert recipe["status"] == "supported_in_sources"
    assert recipe["support"] == 2  # exploration pass + confirmation, both vs baseline
    assert recipe["observed_effect"]["delta"] == pytest.approx(0.048)
    assert recipe["conditions"]["minority_rate_range"] == [0.0, 0.35]
    assert recipe["conditions"]["rows_range"] == [6000, 150000]
    # r01-c1 only added a sentinel fix vs tool-01 and missed min_effect: no positive lesson.
    sentinel_key = action_key(
        spec_diff(
            json.loads((run_dir / "experiments" / "r01-c1.json").read_text())["spec"],
            FOREST.model_dump(mode="json"),
        )
    )
    assert all(lesson["action_key"] != sentinel_key for lesson in draft["lessons"])
    known = {path.stem for path in (run_dir / "experiments").glob("*.json")}
    for lesson in draft["lessons"]:
        assert set(lesson["observed_effect"]["experiment_ids"]) <= known


def test_disabled_memory_leaves_the_run_unchanged(tmp_path, data_root, smoke_config) -> None:
    summary = run_research(smoke_config, "budgetlab", tmp_path / "runs", data_root)
    run_dir = tmp_path / "runs" / summary["run_id"]
    contract = json.loads((run_dir / "contract.json").read_text(encoding="utf-8"))
    assert contract["memory_snapshot_hash"] == stable_hash([])
    assert "memory" not in summary
    assert not (run_dir / "memory_draft.json").exists()
    context = json.loads((run_dir / "llm" / "proposer-r01.context.json").read_text())
    assert "lessons" not in context


def test_enabled_memory_matches_cites_and_records(tmp_path, data_root, smoke_config) -> None:
    snapshot_path = tmp_path / "snap.json"
    digest = write_snapshot(snapshot_path, [_lesson("L-forest", delta=0.02)])
    before = snapshot_path.read_text(encoding="utf-8")
    smoke_config["memory"] = {"enabled": True, "snapshot": str(snapshot_path)}
    summary = run_research(smoke_config, "budgetlab", tmp_path / "runs", data_root)
    run_dir = tmp_path / "runs" / summary["run_id"]

    contract = json.loads((run_dir / "contract.json").read_text(encoding="utf-8"))
    assert contract["memory_snapshot_hash"] == digest
    run_config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
    assert run_config["memory"]["matched_lesson_ids"] == ["L-forest"]
    assert run_config["memory"]["snapshot_hash"] == digest
    context = json.loads((run_dir / "llm" / "proposer-r01.context.json").read_text())
    assert [lesson["lesson_id"] for lesson in context["lessons"]] == ["L-forest"]
    assert "lesson:L-forest" in context["valid_evidence_refs"]

    round_one = json.loads((run_dir / "rounds" / "round-01.json").read_text(encoding="utf-8"))
    refs = [c["hypothesis"]["evidence_refs"] for c in round_one["proposal"]["candidates"]]
    assert any("lesson:L-forest" in r for r in refs)
    usage = json.loads((run_dir / "memory_usage.json").read_text(encoding="utf-8"))
    assert usage["retrieved"] == 1 and usage["cited"] == 1 and usage["tested"] == 1
    assert summary["memory"]["matched_lesson_ids"] == ["L-forest"]
    assert (run_dir / "memory_draft.json").exists()
    events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
    assert "memory_matched" in events and "memory_usage_written" in events
    assert snapshot_path.read_text(encoding="utf-8") == before  # read-only during runs


def test_missing_snapshot_fails_before_creating_a_run(tmp_path, data_root, smoke_config) -> None:
    smoke_config["memory"] = {"enabled": True, "snapshot": str(tmp_path / "absent.json")}
    with pytest.raises(FileNotFoundError):
        run_research(smoke_config, "budgetlab", tmp_path / "runs", data_root)
    assert not (tmp_path / "runs").exists() or not any((tmp_path / "runs").iterdir())
    smoke_config["memory"] = {"enabled": True, "update_after_run": True}
    with pytest.raises(ValueError, match="unknown memory config keys"):
        run_research(smoke_config, "budgetlab", tmp_path / "runs", data_root)
