"""Background workflow for page runs: research, freeze, then one final test."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from budgetlab.cli import load_config
from budgetlab.controller import SYSTEMS, run_research
from budgetlab.evaluation import evaluate_frozen_run
from budgetlab.ledger import EventLedger
from budgetlab.ui.insights import read_json

FINAL_TEST_STATE = "ui_final_test.json"


def _record_status(run_id: str, runs_root: Path, status: str, error: str | None = None) -> None:
    # Reopen the ledger: the evaluator also appends its own event in between updates.
    ledger = EventLedger(run_id, runs_root / run_id)
    ledger.write_artifact(FINAL_TEST_STATE, {"status": status, "error": error})
    ledger.append(f"ui_final_test_{status}", artifact_ref=FINAL_TEST_STATE)


def finish_final_test(run_id: str, runs_root: Path) -> dict[str, Any]:
    """Reuse a saved result; otherwise call the existing frozen-model evaluator once."""
    existing = read_json(runs_root / run_id / "final_evaluation.json")
    if existing:
        return existing
    _record_status(run_id, runs_root, "running")
    try:
        result = evaluate_frozen_run(run_id, runs_root)
    except Exception as exc:
        _record_status(run_id, runs_root, "failed", f"{type(exc).__name__}: {exc}")
        raise
    _record_status(run_id, runs_root, "completed")
    return result


def run_page_research(
    config: dict[str, Any],
    system: str,
    runs_root: Path,
    data_root: Path,
    proposer_kind: str | None = None,
) -> dict[str, Any]:
    summary = run_research(config, system, runs_root, data_root, proposer_kind=proposer_kind)
    # The controller has finished and frozen its delivery before this separate step.
    return finish_final_test(summary["run_id"], runs_root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--config", type=Path)
    mode.add_argument("--evaluate-run-id")
    parser.add_argument("--system", choices=SYSTEMS, default="budgetlab")
    parser.add_argument("--proposer", choices=["scripted", "llm"])
    parser.add_argument("--runs-root", type=Path, default=Path("runs"))
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    args = parser.parse_args(argv)
    if args.evaluate_run_id:
        result = finish_final_test(args.evaluate_run_id, args.runs_root)
    else:
        result = run_page_research(
            load_config(args.config), args.system, args.runs_root, args.data_root, args.proposer
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
