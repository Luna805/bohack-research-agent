"""Zero-token answers derived from saved run evidence."""

from __future__ import annotations

from .evidence import EvidenceStore

QUICK_QUESTIONS = {
    "score": "提升了多少？",
    "cost": "花了多少资源？",
    "choice": "为什么选择这个结果？",
}


def answer_quick(question_id: str, run_id: str, store: EvidenceStore) -> dict:
    summary = store.get_summary(run_id)
    evidence = [{"run_id": run_id, "kind": "summary", "ref_id": "summary.json"}]
    if question_id == "score":
        answer = (
            f"开发集基线 {summary.get('baseline_score')}，交付模型 "
            f"{summary.get('delivered_dev_score')}；确认状态："
            f"{summary.get('confirmation_status')}。"
        )
    elif question_id == "cost":
        llm = summary.get("llm") or {}
        answer = (
            f"LLM 请求 {llm.get('requests', 0)} 次、Token {llm.get('tokens', 0)}；"
            f"墙钟时间 {summary.get('wall_seconds')} 秒。"
        )
    elif question_id == "choice":
        answer = (
            f"最终交付实验 {summary.get('delivered_experiment_id')}，"
            f"确认状态 {summary.get('confirmation_status')}。"
            "具体裁决请展开实验和确认记录。"
        )
    else:
        raise ValueError("Unknown quick question")
    return {"answer": answer, "evidence": evidence, "source": "quick"}
