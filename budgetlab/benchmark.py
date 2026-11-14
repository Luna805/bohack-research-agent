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
* proposals always come from the LLM (``proposer: llm``), so every matrix is checked before
  anything runs (positive LLM budget in every task config, model and key configured) and a
  misconfigured night run fails in seconds instead of recording a column of failed slots.
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
from .evaluation import evaluate_frozen_run, paired_bootstrap
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
    "min_effect",
    "holdout_ci_low",
    "holdout_ci_high",
)
DEFAULT_TIE_BAND = 0.002  # used only when a row has no calibrated min_effect


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
    proposer = matrix.get("proposer", "llm")
    if proposer != "llm":
        raise MatrixError(f"proposer must be llm, got {proposer!r} (no rule-based proposer)")
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
        "reference_system": matrix.get("reference_system", "random_search"),
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
        "min_effect": summary.get("min_effect"),
        "holdout_ci_low": (final.get("holdout_ci95") or [None, None])[0],
        "holdout_ci_high": (final.get("holdout_ci95") or [None, None])[1],
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


def _mean(values: list[float]) -> float | None:
    return statistics.mean(values) if values else None


def paired_holdout_cis(
    rows: list[dict[str, Any]], reference: str, runs_root: Path
) -> dict[str, dict[str, Any]]:
    """Paired bootstrap of holdout differences, keyed "task/r<repeat>/system".

    Pairs whose runs lack saved holdout predictions (evaluated before CIs existed) are skipped.
    """
    ok = {
        (row["task_id"], row["repeat"], row["system"]): row
        for row in rows
        if row.get("status") == "ok" and row.get("run_id")
    }
    results: dict[str, dict[str, Any]] = {}
    for (task, repeat, system), row in ok.items():
        ref = ok.get((task, repeat, reference))
        if system == reference or ref is None:
            continue
        try:
            results[f"{task}/r{repeat}/{system}"] = paired_bootstrap(
                runs_root / row["run_id"], runs_root / ref["run_id"]
            ) | {"repeat": repeat, "run_id": row["run_id"], "reference_run_id": ref["run_id"]}
        except (FileNotFoundError, ValueError):
            continue
    return results


