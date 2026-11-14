"""Task adapters: read one raw dataset into a uniform (features, binary target) table.

Each task ships a scenario card (``cards/<task_id>.yaml``) that states the prediction time and
which fields are available at that time. The card is the trusted source for the approved
feature list; adapters never decide feature availability on their own.

Built-in tasks live in ``TASKS``. Tasks uploaded through the web page (``upload-*``, see
``csv_task.py``) live under ``<data_root>/uploads/<task_id>/`` and are found through the data
roots registered with ``register_data_root`` (``prepare_task`` and ``load_development`` do
this), falling back to ``<project>/data`` and ``<cwd>/data``.
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

from ..schemas import Metric, TaskType

CARD_DIR = Path(__file__).parent / "cards"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
UPLOAD_PREFIX = "upload-"
_DATA_ROOTS: list[Path] = []


def register_data_root(data_root: Path) -> None:
    """Remember a data root so uploaded tasks under it can be resolved by id."""
    root = Path(data_root).resolve()
    if root not in _DATA_ROOTS:
        _DATA_ROOTS.insert(0, root)


@dataclass(frozen=True)
class TaskDefinition:
    task_id: str
    target_column: str
    primary_metric: Metric
    holdout_fraction: float
    holdout_seed: int
    load_raw: Callable[[Path], tuple[pd.DataFrame, pd.Series]]
    card_path: Path | None = None
    task_type: TaskType = "binary"

    @property
    def card(self) -> dict[str, Any]:
        if self.card_path is not None:
            return _load_card_file(str(self.card_path))
        return load_card(self.task_id)


@cache
def load_card(task_id: str) -> dict[str, Any]:
    path = CARD_DIR / f"{task_id}.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@cache
def _load_card_file(path: str) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


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


# ---------------------------------------------------------------- adult census income (UCI 2)

ADULT_URL = "https://archive.ics.uci.edu/static/public/2/adult.zip"
ADULT_SHA256 = {
    "adult.data": "5b00264637dbfec36bdeaab5676b0b309ff9eb788d63554ca0a249491c86603d",
    "adult.test": "a2a9044bc167a35b2361efbabec64e89d69ce82d9790d2980119aac5fd7e9c05",
}
ADULT_COLUMNS = (
    "age",
    "workclass",
    "fnlwgt",
    "education",
    "education-num",
    "marital-status",
    "occupation",
    "relationship",
    "race",
    "sex",
    "capital-gain",
    "capital-loss",
    "hours-per-week",
    "native-country",
    "income",
)


def download_adult(raw_dir: Path) -> tuple[Path, Path]:
    data_path, test_path = raw_dir / "adult.data", raw_dir / "adult.test"
    if not (data_path.exists() and test_path.exists()):
        raw_dir.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(  # noqa: S310 - fixed URL
                ADULT_URL, timeout=60, context=_ssl_context()
            ) as response:
                archive = zipfile.ZipFile(io.BytesIO(response.read()))
        except OSError as exc:
            raise RuntimeError(
                f"download failed ({exc}). Download {ADULT_URL} manually and place adult.data "
                f"and adult.test in {raw_dir}"
            ) from exc
        for name in ADULT_SHA256:
            (raw_dir / name).write_bytes(archive.read(name))
    for name, expected in ADULT_SHA256.items():
        digest = hashlib.sha256((raw_dir / name).read_bytes()).hexdigest()
        if digest != expected:
            raise ValueError(f"unexpected {name} hash: {digest}")
    return data_path, test_path


def read_adult_files(data_path: Path, test_path: Path) -> tuple[pd.DataFrame, pd.Series]:
    """Combine the original train and test files; this project re-splits them itself."""
    options = dict(names=list(ADULT_COLUMNS), skipinitialspace=True, na_values="?", header=None)
    train = pd.read_csv(data_path, **options)
    test = pd.read_csv(test_path, skiprows=1, **options)  # first line is a comment
    frame = pd.concat([train, test], ignore_index=True).dropna(subset=["income"])
    labels = frame.pop("income").astype(str).str.strip().str.rstrip(".")
    unexpected = sorted(set(labels) - {">50K", "<=50K"})
    if unexpected:
        raise ValueError(f"unexpected adult income labels: {unexpected}")
    return frame, (labels == ">50K").astype(int).rename("income")


def _load_adult(raw_dir: Path) -> tuple[pd.DataFrame, pd.Series]:
    return read_adult_files(*download_adult(raw_dir))


# ---------------------------------------------------------------- breast cancer (smoke only)


def _load_breast_cancer(raw_dir: Path) -> tuple[pd.DataFrame, pd.Series]:
    from sklearn.datasets import load_breast_cancer

    raw = load_breast_cancer(as_frame=True)
    return raw.data.copy(), raw.target.astype(int).rename("target")


def _load_iris(raw_dir: Path) -> tuple[pd.DataFrame, pd.Series]:
    from sklearn.datasets import load_iris

    raw = load_iris(as_frame=True)
    return raw.data.copy(), raw.target.astype(int).rename("target")


def _load_diabetes(raw_dir: Path) -> tuple[pd.DataFrame, pd.Series]:
    from sklearn.datasets import load_diabetes

    raw = load_diabetes(as_frame=True)
    return raw.data.copy(), raw.target.astype(float).rename("target")


TASKS: dict[str, TaskDefinition] = {
    "bank_marketing": TaskDefinition(
        task_id="bank_marketing",
        target_column="y",
        primary_metric="f1_macro",
        holdout_fraction=0.2,
        holdout_seed=20261114,
        load_raw=_load_bank_marketing,
    ),
    "adult": TaskDefinition(
        task_id="adult",
        target_column="income",
        primary_metric="f1_macro",
        holdout_fraction=0.2,
        holdout_seed=20261114,
        load_raw=_load_adult,
    ),
    "breast_cancer": TaskDefinition(
        task_id="breast_cancer",
        target_column="target",
        primary_metric="f1_macro",
        holdout_fraction=0.2,
        holdout_seed=20261114,
        load_raw=_load_breast_cancer,
    ),
    "iris": TaskDefinition(
        task_id="iris",
        target_column="target",
        primary_metric="f1_macro",
        holdout_fraction=0.2,
        holdout_seed=20261114,
        load_raw=_load_iris,
        task_type="multiclass",
    ),
    "diabetes": TaskDefinition(
        task_id="diabetes",
        target_column="target",
        primary_metric="r2",
        holdout_fraction=0.2,
        holdout_seed=20261114,
        load_raw=_load_diabetes,
        task_type="regression",
    ),
}


def upload_dir_for(task_id: str) -> Path | None:
    roots = [*_DATA_ROOTS, PROJECT_ROOT / "data", Path.cwd() / "data"]
    for root in roots:
        candidate = root / "uploads" / task_id
        if (candidate / "task.json").exists():
            return candidate
    return None


def get_task(task_id: str) -> TaskDefinition:
    if task_id in TASKS:
        return TASKS[task_id]
    if task_id.startswith(UPLOAD_PREFIX):
        upload_dir = upload_dir_for(task_id)
        if upload_dir is not None:
            from .csv_task import load_uploaded_task

            return load_uploaded_task(upload_dir)
        raise ValueError(f"uploaded task {task_id} not found under any registered data root")
    raise ValueError(f"unknown task: {task_id}; known: {sorted(TASKS)}")
