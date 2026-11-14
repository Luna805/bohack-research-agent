"""Evidence-backed data for the research workspace side panels."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def token_ledger(run_dir: Path) -> dict[str, Any]:
    """Use metered calls and the frozen run budget, including unknown usage."""
    summary = read_json(run_dir / "summary.json")
    budget = read_json(run_dir / "budget.json") or summary.get("budget") or {}
    calls = read_jsonl(run_dir / "llm_calls.jsonl")
    by_role: dict[str, dict[str, int]] = defaultdict(
        lambda: {"tokens": 0, "unknown": 0, "calls": 0}
    )
    by_round: list[dict[str, Any]] = []
    for call in calls:
        role = str(call.get("role") or "unknown")
        usage = call.get("usage") or {}
        unknown = call.get("unknown") or {}
        used_tokens = int(usage.get("llm_tokens") or 0)
        unknown_tokens = int(unknown.get("llm_tokens") or 0)
        by_role[role]["tokens"] += used_tokens
        by_role[role]["unknown"] += unknown_tokens
        by_role[role]["calls"] += 1
        by_round.append(
            {
                "process": f"第 {call.get('round', '?')} 轮 · {role}",
                "tokens": used_tokens,
                "unknown": unknown_tokens,
                "source": call.get("source") or "unknown",
            }
        )
    used = int((budget.get("used") or {}).get("llm_tokens") or 0)
    unknown = int((budget.get("unknown") or {}).get("llm_tokens") or 0)
    return {
        "used": used,
        "unknown": unknown,
        "limit": int((budget.get("limits") or {}).get("max_llm_tokens") or 0),
        "by_role": dict(by_role),
        "by_round": by_round,
        "source": summary.get("proposal_source")
        or read_json(run_dir / "run_config.json").get("proposal_source"),
    }


def cycle_status(events: list[dict[str, Any]]) -> list[tuple[str, int]]:
    counts: dict[str, int] = defaultdict(int)
    for event in events:
        kind = event.get("event_type")
        details = event.get("details") or {}
        if kind == "protocol_accepted":
            counts["规划"] += 1
        elif kind in {"profile_written", "baseline_completed"}:
            counts["收集证据"] += 1
        elif kind == "llm_call_completed" and details.get("role") == "proposer":
            counts["提出假设"] += 1
        elif kind == "experiment_completed":
            counts["实验分析"] += 1
        elif kind in {"evaluation_recorded", "confirmation_completed"}:
            counts["验证"] += 1
        elif kind in {"direction_changed", "tool_search_completed"}:
            counts["修正再探索"] += 1
    return [
        (label, counts[label])
        for label in ("规划", "收集证据", "提出假设", "实验分析", "验证", "修正再探索")
    ]


def _action_experiment(event: dict[str, Any]) -> str | None:
    action = str(event.get("action_id") or "")
    if action.startswith("train:") and re.fullmatch(r"[\w-]+", action[6:]):
        return action[6:]
    return None


def experiment_rows(
    run_dir: Path, summary: dict[str, Any], events: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Include started attempts before their result exists, in execution order."""
    events = read_jsonl(run_dir / "events.jsonl") if events is None else events
    attempts: dict[str, dict[str, Any]] = {}
    hypotheses: dict[str, dict[str, Any]] = {}
    proposals: dict[str, dict[str, Any]] = {}
    best_id = None
    for event in events:
        kind = event.get("event_type")
        details = event.get("details") or {}
        experiment_id = _action_experiment(event)
        if kind == "candidate_selected":
            selected = str(details.get("experiment_id") or "")
            if re.fullmatch(r"r\d+-c\d+", selected):
                round_id = selected.split("-")[0]
                if round_id not in proposals:
                    proposals[round_id] = read_json(
                        run_dir / "llm" / f"proposer-{round_id}.output.json"
                    )
                for candidate in proposals[round_id].get("candidates") or []:
                    if candidate.get("candidate_id") == details.get("candidate_id"):
                        hypotheses[selected] = candidate.get("hypothesis") or {}
        elif kind == "experiment_started" and experiment_id:
            if details.get("purpose") not in {"initial_baseline", "exploration"}:
                continue
            hypothesis = hypotheses.get(experiment_id, {})
            origin = (
                "baseline"
                if experiment_id == "baseline"
                else "tool_search"
                if experiment_id.startswith(("tool-", "random-"))
                else "proposer"
            )
            attempts[experiment_id] = {
                "id": experiment_id,
                "origin": origin,
                "parent": hypothesis.get("comparator_experiment_id") or best_id,
                "hypothesis": hypothesis.get("statement"),
            }
            if experiment_id == "baseline":
                best_id = experiment_id
        elif kind == "evaluation_recorded" and details.get("new_best") and experiment_id:
            best_id = experiment_id

    details_by_id = {}
    for path in sorted((run_dir / "experiments").glob("*.json")):
        detail = read_json(path)
        result = detail.get("result") or {}
        experiment_id = detail.get("experiment_id") or result.get("experiment_id")
        if not isinstance(experiment_id, str) or not re.fullmatch(r"[\w-]+", experiment_id):
            continue
        if not (experiment_id == "baseline" or experiment_id.startswith(("tool-", "r"))):
            continue
        details_by_id[experiment_id] = detail
        attempts.setdefault(experiment_id, {"id": experiment_id})

    rows = []
    compact_rows = summary.get("experiments") or list(attempts.values())
    for compact in compact_rows:
        experiment_id = compact.get("id")
        if not isinstance(experiment_id, str) or not re.fullmatch(r"[\w-]+", experiment_id):
            continue
        detail = details_by_id.get(experiment_id) or read_json(
            run_dir / "experiments" / f"{experiment_id}.json"
        )
        attempt = attempts.get(experiment_id, {})
        result = detail.get("result") or {}
        spec = detail.get("spec") or compact.get("spec") or {}
        rows.append(
            {
                "id": experiment_id,
                "status": compact.get("status") or result.get("status"),
                "model_family": (spec.get("model") or {}).get("family"),
                "selection_score": result.get("mean_score", compact.get("mean_score")),
                "seconds": result.get("duration_seconds", compact.get("seconds")),
                "round": compact.get("round", detail.get("round")),
                "score": compact.get("mean_score", (detail.get("result") or {}).get("mean_score")),
                "origin": compact.get("origin") or detail.get("origin") or attempt.get("origin"),
                "verdict": compact.get("baseline_verdict")
                or (detail.get("vs_baseline") or {}).get("policy_status"),
                "hypothesis": compact.get("hypothesis")
                or detail.get("hypothesis")
                or attempt.get("hypothesis"),
                "parent": compact.get("hypothesis_comparator")
                or (detail.get("hypothesis_check") or {}).get("comparator_experiment_id")
                or detail.get("previous_best_id")
                or attempt.get("parent"),
            }
        )
    search_number = 0
    for row in rows:
        if row.get("origin") == "tool_search" or row["id"].startswith(("tool-", "random-")):
            search_number += 1
            row["label"] = f"自动搜索·方案{search_number}"
        else:
            row["label"] = experiment_label(row)
    return rows