def compare_systems(
    rows: list[dict[str, Any]],
    reference: str = "random_search",
    paired_ci: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Paired comparison against ``reference`` plus cost efficiency, from ok rows only.

    Pairs share task and repeat, hence the same split, training and search seeds. A pair is a
    win or loss only when the holdout difference exceeds the larger calibrated ``min_effect``
    of the two runs; this is an engineering band, not a significance test.
    """
    ok = [row for row in rows if row.get("status") == "ok" and row.get("holdout_score") is not None]
    index = {(row["task_id"], row["repeat"], row["system"]): row for row in ok}
    tasks = list(dict.fromkeys(row["task_id"] for row in ok))
    paired: list[dict[str, Any]] = []
    efficiency: list[dict[str, Any]] = []
    for task in tasks:
        task_rows = [row for row in ok if row["task_id"] == task]
        systems = list(dict.fromkeys(row["system"] for row in task_rows))
        repeats = sorted({row["repeat"] for row in task_rows})
        for system in systems:
            own = [row for row in task_rows if row["system"] == system]
            tokens = _mean([float(row["llm_tokens"] or 0) for row in own]) or 0.0
            wall = _mean([float(row["wall_seconds"]) for row in own])
            dev_gain = _mean(
                [float(row["delivered_dev_score"]) - float(row["baseline_score"]) for row in own]
            )
            efficiency.append(
                {
                    "task_id": task,
                    "system": system,
                    "runs": len(own),
                    "mean_dev_gain_over_baseline": dev_gain,
                    "mean_holdout": _mean([float(row["holdout_score"]) for row in own]),
                    "mean_llm_tokens": tokens,
                    "mean_wall_seconds": wall,
                    "dev_gain_per_1k_tokens": dev_gain / (tokens / 1000)
                    if tokens > 0 and dev_gain is not None
                    else None,
                    "dev_gain_per_minute": dev_gain / (wall / 60)
                    if wall and dev_gain is not None
                    else None,
                }
            )
            if system == reference:
                continue
            pairs = [
                (index[(task, repeat, system)], index[(task, repeat, reference)])
                for repeat in repeats
                if (task, repeat, system) in index and (task, repeat, reference) in index
            ]
            if not pairs:
                continue
            deltas, wins, losses = [], 0, 0
            for mine, ref in pairs:
                delta = float(mine["holdout_score"]) - float(ref["holdout_score"])
                band = max(
                    float(mine.get("min_effect") or DEFAULT_TIE_BAND),
                    float(ref.get("min_effect") or DEFAULT_TIE_BAND),
                )
                deltas.append(delta)
                wins += delta > band
                losses += delta < -band
            mean_tokens = _mean([float(mine["llm_tokens"] or 0) for mine, _ in pairs]) or 0.0
            mean_delta = statistics.mean(deltas)
            paired.append(
                {
                    "task_id": task,
                    "system": system,
                    "reference": reference,
                    "pairs": len(pairs),
                    "mean_delta_holdout": mean_delta,
                    "std_delta_holdout": statistics.stdev(deltas) if len(deltas) > 1 else None,
                    "wins": wins,
                    "ties": len(pairs) - wins - losses,
                    "losses": losses,
                    "mean_llm_tokens": mean_tokens,
                    "mean_delta_wall_seconds": _mean(
                        [float(m["wall_seconds"]) - float(r["wall_seconds"]) for m, r in pairs]
                    ),
                    "mean_delta_experiments": _mean(
                        [float(m["experiments"]) - float(r["experiments"]) for m, r in pairs]
                    ),
                    "mean_delta_fits": _mean(
                        [float(m["fits"]) - float(r["fits"]) for m, r in pairs]
                    ),
                    "delta_holdout_per_1k_tokens": mean_delta / (mean_tokens / 1000)
                    if mean_tokens > 0
                    else None,
                }
            )
            cis = [(paired_ci or {}).get(f"{task}/r{mine['repeat']}/{system}") for mine, _ in pairs]
            cis = [ci for ci in cis if ci is not None]
            paired[-1].update(
                holdout_ci_pairs=[
                    {
                        "repeat": ci["repeat"],
                        "delta": ci["delta"],
                        "ci95": ci["ci95"],
                        "share_positive": ci["share_positive"],
                        "identical_predictions": ci["identical_predictions"],
                    }
                    for ci in cis
                ],
                pairs_ci_above_zero=sum(ci["ci95"][0] > 0 for ci in cis) if cis else None,
                pairs_ci_below_zero=sum(ci["ci95"][1] < 0 for ci in cis) if cis else None,
            )
    return {"reference": reference, "paired": paired, "efficiency": efficiency}


def _fmt(value: float | None, digits: int = 4, signed: bool = False) -> str:
    if value is None:
        return "–"
    return f"{value:+.{digits}f}" if signed else f"{value:.{digits}f}"


def write_aggregate(
    out_dir: Path,
    rows: list[dict[str, Any]],
    reference: str = "random_search",
    paired_ci: dict[str, dict[str, Any]] | None = None,
) -> None:
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
    comparison = compare_systems(rows, reference, paired_ci)
    atomic_write_json(out_dir / "comparison.json", comparison)
    if comparison["paired"]:
        lines += [
            "",
            f"## Paired comparison against `{reference}` (same task and repeat, same seeds)",
            "",
            "W/T/L: holdout difference beyond the larger calibrated min_effect of the pair "
            "(engineering band, not a significance test). CI>0 / CI<0: pairs whose paired "
            "bootstrap 95% interval of the holdout difference lies entirely above / below zero "
            "(descriptive, same holdout rows for both systems).",
            "",
            "| task | system | pairs | Δ holdout | W/T/L | CI>0 / CI<0 | LLM tokens | Δ wall s"
            " | Δ experiments | Δ holdout per 1k tokens |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for item in comparison["paired"]:
            above, below = item.get("pairs_ci_above_zero"), item.get("pairs_ci_below_zero")
            ci_text = (
                "–" if above is None else f"{above}/{below} of {len(item['holdout_ci_pairs'])}"
            )
            spread = item["std_delta_holdout"]
            delta = _fmt(item["mean_delta_holdout"], signed=True) + (
                f" ± {spread:.4f}" if spread is not None else ""
            )
            lines.append(
                f"| {item['task_id']} | {item['system']} | {item['pairs']} | {delta} | "
                f"{item['wins']}/{item['ties']}/{item['losses']} | "
                f"{ci_text} | "
                f"{_fmt(item['mean_llm_tokens'], 0)} | "
                f"{_fmt(item['mean_delta_wall_seconds'], 1, signed=True)} | "
                f"{_fmt(item['mean_delta_experiments'], 1, signed=True)} | "
                f"{_fmt(item['delta_holdout_per_1k_tokens'], 5, signed=True)} |"
            )
    if comparison["efficiency"]:
        lines += [
            "",
            "## Cost efficiency (dev gain = delivered dev score - baseline dev score)",
            "",
            "| task | system | runs | dev gain | holdout | LLM tokens | wall s"
            " | dev gain per 1k tokens | dev gain per minute |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for item in comparison["efficiency"]:
            lines.append(
                f"| {item['task_id']} | {item['system']} | {item['runs']} | "
                f"{_fmt(item['mean_dev_gain_over_baseline'], signed=True)} | "
                f"{_fmt(item['mean_holdout'])} | {_fmt(item['mean_llm_tokens'], 0)} | "
                f"{_fmt(item['mean_wall_seconds'], 1)} | "
                f"{_fmt(item['dev_gain_per_1k_tokens'], 5, signed=True)} | "
                f"{_fmt(item['dev_gain_per_minute'], 4, signed=True)} |"
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
        write_aggregate(
            out_dir,
            [rows[s["slot_id"]] for s in slots if s["slot_id"] in rows],
            matrix.get("reference_system", "random_search"),
        )
    ordered = [rows[s["slot_id"]] for s in slots if s["slot_id"] in rows]
    reference = matrix.get("reference_system", "random_search")
    paired_ci = paired_holdout_cis(ordered, reference, runs_root)
    atomic_write_json(out_dir / "paired_bootstrap.json", paired_ci)
    write_aggregate(out_dir, ordered, reference, paired_ci)
    log(f"[{matrix_id}] paired bootstrap computed for {len(paired_ci)} pairs")
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
