"""Evidence-backed data for the research workspace side panels."""

from __future__ import annotations

import json
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


def experiment_rows(run_dir: Path, summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    compact_rows = summary.get("experiments") or []
    if not compact_rows:
        for path in sorted((run_dir / "experiments").glob("*.json")):
            detail = read_json(path)
            experiment_id = detail.get("experiment_id")
            if not isinstance(experiment_id, str) or not (
                experiment_id == "baseline"
                or experiment_id.startswith("tool-")
                or experiment_id.startswith("r")
            ):
                continue
            compact_rows.append(
                {
                    "id": experiment_id,
                    "round": detail.get("round"),
                    "mean_score": (detail.get("result") or {}).get("mean_score"),
                    "origin": detail.get("origin"),
                    "baseline_verdict": (detail.get("vs_baseline") or {}).get("policy_status"),
                }
            )
    for compact in compact_rows:
        experiment_id = compact.get("id")
        if not isinstance(experiment_id, str) or Path(experiment_id).name != experiment_id:
            continue
        detail = read_json(run_dir / "experiments" / f"{experiment_id}.json")
        rows.append(
            {
                "id": experiment_id,
                "round": compact.get("round"),
                "score": compact.get("mean_score"),
                "origin": compact.get("origin"),
                "verdict": compact.get("baseline_verdict"),
                "hypothesis": compact.get("hypothesis"),
                "spec": compact.get("spec") or detail.get("spec") or {},
                "parent": compact.get("hypothesis_comparator") or detail.get("previous_best_id"),
            }
        )
    return rows


def branch_tree(rows: list[dict[str, Any]], delivered_id: str | None) -> dict[str, Any] | None:
    """Attach each attempt to the idea it tested; preserve all sibling attempts."""
    if not rows:
        return None
    ids = {row["id"] for row in rows}
    nodes: dict[str, dict[str, Any]] = {}
    roots: list[dict[str, Any]] = []
    for row in rows:
        verdict = row.get("verdict")
        model = (row.get("spec") or {}).get("model") or {}
        family = {
            "logistic_regression": "逻辑回归",
            "random_forest": "随机森林",
            "hist_gradient_boosting": "梯度提升树",
        }.get(model.get("family"), "模型实验")
        actions = (row.get("spec") or {}).get("feature_actions") or []
        action = " + 特征调整" if actions else ""
        outcome = (
            "最终采用"
            if row["id"] == delivered_id
            else "达到门槛"
            if verdict == "candidate_pass"
            else "继续探索"
        )
        color = "#B8FF65" if row["id"] == delivered_id else "#F4F7FB"
        nodes[row["id"]] = {
            "name": f"{family}{action}\n{outcome} · {row['id']}",
            "itemStyle": {
                "color": color,
                "borderColor": "#0B1018",
                "opacity": 0.4 if verdict != "candidate_pass" and row["id"] != delivered_id else 1,
            },
            "children": [],
            "value": explain_experiment(row, delivered_id),
        }
    seen: set[str] = set()
    for row in rows:
        parent = row.get("parent")
        if parent in ids and parent in seen and parent != row["id"]:
            nodes[parent]["children"].append(nodes[row["id"]])
        else:
            roots.append(nodes[row["id"]])
        seen.add(row["id"])
    if len(roots) == 1:
        return roots[0]
    return {"name": "研究起点", "itemStyle": {"color": "#F4F7FB"}, "children": roots}


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
                "initialTreeDepth": 5,
                "lineStyle": {"color": "#F4F7FB", "opacity": 0.4, "width": 1},
                "label": {"position": "top", "fontSize": 11, "color": "#F4F7FB"},
                "leaves": {"label": {"position": "bottom"}},
                "animationDurationUpdate": 300,
            }
        ],
    }


def explain_experiment(row: dict[str, Any], delivered_id: str | None) -> str:
    """Give a short, factual explanation that can be read without engine vocabulary."""
    score = row.get("score")
    score_text = f"{score:.3f}" if isinstance(score, (int, float)) else "尚未完成"
    origin = {
        "baseline": "初始基线",
        "tool_search": "程序搜索",
        "proposer": "提案候选",
    }.get(row.get("origin"), "实验尝试")
    verdict = {
        "candidate_pass": "达到开发集门槛",
        "not_met": "未达到开发集门槛",
        "invalid": "证据无效",
    }.get(row.get("verdict"), "尚无通过结论")
    parent = row.get("parent")
    basis = f"基于 {parent} 继续尝试" if parent else "从研究起点开始"
    delivery = "；最终交付" if row.get("id") == delivered_id else ""
    return f"{row['id']}｜{origin}｜{basis}｜开发集分数 {score_text}｜{verdict}{delivery}"


def score_chart_spec(rows: list[dict[str, Any]], delivered_id: str | None) -> dict[str, Any]:
    plotted = [row for row in rows if isinstance(row.get("score"), (int, float))]
    frame = pd.DataFrame(
        {"实验": [row["id"] for row in plotted], "开发集分数": [row["score"] for row in plotted]}
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
            "data": [{"name": "交付", "coord": [delivered_id, delivered["score"]]}],
        }
    return {
        "tooltip": {"trigger": "axis"},
        "dataset": {"source": frame},
        "grid": {"left": "12%", "right": "4%", "bottom": "22%", "top": "8%"},
        "xAxis": {"type": "category", "axisLabel": {"rotate": 50, "fontSize": 10}},
        "yAxis": {"type": "value", "min": "dataMin"},
        "series": [series],
    }
