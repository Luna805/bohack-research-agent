"""Lesson bank commands: ``python -m budgetlab.memory {extract,publish,show}``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..data import load_development
from ..profile import profile_development
from ..tasks import get_task
from .extract import extract_run, merge_runs
from .match import mismatch, target_facts
from .store import load_snapshot, write_snapshot


def _run_dirs(runs_root: Path, run_ids: list[str]) -> list[Path]:
    dirs = [runs_root / run_id for run_id in run_ids]
    for run_dir in dirs:
        if not (run_dir / "summary.json").exists():
            raise SystemExit(f"{run_dir} is not a finished run (no summary.json)")
    return dirs


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m budgetlab.memory")
    parser.add_argument("--runs-root", type=Path, default=Path("runs"))
    sub = parser.add_subparsers(dest="command", required=True)
    extract = sub.add_parser("extract", help="print the lesson draft of one finished run")
    extract.add_argument("--run-id", required=True)
    publish = sub.add_parser("publish", help="build an immutable snapshot from finished runs")
    publish.add_argument("--run-id", action="append", required=True, dest="run_ids")
    publish.add_argument("--out", type=Path, required=True)
    show = sub.add_parser("show", help="list a snapshot; with --task, show which lessons match")
    show.add_argument("--snapshot", type=Path, required=True)
    show.add_argument("--task")
    show.add_argument("--data-root", type=Path, default=Path("data"))
    args = parser.parse_args(argv)

    if args.command == "extract":
        (run_dir,) = _run_dirs(args.runs_root, [args.run_id])
        print(json.dumps(extract_run(run_dir), indent=2, ensure_ascii=False))
    elif args.command == "publish":
        lessons = merge_runs(_run_dirs(args.runs_root, args.run_ids))
        digest = write_snapshot(args.out, lessons)
        print(json.dumps({"snapshot": str(args.out), "hash": digest, "lessons": len(lessons)}))
    else:
        lessons = load_snapshot(args.snapshot)
        facts = None
        if args.task:
            task = get_task(args.task)
            bundle = load_development(task.task_id, args.data_root)
            facts = target_facts(profile_development(bundle.features, bundle.target, task.card, ()))
        for lesson in lessons:
            line = (
                f"{lesson['lesson_id']}  {lesson['status']:<20} "
                f"d={lesson['observed_effect']['delta']:+.4f} support={lesson['support']} "
                f"counter={len(lesson['counterexamples'])}  {lesson['action']['summary']}"
            )
            if facts is not None:
                reason = mismatch(lesson, facts, primary_metric=None, allowed_families=None)
                line += f"  -> {'MATCH' if reason is None else 'skip: ' + reason}"
            print(line)


if __name__ == "__main__":
    main()
