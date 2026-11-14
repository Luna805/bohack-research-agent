"""Offline checks for the built-in task adapters (no downloads)."""

from __future__ import annotations

import pytest

from budgetlab.tasks import ADULT_COLUMNS, TASKS, approved_features, load_card, read_adult_files


def test_every_builtin_card_describes_every_column() -> None:
    expected = {
        "adult": [column for column in ADULT_COLUMNS if column != "income"],
    }
    for task_id, columns in expected.items():
        card = load_card(task_id)
        assert card["task_id"] == task_id
        assert card["target"]["column"] == TASKS[task_id].target_column
        assert {field["name"] for field in card["fields"]} == set(columns)
        assert approved_features(card, columns)


def test_adult_reader_combines_files_and_cleans_labels(tmp_path) -> None:
    row = (
        "39, State-gov, 77516, Bachelors, 13, Never-married, Adm-clerical, Not-in-family, "
        "White, Male, 2174, 0, 40, {country}, {label}\n"
    )
    (tmp_path / "adult.data").write_text(
        row.format(country="United-States", label="<=50K") + row.format(country="?", label=">50K"),
        encoding="utf-8",
    )
    (tmp_path / "adult.test").write_text(
        "|1x3 Cross validator\n" + row.format(country="India", label=">50K."), encoding="utf-8"
    )
    frame, target = read_adult_files(tmp_path / "adult.data", tmp_path / "adult.test")
    assert list(target) == [0, 1, 1]
    assert target.name == "income"
    assert "income" not in frame.columns
    assert frame["native-country"].isna().sum() == 1
    assert frame["workclass"].iloc[0] == "State-gov"


def test_adult_reader_rejects_unknown_labels(tmp_path) -> None:
    row = (
        "39, State-gov, 77516, Bachelors, 13, Never-married, Adm-clerical, Not-in-family, "
        "White, Male, 0, 0, 40, United-States, {label}\n"
    )
    (tmp_path / "adult.data").write_text(row.format(label="maybe"), encoding="utf-8")
    (tmp_path / "adult.test").write_text("|header\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected adult income labels"):
        read_adult_files(tmp_path / "adult.data", tmp_path / "adult.test")
