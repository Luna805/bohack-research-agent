"""Pure presentation helpers for the research page."""

from __future__ import annotations

import json
from pathlib import Path

EVENT_STAGES = {
    "protocol_accepted": ("协议", "研究协议已确认"),
    "profile_written": ("数据", "数据画像完成"),
    "baseline_completed": ("基线", "基线训练完成"),
    "calibration_completed": ("基线", "提升门槛已标定"),
    "contract_frozen": ("基线", "实验契约已冻结"),
    "candidate_rejected": ("提案", "候选方案被拒绝"),
    "candidate_selected": ("提案", "候选方案已选中"),
    "llm_call_completed": ("提案", "本轮提出两个候选"),
    "llm_call_failed": ("提案", "本轮提案未完成"),
    "experiment_completed": ("实验", "实验训练完成"),
    "experiment_failed": ("实验", "实验运行失败"),
    "evaluation_recorded": ("裁决", "实验裁决已记录"),
    "tool_search_started": ("调整", "规则搜索已启动"),
    "tool_search_completed": ("调整", "规则搜索已完成"),
    "direction_changed": ("调整", "研究方向已调整"),
    "stop_decided": ("收尾", "停止原因已确定"),
    "confirmation_completed": ("收尾", "新切分复核完成"),
    "delivery_frozen": ("收尾", "交付模型已冻结"),
    "run_terminal": ("收尾", "研究已结束"),
}


def event_card(event: dict) -> dict | None:
    kind = event.get("event_type")
    if kind not in EVENT_STAGES:
        return None
    if kind in {"llm_call_completed", "llm_call_failed"} and (
        (event.get("details") or {}).get("role") != "proposer"
    ):
        return None
    stage, title = EVENT_STAGES[kind]
    details = event.get("details") or {}
    artifact = event.get("artifact_ref")
    note = event.get("reason_code") or ""
    if kind == "protocol_accepted":
        note = f"可用字段 {details.get('approved_features', '?')} 个"
        excluded = details.get("excluded_features") or []
        if excluded:
            note += f"；排除 {', '.join(map(str, excluded))}"
    elif kind in {"experiment_completed", "experiment_failed"}:
        note = str(artifact or event.get("action_id") or note)
    elif kind == "candidate_selected":
        note = f"{details.get('candidate_id', '?')} → {details.get('experiment_id', '?')}"
    elif kind == "evaluation_recorded":
        verdict = details.get("baseline_verdict") or "未裁决"
        note = f"裁决：{verdict}；{'刷新最优分' if details.get('new_best') else '未刷新最优分'}"
    elif kind in {"llm_call_completed", "llm_call_failed"}:
        source = details.get("source") or "unknown"
        note = "脚本化提案（0 Token）" if source == "scripted" else f"提案来源：{source}"
        if kind == "llm_call_failed" and details.get("error"):
            note += f"；{details['error']}"
    elif kind == "run_terminal":
        note = str(details.get("stop_reason") or note)
    return {
        "seq": event.get("seq"),
        "stage": stage,
        "title": title,
        "note": note,
        "artifact": artifact,
        "raw": event,
    }


def artifact_preview(run_dir: Path, card: dict) -> list[str]:
    """Describe saved evidence without asking viewers to read ledger JSON."""
    reference = card.get("artifact")
    if not isinstance(reference, str) or not reference.endswith(".json"):
        return []
    path = (run_dir / reference).resolve()
    if not path.is_relative_to(run_dir.resolve()) or not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if reference.startswith("experiments/"):
        result = payload.get("result") or {}
        model = (payload.get("spec") or {}).get("model") or {}
        lines = [f"模型：{model.get('family', '未知')}"]
        if result.get("mean_score") is not None:
            lines.append(f"开发集分数：{result['mean_score']:.3f}")
        hypothesis = payload.get("hypothesis")
        if isinstance(hypothesis, dict) and hypothesis.get("statement"):
            lines.append(f"假设：{hypothesis['statement']}")
        return lines
    if reference.startswith("rounds/"):
        candidates = (payload.get("proposal") or {}).get("candidates") or []
        return [
            f"{candidate.get('candidate_id', '候选')}："
            f"{(candidate.get('hypothesis') or {}).get('statement', '未写假设')}"
            for candidate in candidates
        ]
    if reference.startswith("llm/proposer-"):
        return [
            f"{candidate.get('candidate_id', '候选')}："
            f"{(candidate.get('hypothesis') or {}).get('statement', '未写假设')}"
            for candidate in payload.get("candidates") or []
        ]
    return []


def load_matrix(results_root: Path) -> tuple[Path, list[dict], bool] | None:
    """Choose the latest formal matrix, falling back to development data."""
    for pattern, formal in (("final-*", True), ("dev-*", False)):
        files = sorted(results_root.glob(f"{pattern}/aggregate.json"), reverse=True)
        for path in files:
            rows = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(rows, list):
                return path, rows, formal
    return None


def trajectory_rows(summary: dict) -> list[dict]:
    rows = []
    for point in summary.get("trajectory") or []:
        score = point.get("best_score_after")
        if score is not None:
            rows.append(
                {
                    "实验": len(rows) + 1,
                    "最优分": score,
                    "累计 Token": point.get("llm_tokens_so_far", 0),
                    "累计秒数": point.get("elapsed_seconds", 0),
                }
            )
    return rows
