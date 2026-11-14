"""Comparison matrix runner (role C). Output format: docs/INTERFACES.md section 5.

Usage (from the repository root)::

    python -m budgetlab.benchmark --matrix configs/benchmark/dev.yaml
    python -m budgetlab.benchmark --matrix configs/benchmark/dev.yaml --dry-run
    python -m budgetlab.benchmark --resume dev-20261114T031500Z

Rules baked in:

* runs are executed **one at a time** (parallel runs would distort wall-clock comparisons);
* within each (task, repeat) all systems run back to back, so machine drift hits every
  system equally;
* repeat ``r`` adds ``r * repeat_seed_stride`` to ``search_seed`` for every system alike;
  split and training seeds never change;
* every run's frozen delivery is scored on the sealed holdout exactly once, then only
  ``summary.json``, ``final_evaluation.json`` and ``report.md`` are copied into ``results/``;
* ``aggregate.csv`` / ``aggregate.json`` / ``aggregate.md`` are rewritten after every run,
  so an interrupted matrix keeps everything finished so far and can be resumed;
* a ``final`` matrix refuses to start from a checkout with uncommitted changes;
* a matrix with ``proposer: llm`` is checked before anything runs (positive LLM budget in
  every task config, model and key configured), so a misconfigured night run fails in
  seconds instead of recording a column of failed slots.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import shutil
import statistics
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .contracts import stable_hash
from .controller import SYSTEMS, make_agents, run_research
from .evaluation import evaluate_frozen_run
from .ledger import atomic_write_json, utc_now
from .provenance import code_version_label, environment_info, git_info
from .runner import PROJECT_ROOT

MATRIX_VERSION = 1
RESULT_FILES = ("summary.json", "final_evaluation.json", "report.md")
# Column order is part of the interface: only append new columns at the end.
COLUMNS = (
    "matrix_id",
    "task_id",
    "system",
    "proposal_source",
    "repeat",
    "run_id",
    "code_version",
    "baseline_score",
    "exploration_best_score",
    "confirmation_status",
    "delivered_experiment_id",
    "delivered_dev_score",
    "holdout_score",
    "dev_minus_holdout",
    "llm_calls",
    "llm_requests",
    "llm_tokens",
    "llm_unknown_tokens",
    "cost_usd",
    "wall_seconds",
    "train_seconds",
    "experiments",
    "fits",
    "rounds",
    "duplicates_blocked",
    "invalid_rejected",
    "direction_changes_agent",
    "direction_changes_rule",
    "stop_reason",
    "slot_id",
    "status",
    "error",
)


class MatrixError(RuntimeError):
    pass


# ---------------------------------------------------------------------------- planning


def deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load_matrix(path: Path) -> dict[str, Any]:
    matrix = yaml.safe_load(path.read_text(encoding="utf-8"))
    kind = matrix.get("kind", "dev")
    if kind not in ("dev", "final"):
        raise MatrixError(f"matrix kind must be dev or final, got {kind!r}")
    systems = list(matrix.get("systems", SYSTEMS))
    unknown = sorted(set(systems) - set(SYSTEMS))
    if unknown:
        raise MatrixError(f"unknown systems {unknown}; choose from {SYSTEMS}")
    if not matrix.get("tasks"):
        raise MatrixError("matrix needs at least one task")
    repeats = int(matrix.get("repeats", 1))
    if repeats < 1:
        raise MatrixError("repeats must be >= 1")
    proposer = matrix.get("proposer", "scripted")
    if proposer not in ("scripted", "llm"):
        raise MatrixError("proposer must be scripted or llm")
    return {
        "kind": kind,
        "description": matrix.get("description", ""),
        "tasks": [
            {
                "name": task["name"],
                "config": str(task["config"]),
                "overrides": task.get("overrides", {}),
            }
            for task in matrix["tasks"]
        ],
        "systems": systems,
        "repeats": repeats,
        "proposer": proposer,
        "overrides": matrix.get("overrides", {}),
        "repeat_seed_stride": int(matrix.get("repeat_seed_stride", 1000)),
    }


def plan_slots(matrix: dict[str, Any], base_dir: Path) -> list[dict[str, Any]]:
    """One slot per (task, repeat, system), ordered task -> repeat -> system."""
    slots = []
    for task in matrix["tasks"]:
        config_path = (base_dir / task["config"]).resolve()
        base_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        task_config = deep_merge(deep_merge(base_config, matrix["overrides"]), task["overrides"])
        for repeat in range(matrix["repeats"]):
            config = copy.deepcopy(task_config)
            config["search_seed"] = int(config.get("search_seed", 2026)) + (
                repeat * matrix["repeat_seed_stride"]
            )
            for system in matrix["systems"]:
                slots.append(
                    {
                        "slot_id": f"{task['name']}/r{repeat + 1}/{system}",
                        "task": task["name"],
                        "repeat": repeat + 1,
                        "system": system,
                        "proposer_kind": None if system == "random_search" else matrix["proposer"],
                        "config_path": task["config"],
                        "config": config,
                        "config_hash": stable_hash(config),
                    }
                )
    return slots


def preflight(slots: list[dict[str, Any]], *, check_credentials: bool = True) -> list[str]:
    """Problems that would make LLM slots fail or stop at once. No model request is made."""
    problems: list[str] = []
    checked: set[str] = set()
    for slot in slots:
        # Repeats differ only in search_seed, so one check per task is enough.
        if slot["proposer_kind"] != "llm" or slot["task"] in checked:
            continue
        checked.add(slot["task"])
        budget = slot["config"].get("budget", {})
        label = f"{slot['task']} ({slot['config_path']})"
        if int(budget.get("max_llm_requests", 0)) <= 0 or int(budget.get("max_llm_tokens", 0)) <= 0:
            problems.append(
                f"{label}: max_llm_requests and max_llm_tokens must be positive for proposer=llm "
                "(otherwise every run stops at once with llm_budget_exhausted)"
            )
        if check_credentials:
            try:
                make_agents(slot["config"], "llm")
            except Exception as exc:  # report every configuration problem before starting
                problems.append(f"{label}: cannot build the LLM proposer: {exc}")
    return problems


# ---------------------------------------------------------------------------- rows


def _row(
    matrix_id: str, slot: dict[str, Any], summary: dict[str, Any], final: dict[str, Any]
) -> dict[str, Any]:
    counts = summary["counts"]
    llm = summary["llm"]
    used = summary["budget"]["used"]
    return {
        "matrix_id": matrix_id,
        "task_id": summary["task_id"],
        "system": summary["system"],
        "proposal_source": summary["proposal_source"],
        "repeat": slot["repeat"],
        "run_id": summary["run_id"],
        "code_version": summary.get("code_version"),
        "baseline_score": summary["baseline_score"],
        "exploration_best_score": summary["exploration_best_score"],
        "confirmation_status": summary["confirmation_status"],
        "delivered_experiment_id": summary["delivered_experiment_id"],
        "delivered_dev_score": summary["delivered_dev_score"],
        "holdout_score": final["holdout_score"],
        "dev_minus_holdout": final["dev_minus_holdout"],
        "llm_calls": llm["calls"],
        "llm_requests": llm["requests"],
        "llm_tokens": llm["tokens"],
        "llm_unknown_tokens": llm["unknown"]["llm_tokens"],
        "cost_usd": llm["cost_usd"],
        "wall_seconds": summary["wall_seconds"],
        "train_seconds": round(float(used["seconds"]), 2),
        "experiments": counts["experiments"],
        "fits": used["fits"],
        "rounds": counts["rounds"],
        "duplicates_blocked": counts["duplicates_blocked"],
        "invalid_rejected": counts["invalid_rejected"],
        "direction_changes_agent": counts["direction_changes"]["agent"],
        "direction_changes_rule": counts["direction_changes"]["rule"],
        "stop_reason": summary["stop_reason"],
        "slot_id": slot["slot_id"],
        "status": "ok",
        "error": None,
    }


def _error_row(matrix_id: str, slot: dict[str, Any], error: str) -> dict[str, Any]:
    row: dict[str, Any] = {column: None for column in COLUMNS}
    row.update(
        matrix_id=matrix_id,
        task_id=slot["task"],
        system=slot["system"],
        repeat=slot["repeat"],
        slot_id=slot["slot_id"],
        status="error",
        error=error[-500:],
    )
    return row


def _mean_std(values: list[float], digits: int = 4) -> str:
    if not values:
        return "–"
    if len(values) == 1:
        return f"{values[0]:.{digits}f}"
    return f"{statistics.mean(values):.{digits}f} ± {statistics.stdev(values):.{digits}f}"


def write_aggregate(out_dir: Path, rows: list[dict[str, Any]]) -> None:
    """Rows are written in matrix plan order (task -> repeat -> system)."""
    with (out_dir / "aggregate.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column) for column in COLUMNS})
    atomic_write_json(out_dir / "aggregate.json", rows)
    lines = [
        f"# Matrix `{out_dir.name}`",
        "",
        "Per task and system (mean ± sample std over repeats; ok runs only).",
        "",
        "| task | system | n | baseline | best dev | delivered dev | holdout | LLM tokens"
        " | wall s | confirmed |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        if row["status"] == "ok":
            groups.setdefault((row["task_id"], row["system"]), []).append(row)
    for (task_id, system), items in sorted(groups.items()):

        def col(name: str, items: list[dict[str, Any]] = items) -> list[float]:
            return [float(item[name]) for item in items if item[name] is not None]

        confirmed = sum(item["confirmation_status"] == "confirmed_pass" for item in items)
        lines.append(
            f"| {task_id} | {system} | {len(items)} | {_mean_std(col('baseline_score'))} | "
            f"{_mean_std(col('exploration_best_score'))} | {_mean_std(col('delivered_dev_score'))}"
            f" | {_mean_std(col('holdout_score'))} | {_mean_std(col('llm_tokens'), 0)} | "
            f"{_mean_std(col('wall_seconds'), 1)} | {confirmed}/{len(items)} |"
        )
    failed = [row for row in rows if row["status"] != "ok"]
    if failed:
        lines += ["", f"Failed slots: {', '.join(row['slot_id'] for row in failed)}"]
    (out_dir / "aggregate.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------- running


def _new_matrix_id(kind: str) -> str:
    return f"{kind}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"


def run_matrix(
    matrix_path: Path | None = None,
    *,
    resume: str | None = None,
    runs_root: Path = Path("runs"),
    data_root: Path = Path("data"),
    results_root: Path = Path("results"),
    base_dir: Path = Path("."),
    proposer_factory: Any = None,
    log: Any = print,
) -> Path:
    """Run (or resume) a matrix; returns ``results/<matrix_id>``.

    ``proposer_factory(slot) -> proposer | None`` exists for tests that inject a model.
    """
    git = git_info(PROJECT_ROOT)
    if resume is not None:
        out_dir = results_root / resume
        record = json.loads((out_dir / "matrix.json").read_text(encoding="utf-8"))
        matrix = record["matrix"]
        matrix_id = record["matrix_id"]
        if matrix["kind"] == "final" and (git or {}).get("commit") != record["git"]["commit"]:
            raise MatrixError("a final matrix can only be resumed on the commit it started on")
    else:
        if matrix_path is None:
            raise MatrixError("give --matrix or --resume")
        matrix = load_matrix(matrix_path)
        matrix_id = _new_matrix_id(matrix["kind"])
        out_dir = results_root / matrix_id
        record = None
    if matrix["kind"] == "final" and (git is None or git["dirty"]):
        raise MatrixError(
            "final matrices must start from a clean git checkout "
            f"(code version: {code_version_label(git)})"
        )
    slots = plan_slots(matrix, base_dir)
    problems = preflight(slots, check_credentials=proposer_factory is None)
    if problems:
        raise MatrixError("preflight failed:\n- " + "\n- ".join(problems))
    if record is not None:
        registered = {slot["slot_id"]: slot["config_hash"] for slot in record["slots"]}
        changed = [s["slot_id"] for s in slots if registered.get(s["slot_id"]) != s["config_hash"]]
        if changed:
            raise MatrixError(f"task configs changed since the matrix started: {changed[:3]}")
    if record is None:
        out_dir.mkdir(parents=True, exist_ok=False)
        record = {
            "matrix_version": MATRIX_VERSION,
            "matrix_id": matrix_id,
            "matrix_file": str(matrix_path),
            "matrix": matrix,
            "slots": [
                {key: slot[key] for key in ("slot_id", "task", "repeat", "system", "config_path")}
                | {"config_hash": slot["config_hash"], "search_seed": slot["config"]["search_seed"]}
                for slot in slots
            ],
            "code_version": code_version_label(git),
            "git": git,
            "environment": environment_info(),
            "started_at": utc_now(),
            "finished_at": None,
            "seed_policy": "split/training seeds fixed; search_seed += (repeat-1) * stride",
        }
        atomic_write_json(out_dir / "matrix.json", record)
    aggregate_path = out_dir / "aggregate.json"
    rows: dict[str, dict[str, Any]] = {}
    if aggregate_path.exists():
        rows = {row["slot_id"]: row for row in json.loads(aggregate_path.read_text("utf-8"))}
    pending = [slot for slot in slots if rows.get(slot["slot_id"], {}).get("status") != "ok"]
    log(f"[{matrix_id}] {len(slots)} slots, {len(pending)} to run")
    for index, slot in enumerate(pending, start=1):
        log(f"[{matrix_id}] ({index}/{len(pending)}) {slot['slot_id']} ...")
        try:
            proposer = proposer_factory(slot) if proposer_factory else None
            summary = run_research(
                slot["config"],
                slot["system"],
                runs_root,
                data_root,
                proposer=proposer,
                proposer_kind=slot["proposer_kind"],
            )
            final = evaluate_frozen_run(summary["run_id"], runs_root)
            destination = out_dir / "runs" / summary["run_id"]
            destination.mkdir(parents=True, exist_ok=True)
            for name in RESULT_FILES:
                shutil.copy2(runs_root / summary["run_id"] / name, destination / name)
            rows[slot["slot_id"]] = _row(matrix_id, slot, summary, final)
            log(
                f"[{matrix_id}]   {summary['run_id']} holdout={final['holdout_score']:.4f} "
                f"tokens={summary['llm']['tokens']} wall={summary['wall_seconds']}s"
            )
        except Exception as exc:  # one failed slot must not lose the rest of the matrix
            rows[slot["slot_id"]] = _error_row(
                matrix_id, slot, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
            )
            log(f"[{matrix_id}]   FAILED: {type(exc).__name__}: {exc}")
        write_aggregate(out_dir, [rows[s["slot_id"]] for s in slots if s["slot_id"] in rows])
    record["finished_at"] = utc_now()
    record["completed_slots"] = sum(row["status"] == "ok" for row in rows.values())
    atomic_write_json(out_dir / "matrix.json", record)
    return out_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m budgetlab.benchmark")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--matrix", type=Path, help="matrix YAML, e.g. configs/benchmark/dev.yaml")
    source.add_argument("--resume", help="matrix_id under results/ to continue")
    parser.add_argument("--runs-root", type=Path, default=Path("runs"))
    parser.add_argument("--data-root", type=Path, default=Path("data"))
    parser.add_argument("--results-root", type=Path, default=Path("results"))
    parser.add_argument("--dry-run", action="store_true", help="print the planned slots only")
    args = parser.parse_args(argv)
    if args.dry_run:
        if args.matrix is None:
            parser.error("--dry-run needs --matrix")
        matrix = load_matrix(args.matrix)
        slots = plan_slots(matrix, Path("."))
        for slot in slots:
            print(
                f"{slot['slot_id']:<48} proposer={slot['proposer_kind']} "
                f"search_seed={slot['config']['search_seed']}"
            )
        problems = preflight(slots)
        report = "preflight problems:\n- " + "\n- ".join(problems) if problems else "preflight: ok"
        print(report)
        return 0 if not problems else 1
    out_dir = run_matrix(
        args.matrix,
        resume=args.resume,
        runs_root=args.runs_root,
        data_root=args.data_root,
        results_root=args.results_root,
    )
    print((out_dir / "aggregate.md").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
