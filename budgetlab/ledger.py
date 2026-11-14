from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class EventLedger:
    """Single-process writer for append-only run events."""

    def __init__(self, run_id: str, run_dir: Path) -> None:
        self.run_id = run_id
        self.run_dir = run_dir
        self.path = run_dir / "events.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._next_sequence = len(self.read_events()) + 1

    def append(
        self,
        event_type: str,
        *,
        action_id: str | None = None,
        artifact_ref: str | None = None,
        reason_code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            event = {
                "seq": self._next_sequence,
                "event_id": str(uuid.uuid4()),
                "timestamp": utc_now(),
                "run_id": self.run_id,
                "action_id": action_id,
                "event_type": event_type,
                "artifact_ref": artifact_ref,
                "reason_code": reason_code,
                "details": details or {},
            }
            line = json.dumps(event, ensure_ascii=False, sort_keys=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(line + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._next_sequence += 1
            return event

    def write_artifact(self, relative_path: str, value: Any) -> Path:
        path = self.run_dir / relative_path
        atomic_write_json(path, value)
        return path

    def read_events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events: list[dict[str, Any]] = []
        with self.path.open(encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    events.append(json.loads(line))
        expected = list(range(1, len(events) + 1))
        if [event.get("seq") for event in events] != expected:
            raise ValueError("event ledger sequence is not contiguous")
        return events
