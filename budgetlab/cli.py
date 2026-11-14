from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
from typing import Any

import yaml

from .controller import replay_run, reproduce_run, run_research


def load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def doctor(config_path: Path) -> dict[str, Any]:
    config = load_config(config_path)
    packages = {}
    for name in ["pydantic", "scikit-learn", "pandas", "numpy", "joblib", "PyYAML"]:
        packages[name] = importlib.metadata.version(name)
    return {
        "status": "ok",
        "config": str(config_path),
        "dataset_ref": config["dataset_ref"],
        "api_budget": {"requests": 0, "cost_usd": 0},
        "packages": packages,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="budgetlab")
    commands = parser.add_subparsers(dest="command", required=True)
    doctor_parser = commands.add_parser("doctor", help="validate offline dependencies and config")
    doctor_parser.add_argument("--config", type=Path, required=True)
    research = commands.add_parser("research", help="run a deterministic research smoke")
    research.add_argument("--config", type=Path, required=True)
    research.add_argument("--system", choices=["random_search", "scripted_smoke"], required=True)
    research.add_argument("--runs-root", type=Path, default=Path("runs"))
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
    elif args.command == "research":
        result = run_research(load_config(args.config), args.system, args.runs_root)
    elif args.command == "reproduce":
        result = reproduce_run(args.run_id, args.runs_root)
    else:
        result = replay_run(args.run_id, args.runs_root)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
