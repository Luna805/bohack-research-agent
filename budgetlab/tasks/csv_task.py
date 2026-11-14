"""Generic CSV task adapter for the chat research page (role C; docs/INTERFACES.md 8.2).

A user uploads a CSV, the page drafts a protocol, a person confirms it, and the confirmed
scenario card plus the CSV are registered here as a normal task:

    task_id = register_csv_task(Path("upload.csv"), card, Path("data"))
    prepare_task(task_id, Path("data"))          # seals a stratified 20% holdout
    run_research({**base_config, "task_id": task_id}, "budgetlab", ...)

Everything is written to ``<data_root>/uploads/<task_id>/`` (``data.csv``, ``card.yaml``,
``task.json``) so training subprocesses can resolve the task by id. Only binary
classification is supported; anything else is rejected with reasons a person can act on.
Rejection messages are Chinese because they are shown to users on the page.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from ..contracts import canonical_json
from ..ledger import atomic_write_json, utc_now
from . import UPLOAD_PREFIX, TaskDefinition, register_data_root

MAX_ROWS = 100_000
MAX_COLUMNS = 200
MIN_PER_CLASS = 10  # enough for a 20% holdout and 5-fold CV on the rest
MAX_CATEGORIES = 1_000  # wider categorical columns would explode one-hot encoding
AVAILABILITIES = ("available", "post_outcome", "identifier")
METRICS = ("f1_macro", "accuracy", "roc_auc")
HOLDOUT_FRACTION = 0.2
HOLDOUT_SEED = 20261114
REQUIRED_CARD_KEYS = ("title", "business_question", "prediction_time", "target", "fields")


class CsvTaskError(ValueError):
    """Raised with every reason at once so the page can show them together."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("; ".join(reasons))


