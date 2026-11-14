from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest
from sklearn.datasets import load_breast_cancer

from budgetlab.controller import run_research
from budgetlab.data import load_development, prepare_task
from budgetlab.evaluation import evaluate_frozen_run
from budgetlab.tasks import csv_task, get_task
from budgetlab.tasks.csv_task import (
    CsvTaskError,
    config_for_upload,
    read_csv_any,
    register_csv_task,
    task_id_for,
    validate_csv_for_task,
)


def _frame() -> pd.DataFrame:
    raw = load_breast_cancer(as_frame=True)
    frame = raw.data.iloc[:, :6].copy()
    frame.columns = [f"f{i}" for i in range(6)]
    rng = np.random.default_rng(0)
    frame["年龄组"] = rng.choice(["青年", "中年", "老年"], size=len(frame))
    frame["patient_id"] = np.arange(len(frame))
    label = np.where(raw.target == 1, "benign", "malignant")
    frame["confirmed_after_surgery"] = label  # leaks the outcome
    frame["diagnosis"] = label
    return frame


def _card(frame: pd.DataFrame, **changes) -> dict:
    fields = []
    for column in frame.columns:
        if column == "diagnosis":
            continue
        availability = {"patient_id": "identifier", "confirmed_after_surgery": "post_outcome"}.get(
            column, "available"
        )
        fields.append({"name": column, "availability": availability, "description": column})
    card = {
        "title": "Tumour diagnosis upload",
        "business_question": "classify a sample before surgery",
        "prediction_time": "before surgery",
        "target": {"column": "diagnosis", "positive_label": "malignant"},
        "primary_metric": "f1_macro",
        "fields": fields,
    }
    card.update(changes)
    return card


def _write(frame: pd.DataFrame, path, **kwargs):
    frame.to_csv(path, index=False, **kwargs)
    return path


def test_gbk_semicolon_csv_is_read(tmp_path) -> None:
    path = _write(_frame(), tmp_path / "upload.csv", sep=";", encoding="gbk")
    frame = read_csv_any(path)
    assert "年龄组" in frame.columns
    assert frame.shape == _frame().shape


def test_uploaded_csv_runs_end_to_end(tmp_path, smoke_config) -> None:
    data_root = tmp_path / "data"
    frame = _frame()
    path = _write(frame, tmp_path / "upload.csv", sep=";", encoding="gbk")
    task_id = register_csv_task(path, _card(frame), data_root)
    assert task_id.startswith("upload-")
    upload_dir = data_root / "uploads" / task_id
    assert {p.name for p in upload_dir.iterdir()} == {"data.csv", "card.yaml", "task.json"}

    task = get_task(task_id)
    assert task.card["prediction_time"] == "before surgery"
    manifest = prepare_task(task_id, data_root)
    assert manifest["development_rows"] + manifest["holdout_rows"] == len(frame)
    bundle = load_development(task_id, data_root)
    assert set(bundle.target.unique()) == {0, 1}
    assert bundle.target.mean() == pytest.approx(
        (frame["diagnosis"] == "malignant").mean(), abs=0.02
    )

    config = config_for_upload(task_id, smoke_config)
    config["loop"] = {"max_rounds": 1, "initial_tool_search": 0, "stagnation_stop": 3}
    summary = run_research(config, "budgetlab_no_schedule", tmp_path / "runs", data_root)
    run_dir = tmp_path / "runs" / summary["run_id"]
    contract = json.loads((run_dir / "contract.json").read_text(encoding="utf-8"))
    approved = set(contract["approved_feature_columns"])
    assert "confirmed_after_surgery" not in approved
    assert "patient_id" not in approved
    assert {"年龄组", "f0"} <= approved
    final = evaluate_frozen_run(summary["run_id"], tmp_path / "runs")
    assert 0 <= final["holdout_score"] <= 1


def test_same_upload_and_card_give_same_id(tmp_path) -> None:
    frame = _frame()
    path = _write(frame, tmp_path / "upload.csv")
    first = register_csv_task(path, _card(frame), tmp_path / "data")
    second = register_csv_task(path, _card(frame), tmp_path / "data")
    other = task_id_for(path.read_bytes(), _card(frame, prediction_time="after surgery"))
    assert first == second
    assert other != first


def test_csv_level_rejections(tmp_path, monkeypatch) -> None:
    frame = _frame()
    multiclass = frame.copy()
    multiclass["diagnosis"] = np.resize(["a", "b", "c"], len(frame))
    reasons = validate_csv_for_task(_write(multiclass, tmp_path / "m.csv"), "diagnosis")
    assert any("二分类" in reason for reason in reasons)

    reasons = validate_csv_for_task(_write(frame, tmp_path / "f.csv"), "no_such_column")
    assert any("找不到目标列" in reason for reason in reasons)

    rare = frame.copy()
    rare["diagnosis"] = "benign"
    rare.loc[:3, "diagnosis"] = "malignant"
    reasons = validate_csv_for_task(_write(rare, tmp_path / "r.csv"), "diagnosis")
    assert any("少数类" in reason for reason in reasons)

    with_missing = frame.copy().astype({"diagnosis": object})
    with_missing.loc[:2, "diagnosis"] = None
    reasons = validate_csv_for_task(_write(with_missing, tmp_path / "n.csv"), "diagnosis")
    assert any("缺失" in reason for reason in reasons)

    monkeypatch.setattr(csv_task, "MAX_ROWS", 100)
    reasons = validate_csv_for_task(_write(frame, tmp_path / "big.csv"), "diagnosis")
    assert any("超过上限" in reason for reason in reasons)
    assert validate_csv_for_task(tmp_path / "missing.csv", "diagnosis")[0].startswith("无法读取")


def test_card_level_rejections_are_reported_together(tmp_path, monkeypatch) -> None:
    frame = _frame()
    path = _write(frame, tmp_path / "upload.csv")
    card = _card(frame, target={"column": "diagnosis", "positive_label": "cancer"})
    card["fields"] = [field for field in card["fields"] if field["name"] != "f5"]
    card["fields"][0]["availability"] = "maybe"
    with pytest.raises(CsvTaskError) as caught:
        register_csv_task(path, card, tmp_path / "data")
    reasons = caught.value.reasons
    assert any("正类" in reason for reason in reasons)
    assert any("f5" in reason for reason in reasons)
    assert any("可用性" in reason for reason in reasons)
    assert not (tmp_path / "data" / "uploads").exists()

    monkeypatch.setattr(csv_task, "MAX_CATEGORIES", 2)
    with pytest.raises(CsvTaskError, match="高基数"):
        register_csv_task(path, _card(frame), tmp_path / "data")

    nothing_left = _card(frame)
    for field in nothing_left["fields"]:
        field["availability"] = "identifier"
    with pytest.raises(CsvTaskError, match="没有任何可用特征"):
        register_csv_task(path, nothing_left, tmp_path / "data")


def test_unknown_upload_id_is_a_clear_error() -> None:
    with pytest.raises(ValueError, match="not found"):
        get_task("upload-0000000000")