def experiment_label(row: dict[str, Any]) -> str:
    """Keep engine IDs stable while giving each scheme a readable UI name."""
    if row.get("label"):
        return row["label"]
    experiment_id = row["id"]
    if experiment_id == "baseline":
        return "初始方案"
    match = re.fullmatch(r"r(\d+)-c(\d+)", experiment_id)
    if match:
        return f"第{int(match[1])}轮·方案{int(match[2])}"
    if experiment_id.startswith(("tool-", "random-")):
        return "自动搜索方案"
    return "候选方案"


def model_label(row: dict[str, Any]) -> str:
    return {
        "logistic_regression": "逻辑回归",
        "random_forest": "随机森林",
        "hist_gradient_boosting": "梯度提升树",
    }.get(row.get("model_family"), "模型信息见记录")


def selection_reason(
    row: dict[str, Any],
    delivered_id: str | None,
    rows: list[dict[str, Any]] | None = None,
    summary: dict[str, Any] | None = None,
) -> str:
    """Explain recorded eligibility, ranking and confirmation without inventing a reason."""
    summary = summary or {}
    if row["id"] == delivered_id:
        if delivered_id == "baseline":
            if summary.get("finalist_id"):
                return "候选方案未通过新切分复核，因此保留初始方案。"
            return "没有确认可交付的更优候选，本次保留初始方案。"
        if summary.get("confirmation_status") == "confirmed_pass":
            return "被选入最终复核，且在新数据切分上通过复核，因此最终采用。"
        return "这是本次研究最终采用的方案。"
    if row["id"] == "baseline":
        return (
            "这是起始对照，用来衡量后续方案的提升；不是最终采用的方案。"
            if delivered_id
            else "这是起始对照，用来衡量后续方案的提升。"
        )
    if row.get("status") in {"failed", "timeout"}:
        return "本次训练未成功完成，不能作为最终候选。"
    verdict = row.get("verdict")
    if verdict == "invalid":
        return "比较证据不满足要求，无法据此判断是否有提升。"
    if verdict == "not_met":
        return "相对初始方案的提升未达到最低要求，未进入最终候选。"
    if verdict != "candidate_pass":
        return "尚无完整的改进结论，暂不能判断是否入选。"
    if not delivered_id:
        return "相对初始方案有足够提升，可以参与最终候选排序；最终方案尚未确定。"
    finalist_id = summary.get("finalist_id")
    if row["id"] == finalist_id:
        return "虽然相对初始方案有足够提升，但未通过新切分复核，最终未采用。"
    preferred_id = finalist_id or delivered_id
    preferred = next((item for item in rows or [] if item["id"] == preferred_id), None)
    if preferred:
        mine = row.get("selection_score", row.get("score"))
        theirs = preferred.get("selection_score", preferred.get("score"))
        if isinstance(mine, (int, float)) and isinstance(theirs, (int, float)):
            if mine < theirs:
                return (
                    "相对初始方案有足够提升，但开发集分数低于"
                    f"「{experiment_label(preferred)}」（{theirs:.4f}），因此未入选。"
                )
            if mine == theirs:
                mine_seconds, other_seconds = row.get("seconds"), preferred.get("seconds")
                if isinstance(mine_seconds, (int, float)) and isinstance(
                    other_seconds, (int, float)
                ):
                    if mine_seconds > other_seconds:
                        return "开发集分数相同，系统优先选择训练耗时更短的方案进行复核。"
                    if mine_seconds == other_seconds:
                        return "开发集分数与训练耗时相同，系统按固定规则选择另一个方案进行复核。"
    return "相对初始方案有足够提升，但本次最终采用了其他方案。"


