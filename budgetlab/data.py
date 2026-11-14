"""Trusted data preparation and the development-only loader.

``prepare_task`` is the only code that sees the full labelled dataset. It writes two files:

* ``<data_root>/prepared/<task>/development.csv`` - the only data the research loop, the
  runner and the proposer context are built from;
* ``<data_root>/sealed/<task>/holdout.csv`` - read only by ``budgetlab.evaluation`` after a
  run's delivery is frozen.

This is a file-level boundary inside one machine, not an OS sandbox.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from sklearn.model_selection import StratifiedKFold, train_test_split

from .contracts import stable_hash
from .ledger import atomic_write_json
from .tasks import get_task, register_data_root

ROW_ID = "__row_id__"


@dataclass(frozen=True)
class DatasetBundle:
    dataset_ref: str
    features: pd.DataFrame
    target: pd.Series
    row_ids: tuple[str, ...]
    dataset_hash: str
    target_column: str


def development_path(data_root: Path, task_id: str) -> Path:
    return data_root / "prepared" / task_id / "development.csv"


def manifest_path(data_root: Path, task_id: str) -> Path:
    return data_root / "prepared" / task_id / "manifest.json"


def sealed_holdout_path(data_root: Path, task_id: str) -> Path:
    return data_root / "sealed" / task_id / "holdout.csv"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_frame(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, float_format="%.17g", lineterminator="\n")


def prepare_task(task_id: str, data_root: Path, *, force: bool = False) -> dict[str, Any]:
    """Split the raw dataset once into development data and a sealed stratified holdout."""
    register_data_root(data_root)
    task = get_task(task_id)
    dev_path = development_path(data_root, task_id)
    holdout_path = sealed_holdout_path(data_root, task_id)
    meta_path = manifest_path(data_root, task_id)
    if dev_path.exists() and holdout_path.exists() and meta_path.exists() and not force:
        import json

        return json.loads(meta_path.read_text(encoding="utf-8"))
    features, target = task.load_raw(data_root / "raw" / task_id)
    frame = features.copy()
    frame.insert(0, ROW_ID, [f"{task_id}:{index}" for index in range(len(frame))])
    frame[task.target_column] = target.to_numpy()
    positions = list(range(len(frame)))
    dev_positions, holdout_positions = train_test_split(
        positions,
        test_size=task.holdout_fraction,
        stratify=target,
        random_state=task.holdout_seed,
    )
    development = frame.iloc[sorted(dev_positions)].reset_index(drop=True)
    holdout = frame.iloc[sorted(holdout_positions)].reset_index(drop=True)
    _write_frame(development, dev_path)
    _write_frame(holdout, holdout_path)
    manifest = {
        "task_id": task_id,
        "target_column": task.target_column,
        "holdout_fraction": task.holdout_fraction,
        "holdout_seed": task.holdout_seed,
        "development_rows": len(development),
        "development_positive_rate": float(development[task.target_column].mean()),
        "development_sha256": file_sha256(dev_path),
        "holdout_rows": len(holdout),
        "holdout_sha256": file_sha256(holdout_path),
        "scenario_card_hash": stable_hash(task.card),
    }
    atomic_write_json(meta_path, manifest)
    return manifest


def load_development(task_id: str, data_root: Path) -> DatasetBundle:
    """Load development rows only. Holdout rows are not in this file."""
    register_data_root(data_root)
    task = get_task(task_id)
    path = development_path(data_root, task_id)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing; run `python -m budgetlab.cli prepare --task {task_id}` first"
        )
    frame = pd.read_csv(path)
    row_ids = tuple(frame.pop(ROW_ID).astype(str))
    target = frame.pop(task.target_column).astype(int).rename(task.target_column)
    return DatasetBundle(
        dataset_ref=task_id,
        features=frame,
        target=target,
        row_ids=row_ids,
        dataset_hash=file_sha256(path),
        target_column=task.target_column,
    )


def numeric_minima(features: pd.DataFrame) -> dict[str, float]:
    return {
        column: float(features[column].min(skipna=True))
        for column in features.select_dtypes(include="number").columns
    }


def split_manifest(
    bundle: DatasetBundle, seeds: Iterable[int], cv_folds: int
) -> tuple[dict[str, object], str]:
    manifests: list[dict[str, object]] = []
    for seed in seeds:
        splitter = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=seed)
        folds = []
        for fold_index, (train, valid) in enumerate(splitter.split(bundle.features, bundle.target)):
            folds.append(
                {
                    "fold": fold_index,
                    "train_rows": len(train),
                    "valid_row_ids": [bundle.row_ids[index] for index in valid],
                }
            )
        manifests.append({"seed": seed, "folds": folds})
    value = {"dataset_hash": bundle.dataset_hash, "cv_folds": cv_folds, "splits": manifests}
    return value, stable_hash(value)
