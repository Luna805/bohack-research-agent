"""Read-only, path-confined access to research evidence."""

from __future__ import annotations

import json
from pathlib import Path


class EvidenceStore:
    def __init__(self, runs_root: Path, results_root: Path) -> None:
        self.runs_root = runs_root.resolve()
        self.results_root = results_root.resolve()

    def _run(self, run_id: str) -> Path:
        path = (self.runs_root / run_id).resolve()
        if path.parent != self.runs_root:
            raise ValueError("Invalid run ID")
        return path

    def _read(self, path: Path) -> dict:
        if not path.is_file():
            raise FileNotFoundError(path.name)
        return json.loads(path.read_text(encoding="utf-8"))

    def list_runs(self) -> list[dict]:
        if not self.runs_root.exists():
            return []
        rows = []
        for path in sorted(self.runs_root.iterdir(), reverse=True):
            if path.is_dir() and (path / "summary.json").is_file():
                summary = self._read(path / "summary.json")
                rows.append(
                    {
                        "run_id": path.name,
                        "system": summary.get("system"),
                        "task_id": summary.get("task_id"),
                        "finished": True,
                    }
                )
        return rows

    def get_summary(self, run_id: str) -> dict:
        return self._read(self._run(run_id) / "summary.json")

    def get_experiment(self, run_id: str, experiment_id: str) -> dict:
        if Path(experiment_id).name != experiment_id or experiment_id in {".", ".."}:
            raise ValueError("Invalid experiment ID")
        return self._read(self._run(run_id) / "experiments" / f"{experiment_id}.json")

    def get_round(self, run_id: str, round_index: int) -> dict:
        if round_index < 0:
            raise ValueError("Invalid round index")
        return self._read(self._run(run_id) / "rounds" / f"round-{round_index:02d}.json")

    def get_llm_calls(self, run_id: str) -> list[dict]:
        path = self._run(run_id) / "llm_calls.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    def get_final_evaluation(self, run_id: str) -> dict | None:
        path = self._run(run_id) / "final_evaluation.json"
        return self._read(path) if path.is_file() else None