def branch_activity(
    run_dir: Path,
    events: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    *,
    finished: bool = False,
    running: bool | None = None,
) -> tuple[str | None, str]:
    """Follow paired ledger events; never infer activity from the highest score."""
    if finished or running is False:
        return None, ""
    active = None
    for event in events:
        kind = event.get("event_type")
        if kind in {"run_terminal", "run_failed", "delivery_frozen"}:
            return None, ""
        if kind in {"experiment_started", "llm_call_started"}:
            active = event
        elif (
            kind
            in {
                "experiment_completed",
                "experiment_failed",
                "llm_call_completed",
                "llm_call_failed",
            }
            and active
            and event.get("action_id") == active.get("action_id")
        ):
            active = None
    if not active:
        return None, ""
    ids = {row["id"] for row in rows}
    if active["event_type"] == "llm_call_started":
        action = str(active.get("action_id") or "")
        match = re.fullmatch(r"llm:(proposer|critic):(r\d+)", action)
        if not match:
            return None, ""
        role, round_id = match.groups()
        context = read_json(run_dir / "llm" / f"{role}-{round_id}.context.json")
        node_id = context.get("best_id")
        label = "正在提出假设" if role == "proposer" else "正在审查方向"
        return (node_id if node_id in ids else None), label
    experiment_id = _action_experiment(active)
    if not experiment_id:
        return None, ""
    purpose = (active.get("details") or {}).get("purpose")
    label = {
        "initial_baseline": "正在训练基线",
        "exploration": "正在执行",
        "calibration": "正在标定门槛",
        "confirmation_candidate": "正在复核候选",
        "confirmation_baseline": "正在复核基线",
        "final_refit": "正在拟合交付模型",
    }.get(purpose, "正在执行")
    if experiment_id in ids:
        return experiment_id, label
    if purpose in {"calibration", "confirmation_baseline"}:
        return ("baseline" if "baseline" in ids else None), label
    # Confirmation/refit jobs retain the exact spec of the node being executed.
    spec = read_json(run_dir / "work" / f"{experiment_id}.job.json").get("spec")
    if spec:
        for row in rows:
            if read_json(run_dir / "experiments" / f"{row['id']}.json").get("spec") == spec:
                return row["id"], label
    return None, label


