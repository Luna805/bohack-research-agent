"""Immutable, hash-addressed lesson snapshots (a plain JSON list of lessons)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..contracts import stable_hash
from ..ledger import atomic_write_json
from .models import Lesson

EMPTY_SNAPSHOT_HASH = stable_hash([])


def normalize(lessons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate every lesson and sort by id so input order never changes the hash."""
    try:
        validated = [Lesson.model_validate(item).model_dump(mode="json") for item in lessons]
    except ValidationError as exc:
        raise ValueError(f"invalid lesson in snapshot: {exc}") from exc
    ids = [item["lesson_id"] for item in validated]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate lesson_id in snapshot")
    return sorted(validated, key=lambda item: item["lesson_id"])


def snapshot_hash(lessons: list[dict[str, Any]]) -> str:
    return stable_hash(normalize(lessons))


def load_snapshot(path: Path) -> list[dict[str, Any]]:
    """Read and strictly validate a snapshot; a missing, corrupt or invalid file fails loudly."""
    if not path.exists():
        raise FileNotFoundError(f"lesson snapshot not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"lesson snapshot is not valid JSON: {path}: {exc}") from exc
    if not isinstance(value, list):
        raise ValueError(f"lesson snapshot must be a JSON list: {path}")
    return normalize(value)


def write_snapshot(path: Path, lessons: list[dict[str, Any]]) -> str:
    """Publish a new snapshot. Published snapshots are never overwritten in place."""
    if path.exists():
        raise FileExistsError(f"snapshot already published, choose a new name: {path}")
    value = normalize(lessons)
    atomic_write_json(path, value)
    return stable_hash(value)
