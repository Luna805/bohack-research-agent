"""Minimal cross-run lesson bank (P1).

Flow: a finished run -> ``extract_run`` (draft, program facts only) -> ``write_snapshot``
(immutable, hashed) -> a later run selects that snapshot in its config -> ``match_lessons``
(at most three) -> proposer context key ``lessons`` -> ``lesson_usage`` records what was
cited and tested. Lessons never bypass screening, budgets or verdicts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .extract import extract_run, merge_runs
from .match import context_view, match_lessons
from .store import EMPTY_SNAPSHOT_HASH, load_snapshot, snapshot_hash, write_snapshot
from .usage import lesson_usage

__all__ = [
    "EMPTY_SNAPSHOT_HASH",
    "MemorySettings",
    "context_view",
    "extract_run",
    "lesson_usage",
    "load_snapshot",
    "match_lessons",
    "merge_runs",
    "snapshot_hash",
    "write_snapshot",
]


class MemorySettings:
    """The optional ``memory:`` config section. Absent or ``enabled: false`` changes nothing."""

    def __init__(self, config: dict[str, Any]) -> None:
        section = config.get("memory") or {}
        unknown = set(section) - {"enabled", "snapshot"}
        if unknown:
            raise ValueError(f"unknown memory config keys: {sorted(unknown)}")
        self.enabled = bool(section.get("enabled", False))
        snapshot = section.get("snapshot")
        self.snapshot = Path(snapshot) if snapshot else None

    def load(self, project_root: Path) -> tuple[list[dict[str, Any]], str | None]:
        """Lessons and the snapshot reference; an enabled bank without a snapshot is empty."""
        if not self.enabled or self.snapshot is None:
            return [], None
        path = self.snapshot if self.snapshot.is_absolute() else project_root / self.snapshot
        return load_snapshot(path), self.snapshot.as_posix()
