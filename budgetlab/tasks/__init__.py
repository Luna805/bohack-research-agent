"""Task adapters: read one raw dataset into a uniform (features, binary target) table.

Each task ships a scenario card (``cards/<task_id>.yaml``) that states the prediction time and
which fields are available at that time. The card is the trusted source for the approved
feature list; adapters never decide feature availability on their own.
"""

from __future__ import annotations

import hashlib
import io
import ssl
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from ..schemas import Metric

CARD_DIR = Path(__file__).parent / "cards"


@dataclass(frozen=True)
class TaskDefinition:
    task_id: str
    target_column: str
    primary_metric: Metric
    holdout_fraction: float
    holdout_seed: int
    load_raw: Callable[[Path], tuple[pd.DataFrame, pd.Series]]

    @property
    def card(self) -> dict[str, Any]:
        return load_card(self.task_id)


@cache
def load_card(task_id: str) -> dict[str, Any]:
    path = CARD_DIR / f"{task_id}.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def field_availability(card: dict[str, Any], columns: list[str]) -> dict[str, str]:
    """Map every column to its availability label from the card (default from the card)."""
    declared = {field["name"]: field["availability"] for field in card.get("fields", [])}
    default = card.get("default_availability")
    result: dict[str, str] = {}
    for column in columns:
        if column in declared:
            result[column] = declared[column]
        elif default is not None:
            result[column] = default
        else:
            raise ValueError(f"scenario card {card['task_id']} does not describe column {column}")
    return result


def approved_features(card: dict[str, Any], columns: list[str]) -> tuple[str, ...]:
    availability = field_availability(card, columns)
    return tuple(column for column in columns if availability[column] == "available")


# ---------------------------------------------------------------- bank marketing (UCI 222)

BANK_URL = "https://archive.ics.uci.edu/static/public/222/bank+marketing.zip"
BANK_FULL_SHA256 = "74adfc578bf77a7ff4bb1ba4a9f8709d9e3c6907342959c2c8416847e0afb4d8"


def _bank_csv_path(raw_dir: Path) -> Path:
    return raw_dir / "bank-additional" / "bank-additional-full.csv"


def _ssl_context() -> ssl.SSLContext:
    """Prefer certifi's CA bundle: some macOS/pyenv Pythons ship without system CAs."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def download_bank_marketing(raw_dir: Path) -> Path:
    target = _bank_csv_path(raw_dir)
    if target.exists():
        return target
    raw_dir.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(  # noqa: S310 - fixed URL
            BANK_URL, timeout=60, context=_ssl_context()
        ) as response:
            outer = zipfile.ZipFile(io.BytesIO(response.read()))
    except OSError as exc:
        raise RuntimeError(
            f"download failed ({exc}). Download {BANK_URL} manually, unzip it, unzip the inner "
            f"bank-additional.zip, and place bank-additional-full.csv at {target}"
        ) from exc
    inner = zipfile.ZipFile(io.BytesIO(outer.read("bank-additional.zip")))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(inner.read("bank-additional/bank-additional-full.csv"))
    return target


def _load_bank_marketing(raw_dir: Path) -> tuple[pd.DataFrame, pd.Series]:
    path = download_bank_marketing(raw_dir)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != BANK_FULL_SHA256:
        raise ValueError(f"unexpected bank-additional-full.csv hash: {digest}")
    frame = pd.read_csv(path, sep=";")
    target = (frame.pop("y") == "yes").astype(int).rename("y")
    return frame, target


# ---------------------------------------------------------------- breast cancer (smoke only)


def _load_breast_cancer(raw_dir: Path) -> tuple[pd.DataFrame, pd.Series]:
    from sklearn.datasets import load_breast_cancer

    raw = load_breast_cancer(as_frame=True)
    return raw.data.copy(), raw.target.astype(int).rename("target")


TASKS: dict[str, TaskDefinition] = {
    "bank_marketing": TaskDefinition(
        task_id="bank_marketing",
        target_column="y",
        primary_metric="f1_macro",
        holdout_fraction=0.2,
        holdout_seed=20261114,
        load_raw=_load_bank_marketing,
    ),
    "breast_cancer": TaskDefinition(
        task_id="breast_cancer",
        target_column="target",
        primary_metric="f1_macro",
        holdout_fraction=0.2,
        holdout_seed=20261114,
        load_raw=_load_breast_cancer,
    ),
}


def get_task(task_id: str) -> TaskDefinition:
    try:
        return TASKS[task_id]
    except KeyError as exc:
        raise ValueError(f"unknown task: {task_id}; known: {sorted(TASKS)}") from exc