def read_csv_any(path: Path) -> pd.DataFrame:
    """Read a CSV in UTF-8, UTF-8 with BOM, GBK or Latin-1 with a sniffed delimiter."""
    raw = Path(path).read_bytes()
    text = None
    for encoding in ("utf-8-sig", "gbk", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:  # latin-1 never fails; kept for type checkers
        raise ValueError("unreadable encoding")
    sample = text[:65536]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        delimiter = ","
    return pd.read_csv(io.StringIO(text), sep=delimiter)


def _target_values(series: pd.Series) -> list[str]:
    return sorted(series.dropna().astype(str).str.strip().unique().tolist())


def validate_csv_for_task(csv_path: Path, target_column: str) -> list[str]:
    """Reasons this CSV cannot become a task; an empty list means it can."""
    try:
        frame = read_csv_any(csv_path)
    except Exception as exc:  # any parse error is a user-facing rejection
        return [f"无法读取这个 CSV：{type(exc).__name__}: {exc}"]
    return _frame_problems(frame, target_column)


def _frame_problems(frame: pd.DataFrame, target_column: str) -> list[str]:
    reasons: list[str] = []
    if frame.empty:
        return ["CSV 里没有数据行"]
    if len(frame) > MAX_ROWS:
        reasons.append(f"行数 {len(frame)} 超过上限 {MAX_ROWS}，请先抽样")
    if frame.shape[1] > MAX_COLUMNS:
        reasons.append(f"列数 {frame.shape[1]} 超过上限 {MAX_COLUMNS}")
    if frame.shape[1] < 2:
        reasons.append("除了目标列至少还需要一列特征")
    if target_column not in frame.columns:
        shown = ", ".join(map(str, list(frame.columns)[:12]))
        reasons.append(f"找不到目标列「{target_column}」；现有列：{shown}")
        return reasons
    target = frame[target_column]
    missing = int(target.isna().sum())
    if missing:
        reasons.append(f"目标列有 {missing} 行缺失值，请先删除或补全这些行")
    values = _target_values(target)
    if len(values) != 2:
        sample = ", ".join(values[:6])
        reasons.append(
            f"目前只支持二分类，目标列有 {len(values)} 个不同取值"
            f"（{sample}{'…' if len(values) > 6 else ''}）"
        )
    else:
        counts = target.dropna().astype(str).str.strip().value_counts()
        if int(counts.min()) < MIN_PER_CLASS:
            reasons.append(
                f"少数类只有 {int(counts.min())} 行，至少需要 {MIN_PER_CLASS} 行"
                "才能切出 holdout 并做 5 折交叉验证"
            )
    return reasons


def _card_problems(card: dict[str, Any], frame: pd.DataFrame) -> list[str]:
    reasons = [f"协议缺少字段「{key}」" for key in REQUIRED_CARD_KEYS if not card.get(key)]
    if reasons:
        return reasons
    target = card["target"]
    target_column = str(target.get("column", ""))
    if target_column not in frame.columns:
        return [f"协议里的目标列「{target_column}」不在 CSV 中"]
    values = _target_values(frame[target_column])
    positive = str(target.get("positive_label", "")).strip()
    if positive not in values:
        reasons.append(f"正类「{positive}」不是目标列的取值之一（{', '.join(values[:6])}）")
    metric = card.get("primary_metric", "f1_macro")
    if metric not in METRICS:
        reasons.append(f"指标「{metric}」不受支持，可选：{', '.join(METRICS)}")
    feature_columns = [column for column in frame.columns if column != target_column]
    fields = {str(field.get("name")): field for field in card["fields"]}
    missing = [column for column in feature_columns if column not in fields]
    if missing:
        reasons.append(f"协议没有说明这些列能否使用：{', '.join(missing[:10])}")
    extra = [name for name in fields if name not in frame.columns or name == target_column]
    if extra:
        reasons.append(f"协议里有 CSV 中不存在的特征列：{', '.join(extra[:10])}")
    bad = [
        name for name, field in fields.items() if field.get("availability") not in AVAILABILITIES
    ]
    if bad:
        reasons.append(f"这些列的可用性不是 {'/'.join(AVAILABILITIES)} 之一：{', '.join(bad[:10])}")
    available = [
        name
        for name, field in fields.items()
        if field.get("availability") == "available" and name in frame.columns
    ]
    if not available and not missing:
        reasons.append("确认后没有任何可用特征")
    for name in available:
        series = frame[name]
        if not pd.api.types.is_numeric_dtype(series) and series.nunique() > MAX_CATEGORIES:
            reasons.append(
                f"列「{name}」有 {series.nunique()} 个不同取值，当前版本不支持高基数类别或文本列；"
                "请标记为 identifier，或先删除这一列"
            )
    return reasons


def task_id_for(csv_bytes: bytes, card: dict[str, Any]) -> str:
    """Same CSV and same confirmed card give the same id; any change gives a new one."""
    digest = hashlib.sha256()
    digest.update(csv_bytes)
    digest.update(
        canonical_json({key: value for key, value in card.items() if key != "task_id"}).encode()
    )
    return UPLOAD_PREFIX + digest.hexdigest()[:10]


def register_csv_task(csv_path: Path, card: dict[str, Any], data_root: Path) -> str:
    """Validate an uploaded CSV with its confirmed card and register it as a task."""
    csv_path = Path(csv_path)
    try:
        frame = read_csv_any(csv_path)
    except Exception as exc:
        raise CsvTaskError([f"无法读取这个 CSV：{type(exc).__name__}: {exc}"]) from exc
    target_column = str((card.get("target") or {}).get("column", ""))
    reasons = _frame_problems(frame, target_column) + (
        _card_problems(card, frame) if target_column in frame.columns else []
    )
    if not card.get("target"):
        reasons.append("协议缺少字段「target」")
    if reasons:
        raise CsvTaskError(list(dict.fromkeys(reasons)))
    raw = csv_path.read_bytes()
    task_id = task_id_for(raw, card)
    upload_dir = Path(data_root) / "uploads" / task_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    frame.to_csv(upload_dir / "data.csv", index=False, lineterminator="\n")
    stored_card = {**card, "task_id": task_id}
    (upload_dir / "card.yaml").write_text(
        yaml.safe_dump(stored_card, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    target = card["target"]
    atomic_write_json(
        upload_dir / "task.json",
        {
            "task_id": task_id,
            "source_file_name": csv_path.name,
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "rows": len(frame),
            "columns": len(frame.columns),
            "target_column": str(target["column"]),
            "positive_label": str(target["positive_label"]).strip(),
            "primary_metric": card.get("primary_metric", "f1_macro"),
            "holdout_fraction": HOLDOUT_FRACTION,
            "holdout_seed": HOLDOUT_SEED,
            "registered_at": utc_now(),
        },
    )
    register_data_root(Path(data_root))
    return task_id


def load_uploaded_task(upload_dir: Path) -> TaskDefinition:
    meta = json.loads((upload_dir / "task.json").read_text(encoding="utf-8"))
    target_column = meta["target_column"]
    positive = meta["positive_label"]

    def load_raw(_raw_dir: Path) -> tuple[pd.DataFrame, pd.Series]:
        frame = pd.read_csv(upload_dir / "data.csv")
        target = frame.pop(target_column)
        encoded = (target.astype(str).str.strip() == positive).astype(int).rename(target_column)
        return frame, encoded

    return TaskDefinition(
        task_id=meta["task_id"],
        target_column=target_column,
        primary_metric=meta["primary_metric"],
        holdout_fraction=meta["holdout_fraction"],
        holdout_seed=meta["holdout_seed"],
        load_raw=load_raw,
        card_path=upload_dir / "card.yaml",
    )


def development_rows(
    csv_path: Path, target_column: str, positive_label: str
) -> tuple[pd.DataFrame, pd.Series]:
    """The rows ``prepare_task`` will keep for development, reproduced before registration.

    The holdout split depends only on the row order, the encoded target and a fixed seed, never
    on the protocol, so the page can show the protocol agent development data only and keep the
    future holdout rows out of its context (INTERFACES 8.1).
    """
    from sklearn.model_selection import train_test_split

    frame = read_csv_any(csv_path)
    raw_target = frame.pop(target_column)
    target = (raw_target.astype(str).str.strip() == str(positive_label).strip()).astype(int)
    development, _ = train_test_split(
        list(range(len(frame))),
        test_size=HOLDOUT_FRACTION,
        stratify=target,
        random_state=HOLDOUT_SEED,
    )
    keep = sorted(development)
    features = frame.iloc[keep].reset_index(drop=True)
    return features, target.iloc[keep].reset_index(drop=True).rename(target_column)


def development_profile(
    csv_path: Path, target_column: str, positive_label: str
) -> tuple[list[str], dict[str, Any]]:
    """Column list (with the target) and a development-only profile for the protocol agent."""
    from ..profile import profile_development

    features, target = development_rows(csv_path, target_column, positive_label)
    unlabeled = {"fields": [{"name": name, "availability": "available"} for name in features]}
    return [*features.columns, target_column], profile_development(features, target, unlabeled)


def config_for_upload(task_id: str, base_config: dict[str, Any]) -> dict[str, Any]:
    """Research config for an uploaded task: the base config with this task id swapped in."""
    config = json.loads(json.dumps(base_config))
    config["task_id"] = task_id
    config.pop("primary_metric", None)  # the card decides the metric
    config.pop("text_columns", None)
    return config
