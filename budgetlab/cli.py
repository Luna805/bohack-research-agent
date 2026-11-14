from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
from typing import Any

import yaml

from .controller import SYSTEMS, replay_run, reproduce_run, run_research
from .data import prepare_task
from .tasks import TASKS


def load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def doctor(config_path: Path) -> dict[str, Any]:
    config = load_config(config_path)
    packages = {}
    for name in [
        "pydantic",
        "scikit-learn",
        "pandas",
        "numpy",
        "joblib",
        "PyYAML",
        "pydantic-ai-slim",
    ]:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    budget = config.get("budget", {})
    return {
        "status": "ok",
        "config": str(config_path),
        "task_id": config["task_id"],
        "proposer": config.get("proposer", "scripted"),
        "llm_budget": {
            "requests": budget.get("max_llm_requests", 0),
            "tokens": budget.get("max_llm_tokens", 0),
        },
        "packages": packages,
    }


def probe_llm(config_path: Path) -> dict[str, Any]:
    """One real structured-output request with the final ProposalBatch schema."""
    from .controller import make_agents
    from .proposers import CallOutcome

    config = load_config(config_path)
    proposer, _ = make_agents(config, "llm")
    context = {
        "mode": "normal",
        "task": {"title": "probe", "primary_metric": "f1_macro"},
        "legal_space": {"model_families": ["logistic_regression", "random_forest"]},
        "data_profile": [
            {"name": "age", "kind": "numeric"},
            {"name": "job", "kind": "categorical"},
        ],
        "baseline_id": "baseline",
        "best_id": "baseline",
        "experiments": [
            {
                "id": "baseline",
                "spec": {"model": {"family": "logistic_regression"}},
                "mean_score": 0.64,
            }
        ],
        "valid_evidence_refs": ["baseline", "eda"],
    }
    outcome: CallOutcome = proposer.propose(context)
    return {
        "ok": outcome.output is not None,
        "error": outcome.error,
        "details": outcome.details,
        "output": outcome.output.model_dump(mode="json") if outcome.output is not None else None,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="budgetlab")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor_parser = commands.add_parser("doctor", help="validate dependencies and config")
    doctor_parser.add_argument("--config", type=Path, required=True)
    prepare = commands.add_parser("prepare", help="download data and seal a stratified holdout")
    prepare.add_argument("--task", choices=sorted(TASKS), required=True)
    prepare.add_argument("--data-root", type=Path, default=Path("data"))
    prepare.add_argument("--force", action="store_true")
    research = commands.add_parser("research", help="run one research system end to end")
    research.add_argument("--config", type=Path, required=True)
    research.add_argument("--system", choices=SYSTEMS, required=True)
    research.add_argument("--proposer", choices=["scripted", "llm"], default=None)
    research.add_argument("--runs-root", type=Path, default=Path("runs"))
    research.add_argument("--data-root", type=Path, default=Path("data"))
    evaluate = commands.add_parser("evaluate", help="score a frozen delivery once on the holdout")
    evaluate.add_argument("--run-id", required=True)
    evaluate.add_argument("--runs-root", type=Path, default=Path("runs"))
    probe = commands.add_parser("probe-llm", help="one real structured-output request")
    probe.add_argument("--config", type=Path, required=True)
    reproduce = commands.add_parser("reproduce", help="retrain one frozen specification")
    reproduce.add_argument("--run-id", required=True)
    reproduce.add_argument("--runs-root", type=Path, default=Path("runs"))
    replay = commands.add_parser("replay", help="read saved events without side effects")
    replay.add_argument("--run-id", required=True)
    replay.add_argument("--runs-root", type=Path, default=Path("runs"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        result = doctor(args.config)
    elif args.command == "prepare":
        result = prepare_task(args.task, args.data_root, force=args.force)
    elif args.command == "research":
        summary = run_research(
            load_config(args.config),
            args.system,
            args.runs_root,
            args.data_root,
            proposer_kind=args.proposer,
        )
        result = {
            key: summary[key]
            for key in (
                "run_id",
                "system",
                "code_version",
                "proposal_source",
                "baseline_score",
                "exploration_best_score",
                "confirmation_status",
                "delivered_experiment_id",
                "stop_reason",
                "wall_seconds",
                "counts",
                "llm",
            )
        }
    elif args.command == "evaluate":
        from .evaluation import evaluate_frozen_run

        result = evaluate_frozen_run(args.run_id, args.runs_root)
    elif args.command == "probe-llm":
        result = probe_llm(args.config)
    elif args.command == "reproduce":
        result = reproduce_run(args.run_id, args.runs_root)
    else:
        result = replay_run(args.run_id, args.runs_root)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