def branch_tree(
    rows: list[dict[str, Any]],
    delivered_id: str | None,
    active_id: str | None = None,
    active_label: str = "正在执行",
    *,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Highlight exactly one ancestor path while preserving sibling attempts."""
    if not rows:
        return None
    ids = {row["id"] for row in rows}
    parents: dict[str, str | None] = {}
    for row in rows:
        parent = row.get("parent")
        parents[row["id"]] = parent if parent in ids and parent != row["id"] else None
    focus = active_id if active_id in ids else delivered_id
    route: set[str] = set()
    while focus in ids and focus not in route:
        route.add(focus)
        focus = parents.get(focus)
    route_color = "#5AD7FF" if active_id in ids else "#B8FF65"
    nodes: dict[str, dict[str, Any]] = {}
    roots: list[dict[str, Any]] = []
    for row in rows:
        node_id = row["id"]
        current = node_id == active_id
        lit = node_id in route
        verdict = row.get("verdict")
        selected = node_id == delivered_id
        outcome = (
            active_label
            if current
            else "最终采用"
            if selected
            else "初始对照"
            if node_id == "baseline"
            else "对照步骤"
            if lit
            else "复核未通过"
            if (summary or {}).get("finalist_id") == node_id and delivered_id
            else "训练未完成"
            if row.get("status") in {"failed", "timeout"}
            else "有提升·未入选"
            if verdict == "candidate_pass" and delivered_id
            else "有提升·候选"
            if verdict == "candidate_pass"
            else "提升不足"
            if verdict == "not_met"
            else "结果不可用"
            if verdict == "invalid"
            else "尚未完成"
            if row.get("score") is None
            else "已完成"
        )
        color = route_color if lit else "#A8B4C2"
        score = row.get("score")
        score_line = f"\n{score:.4f}" if isinstance(score, (int, float)) else ""
        chart_label = experiment_label(row).replace("自动搜索·", "搜索·")
        chart_outcome = outcome.replace("有提升·未入选", "已改善·未选")
        nodes[node_id] = {
            "id": node_id,
            "name": f"{chart_label}\n{chart_outcome}{score_line}",
            "symbol": "diamond" if selected else "circle",
            "symbolSize": 22 if selected else 20 if current else 13 if lit else 11,
            "itemStyle": {
                "color": "#151F2C" if lit and not selected and not current else color,
                "borderColor": route_color if lit else "#0B1018",
                "borderWidth": 2 if lit else 1,
                "opacity": 1 if lit or not route else 0.85,
                "shadowColor": route_color,
                "shadowBlur": 18 if current else 7 if lit else 0,
            },
            # A node's lineStyle controls its incoming edge, not its children's edges.
            "lineStyle": {
                "color": route_color if lit else "#536173",
                "width": 3 if lit else 1,
                "opacity": 1 if lit else 0.45,
            },
            "label": {
                "color": route_color if lit else "#C0CBD6",
                "fontWeight": "bold" if lit else "normal",
            },
            "children": [],
            "value": explain_experiment(row, delivered_id, rows=rows, summary=summary)
            + (f"；{active_label}" if current else ""),
        }
    for row in rows:
        node_id = row["id"]
        parent = parents[node_id]
        # Broken/cyclic historical evidence must not create a recursive chart.
        ancestors = {node_id}
        cursor = parent
        while cursor is not None and cursor not in ancestors:
            ancestors.add(cursor)
            cursor = parents.get(cursor)
        if parent is not None and cursor is None:
            nodes[parent]["children"].append(nodes[node_id])
        else:
            roots.append(nodes[node_id])
    if len(roots) == 1:
        return roots[0]
    return {"id": "root", "name": "研究起点", "itemStyle": {"color": "#F4F7FB"}, "children": roots}


def branch_chart_spec(tree: dict[str, Any]) -> dict[str, Any]:
    return {
        "tooltip": {"trigger": "item", "formatter": "{c}"},
        "series": [
            {
                "type": "tree",
                "data": [tree],
                "top": "8%",
                "left": "5%",
                "bottom": "8%",
                "right": "5%",
                "orient": "TB",
                "symbol": "circle",
                "symbolSize": 13,
                "roam": True,
                "expandAndCollapse": True,
                "initialTreeDepth": -1,
                "emphasis": {"focus": "none"},
                "lineStyle": {"color": "#536173", "width": 1},
                "label": {"position": "top", "fontSize": 11, "color": "#EAF2FA"},
                "leaves": {"label": {"position": "bottom"}},
                "animationDurationUpdate": 300,
            }
        ],
    }


def explain_experiment(
    row: dict[str, Any],
    delivered_id: str | None,
    *,
    rows: list[dict[str, Any]] | None = None,
    summary: dict[str, Any] | None = None,
) -> str:
    """Use readable scheme names and recorded reasons in tooltips and details."""
    score = row.get("score")
    score_text = f"{score:.4f}" if isinstance(score, (int, float)) else "尚未完成"
    parent = next((item for item in rows or [] if item["id"] == row.get("parent")), None)
    if parent is None and row.get("parent"):
        parent = {"id": row["parent"]}
    basis = f"以「{experiment_label(parent)}」为对照" if parent else "研究起点"
    reason = selection_reason(row, delivered_id, rows, summary)
    return (
        f"{experiment_label(row)}｜{model_label(row)}｜{basis}｜开发集分数 {score_text}。{reason}"
    )


def score_chart_spec(rows: list[dict[str, Any]], delivered_id: str | None) -> dict[str, Any]:
    plotted = [row for row in rows if isinstance(row.get("score"), (int, float))]
    frame = pd.DataFrame(
        {
            "实验": [experiment_label(row) for row in plotted],
            "开发集分数": [row["score"] for row in plotted],
        }
    )
    delivered = next((row for row in plotted if row["id"] == delivered_id), None)
    series: dict[str, Any] = {
        "type": "line",
        "encode": {"x": "实验", "y": "开发集分数"},
        "lineStyle": {"color": "#F4F7FB", "width": 2},
        "itemStyle": {"color": "#F4F7FB"},
        "symbolSize": 7,
    }
    if delivered:
        series["markPoint"] = {
            "symbolSize": 45,
            "itemStyle": {"color": "#B8FF65"},
            "data": [{"name": "交付", "coord": [experiment_label(delivered), delivered["score"]]}],
        }
    return {
        "tooltip": {"trigger": "axis"},
        "dataset": {"source": frame},
        "grid": {"left": "12%", "right": "4%", "bottom": "22%", "top": "8%"},
        "xAxis": {"type": "category", "axisLabel": {"rotate": 50, "fontSize": 10}},
        "yAxis": {"type": "value", "min": "dataMin"},
        "series": [series],
    }
