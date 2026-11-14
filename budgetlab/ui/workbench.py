"""Read-only data for the workbench page: run files, research history, experiments, progress.

Pure helpers (no Streamlit) so CI can test them. Everything is read from one run directory
under ``runs/``; paths are confined to that directory and nothing here writes files.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from budgetlab.ui.artifacts import VIEWABLE_SUFFIXES, run_dir
from budgetlab.ui.insights import cycle_status, read_json, read_jsonl

MODEL_NAMES = {
    "logistic_regression": "逻辑回归",
    "random_forest": "随机森林",
    "hist_gradient_boosting": "梯度提升树",
}
SOURCE_NAMES = {"baseline": "基线", "tool_search": "规则搜索"}
STAGES = ("规划", "收集证据", "提出假设", "实验分析", "验证", "修正再探索")


def parse_time(value: Any) -> float | None:
    """Seconds since the epoch for an ISO timestamp, or None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def run_started(run_id: str) -> datetime | None:
    """The UTC start time encoded in a run id such as ``20261114T091425Z-budgetlab-bcfccc``."""
    try:
        return datetime.strptime(run_id[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


# ------------------------------------------------------------------------------ files


def list_entries(runs_root: Path, run_id: str, folder: str = "") -> list[dict[str, Any]] | None:
    """Children of one folder inside a run, or None when the folder is outside the run."""
    base = run_dir(runs_root, run_id)
    if base is None:
        return None
    target = (base / folder).resolve()
    if not target.is_relative_to(base) or not target.is_dir():
        return None
    entries = []
    for path in target.iterdir():
        if path.name.startswith("."):
            continue
        relative = path.relative_to(base).as_posix()
        stat = path.stat()
        is_dir = path.is_dir()
        entries.append(
            {
                "name": path.name + ("/" if is_dir else ""),
                "path": relative,
                "is_dir": is_dir,
                "items": sum(1 for child in path.iterdir() if not child.name.startswith("."))
                if is_dir
                else None,
                "size": None if is_dir else stat.st_size,
                "mtime": stat.st_mtime,
                "viewable": is_dir or path.suffix.lower() in VIEWABLE_SUFFIXES,
            }
        )
    return entries


def sort_entries(entries: list[dict[str, Any]], by: str = "time") -> list[dict[str, Any]]:
    """Folders first; within each group newest first (``time``) or by name (``name``)."""
    if by == "name":
        return sorted(entries, key=lambda entry: (not entry["is_dir"], entry["name"].lower()))
    return sorted(entries, key=lambda entry: (not entry["is_dir"], -entry["mtime"]))


def round_started_at(events: list[dict[str, Any]]) -> float | None:
    """When the latest round (or tool search) began; files written after it are 'new'."""
    for event in reversed(events):
        kind = event.get("event_type")
        details = event.get("details") or {}
        if (kind == "llm_call_started" and details.get("role") in {None, "proposer"}) or (
            kind == "tool_search_started"
        ):
            return parse_time(event.get("timestamp"))
    return None


def size_text(size: int | None) -> str:
    if size is None:
        return ""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / 1024 / 1024:.1f} MB"


# ------------------------------------------------------------------------------ history


def history_rows(runs_root: Path, runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per local run for the research drawer, newest first."""
    rows = []
    for run in runs:
        base = run_dir(runs_root, run["run_id"])
        if base is None:
            continue
        summary = read_json(base / "summary.json")
        card = read_json(base / "scenario_card.json")
        config = read_json(base / "run_config.json")
        source = summary.get("proposal_source") or config.get("proposal_source")
        started = run_started(run["run_id"])
        score = summary.get("delivered_dev_score")
        rows.append(
            {
                "run_id": run["run_id"],
                "title": card.get("title") or run.get("task_id") or run["run_id"],
                "task_id": summary.get("task_id") or run.get("task_id"),
                "system": summary.get("system") or run.get("system"),
                "source": "LLM" if source == "llm" else ("脚本化" if source else "未知来源"),
                "finished": bool(run.get("finished")),
                "score": f"{score:.4f}" if isinstance(score, int | float) else "",
                "started": started,
            }
        )
    return sorted(
        rows,
        key=lambda row: row["started"] or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )


def project_groups(rows: list[dict[str, Any]], projects: dict[str, str]) -> list[dict[str, Any]]:
    """History rows grouped under their task, the project with the newest run first.

    ``projects`` maps known task ids to display names. Known projects are listed even
    without runs, after the ones that have runs, in the order given. ``rows`` must be
    newest first, as :func:`history_rows` returns them.
    """
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        task_id = row.get("task_id") or "unknown"
        name = projects.get(task_id) or row.get("title") or task_id
        groups.setdefault(task_id, {"task_id": task_id, "name": name, "runs": []})
        groups[task_id]["runs"].append(row)
    for task_id, name in projects.items():
        groups.setdefault(task_id, {"task_id": task_id, "name": name, "runs": []})
    oldest = datetime.min.replace(tzinfo=UTC)
    return sorted(
        groups.values(),
        key=lambda group: max((row["started"] or oldest for row in group["runs"]), default=oldest),
        reverse=True,
    )


def when_text(started: datetime | None, now: datetime) -> str:
    """Local start time for a history row: ``19:28`` today, ``昨天`` or ``11月13日`` before."""
    if started is None:
        return ""
    local, today = started.astimezone(), now.astimezone().date()
    if local.date() == today:
        return local.strftime("%H:%M")
    if (today - local.date()).days == 1:
        return "昨天"
    return f"{local.month}月{local.day}日"


# ------------------------------------------------------------------------------ experiments


def describe_spec(spec: dict[str, Any]) -> str:
    """A short Chinese description of a model spec, e.g. ``随机森林 · 300 棵 · 深度 32``."""
    model = spec.get("model") or {}
    parts = [MODEL_NAMES.get(model.get("family"), model.get("family") or "模型")]
    if model.get("n_estimators"):
        parts.append(f"{model['n_estimators']} 棵")
    if model.get("max_depth"):
        parts.append(f"深度 {model['max_depth']}")
    if model.get("min_samples_leaf"):
        parts.append(f"叶节点 ≥ {model['min_samples_leaf']}")
    if model.get("learning_rate"):
        parts.append(f"学习率 {model['learning_rate']}")
    if model.get("class_weight") == "balanced":
        parts.append("平衡权重")
    actions = []
    for action in spec.get("feature_actions") or []:
        columns = "、".join(map(str, action.get("columns") or []))
        kind = action.get("kind")
        label = {
            "log1p": "log1p",
            "sentinel_to_missing": "哨兵值转缺失",
            "missing_indicator": "缺失指示列",
            "drop": "去掉",
            "drop_columns": "去掉",
        }.get(kind, kind or "特征处理")
        actions.append(f"{label} {columns}".strip())
    text = " · ".join(parts)
    return text + (f"；{'；'.join(actions)}" if actions else "")


def _min_effect(base: Path) -> float | None:
    summary = read_json(base / "summary.json")
    if isinstance(summary.get("min_effect"), int | float):
        return float(summary["min_effect"])
    policy = read_json(base / "contract.json").get("decision_policy") or {}
    value = policy.get("min_effect")
    return float(value) if isinstance(value, int | float) else None


def experiment_table(
    base: Path, events: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Every search experiment (baseline, tool search, proposals), newest first.

    ``kind`` drives the status chip: run, best, warn (a new high below the minimum effect),
    plain, base or fail. A started experiment without a result shows as ``run``.
    """
    events = events if events is not None else read_jsonl(base / "events.jsonl")
    min_effect = _min_effect(base)
    source = read_json(base / "run_config.json").get("proposal_source")
    proposal = "LLM 提案" if source == "llm" else "脚本提案"
    delivered = read_json(base / "summary.json").get("delivered_experiment_id")
    rows = []
    done: set[str] = set()
    for path in (base / "experiments").glob("*.json"):
        detail = read_json(path)
        experiment_id = detail.get("experiment_id")
        if not isinstance(experiment_id, str) or detail.get("origin") is None:
            continue  # calibration and confirmation fits are not search experiments
        result = detail.get("result") or {}
        score = result.get("mean_score")
        delta = detail.get("delta_vs_previous_best")
        origin = detail.get("origin")
        if result.get("status") not in {None, "ok"}:
            kind, status = "fail", "失败"
        elif experiment_id == delivered:
            kind, status = "delivered", "交付模型"
        elif origin == "baseline":
            kind, status = "base", "基线"
        elif isinstance(delta, int | float) and delta > 0:
            if min_effect is not None and delta < min_effect:
                kind, status = "warn", f"新高但未达 {min_effect:.4g}"
            else:
                kind, status = "best", "刷新最优"
        else:
            kind, status = "plain", "未刷新"
        done.add(experiment_id)
        rows.append(
            {
                "id": experiment_id,
                "round": detail.get("round"),
                "source": SOURCE_NAMES.get(origin, proposal),
                "model": (detail.get("spec") or {}).get("model", {}).get("family", ""),
                "change": describe_spec(detail.get("spec") or {}),
                "score": score,
                "delta": delta,
                "best_after": detail.get("best_score_after"),
                "kind": kind,
                "status": status,
                "seconds": result.get("duration_seconds"),
                "elapsed": detail.get("elapsed_seconds"),
                "tokens": detail.get("llm_tokens_so_far"),
                "path": f"experiments/{experiment_id}.json",
            }
        )
    rows.sort(key=lambda row: row["elapsed"] if row["elapsed"] is not None else -1, reverse=True)
    running = running_experiment(events, done)
    if running:
        rows.insert(
            0,
            {
                "id": running,
                "round": None,
                "source": SOURCE_NAMES.get("tool_search")
                if running.startswith("tool-")
                else proposal,
                "model": "",
                "change": "",
                "score": None,
                "delta": None,
                "best_after": None,
                "kind": "run",
                "status": "训练中",
                "seconds": None,
                "elapsed": None,
                "tokens": None,
                "path": None,
            },
        )
    return rows


def running_experiment(events: list[dict[str, Any]], done: set[str]) -> str | None:
    """The search experiment that has started but not finished, if any."""
    finished = {
        str(event.get("action_id", "")).removeprefix("train:")
        for event in events
        if event.get("event_type") in {"experiment_completed", "experiment_failed"}
    }
    for event in reversed(events):
        if event.get("event_type") != "experiment_started":
            continue
        experiment_id = str(event.get("action_id", "")).removeprefix("train:")
        searchable = experiment_id.startswith(("r", "tool-")) or experiment_id == "baseline"
        if searchable and experiment_id not in finished and experiment_id not in done:
            return experiment_id
        return None
    return None


# ------------------------------------------------------------------------------ progress


def progress(base: Path, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Round, experiment count, budget, best score so far and the six research stages."""
    events = events if events is not None else read_jsonl(base / "events.jsonl")
    table = [row for row in experiment_table(base, events) if row["kind"] != "run"]
    contract = read_json(base / "contract.json")
    budget = (contract.get("budgets") or {}).get("max_experiments")
    best = max(
        (row for row in table if isinstance(row["score"], int | float)),
        key=lambda row: row["score"],
        default=None,
    )
    rounds = [row["round"] for row in table if isinstance(row["round"], int)]
    times = [parse_time(event.get("timestamp")) for event in events]
    times = [value for value in times if value is not None]
    counts = dict(cycle_status(events))
    return {
        "round": max(rounds, default=0),
        "experiments": len(table),
        "max_experiments": budget,
        "best": best["score"] if best else None,
        "best_id": best["id"] if best else None,
        "elapsed": (max(times) - min(times)) if len(times) > 1 else 0.0,
        "stages": [(label, counts.get(label, 0) > 0) for label in STAGES],
        "running": running_experiment(events, {row["id"] for row in table}),
    }


def clock(seconds: float | None) -> str:
    if not isinstance(seconds, int | float):
        return "—"
    minutes, rest = divmod(int(round(seconds)), 60)
    return f"{minutes:02d}:{rest:02d}"
