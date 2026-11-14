"""Research workspace panels rendered from local run evidence."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from budgetlab.ui.insights import (
    branch_activity,
    branch_chart_spec,
    branch_tree,
    cycle_status,
    experiment_label,
    experiment_rows,
    explain_experiment,
    model_label,
    read_json,
    read_jsonl,
    score_chart_spec,
    token_ledger,
)


def render_token_panel(run_dir: Path | None) -> None:
    st.markdown("#### Token 用量")
    if run_dir is None:
        with st.container(key="token_meter"):
            st.markdown("## —")
            st.caption("选择研究后查看")
        return
    ledger = token_ledger(run_dir)
    used, unknown, limit = ledger["used"], ledger["unknown"], ledger["limit"]
    with st.container(key="token_meter"):
        st.markdown(f"## {used:,}")
        st.caption(f"预算 {limit:,} · 未知 {unknown:,}")
        if limit:
            st.progress(min((used + unknown) / limit, 1.0), text="已记 + 未知 / 预算")
        elif ledger["source"] == "scripted":
            st.caption("脚本化提案 · 无 LLM 请求")
    if unknown:
        st.warning("有请求未返回完整 usage；未知用量单列，未当作 0 Token。")
    with st.expander("查看过程用量"):
        for label, role in (("提案", "proposer"), ("审查", "critic")):
            role_data = ledger["by_role"].get(role, {})
            st.write(f"{label} · {role_data.get('tokens', 0):,} Token")
        st.caption(
            "只统计本次研究的提案和审查。CSV 协议起草和开放问答的 Token 另记在 ui_state/；"
            "程序实验和快捷问答不调用 LLM。"
        )
    if ledger["by_round"]:
        with st.expander(f"逐次调用明细（{len(ledger['by_round'])}）"):
            st.dataframe(ledger["by_round"], hide_index=True, alt="每轮提案和审查的 Token 使用记录")


def render_result_panel(run_dir: Path | None) -> None:
    st.markdown("#### 验证结果")
    if run_dir is None:
        st.caption("选择研究后查看")
        return
    summary = read_json(run_dir / "summary.json")
    evaluation = read_json(run_dir / "final_evaluation.json")
    events = read_jsonl(run_dir / "events.jsonl")
    rows = experiment_rows(run_dir, summary)
    score = summary.get("delivered_dev_score")
    if score is None and rows:
        score = max(
            (row["score"] for row in rows if isinstance(row.get("score"), (int, float))),
            default=None,
        )
    st.metric(
        "交付开发集分数" if summary else "当前探索最优分",
        f"{score:.3f}" if score is not None else "—",
    )
    if rows:
        st.echarts_chart(
            score_chart_spec(rows, summary.get("delivered_experiment_id")),
            height=240,
            alt="各次实验的开发集分数，荧光绿点表示交付方案",
        )
        st.caption("开发集交叉验证 · 亮色为交付方案")
    st.markdown("##### 研究闭环")
    stages = cycle_status(events)
    for index, (label, count) in enumerate(stages, start=1):
        st.markdown(f"`{index:02d}`  **{label}**  ·  {count} 条记录")
    if summary:
        st.caption(f"确认状态：{summary.get('confirmation_status', '未知')}")
        deltas = summary.get("confirmation_deltas") or []
        if deltas:
            st.caption("新切分复核差值：" + " / ".join(f"{value:+.3f}" for value in deltas))
    if evaluation:
        st.metric("最终测试分数", f"{evaluation.get('holdout_score'):.3f}")
    else:
        state = read_json(run_dir / "ui_final_test.json")
        if state.get("status") == "running":
            st.caption("最终测试：正在独立测试集上检验模型……")
        elif state.get("status") == "failed":
            st.caption("最终测试：未完成，可在研究结论中查看原因。")
        else:
            st.caption("最终测试：尚未完成。独立测试集不参与训练或选模型。")


def render_branch_map(run_dir: Path | None, *, running: bool | None = None) -> None:
    st.subheader("研究路径")
    st.caption("节点末行是开发集分数（越高越好） · 悬停或选择方案查看入选原因")
    if run_dir is None:
        st.info("选择左侧研究记录，或启动一次研究后查看分岔。")
        return
    summary = read_json(run_dir / "summary.json")
    events = read_jsonl(run_dir / "events.jsonl")
    rows = experiment_rows(run_dir, summary, events)
    active_id, active_label = branch_activity(
        run_dir, events, rows, finished=bool(summary), running=running
    )
    tree = branch_tree(
        rows, summary.get("delivered_experiment_id"), active_id, active_label, summary=summary
    )
    if tree is None:
        st.info("当前还没有可展示的实验，运行开始后会出现分岔。")
        return
    if active_id:
        active_row = next(row for row in rows if row["id"] == active_id)
        st.caption(f"🔵 {active_label} · {experiment_label(active_row)} · 路线每 2 秒更新")
    elif summary:
        st.caption("研究已结束 · 绿色菱形为最终采用方案，绿色空心圆为其对照步骤")
    elif running is False or any(event.get("event_type") == "run_failed" for event in events):
        st.caption("研究已停止 · 执行高亮已熄灭")
    else:
        st.caption(active_label or "当前没有执行中的实验 · 等待下一步")
    st.echarts_chart(
        branch_chart_spec(tree),
        height=540,
        key=f"branch-map-{run_dir.name}",
        alt="研究路径：蓝色为当前执行，绿色菱形为最终采用，空心圆为对照步骤，灰色为未入选方案",
    )
    st.caption("蓝色：正在执行 · 绿色菱形：最终采用 · 空心圆：对照步骤 · 灰色：未入选/其他候选")
    st.caption("灰色不代表失败。先从有足够提升的候选中按开发分数挑选，再复核；通过后才最终采用。")
    st.caption("连线表示方案之间的对照关系，绿色上游节点并不是多个最终模型。")
    chosen = st.selectbox(
        "查看节点说明",
        [row["id"] for row in rows],
        format_func=lambda experiment_id: next(
            f"{experiment_label(row)} · {model_label(row)}"
            for row in rows
            if row["id"] == experiment_id
        ),
        key=f"branch-detail-{run_dir.name}",
    )
    row = next(row for row in rows if row["id"] == chosen)
    st.info(
        explain_experiment(row, summary.get("delivered_experiment_id"), rows=rows, summary=summary)
    )
    with st.expander("技术信息与原始依据"):
        st.caption(
            f"内部编号：{row['id']}"
            + (f" · 对照编号：{row['parent']}" if row.get("parent") else "")
        )
        st.caption("r 表示研究轮次，c 表示该轮实际执行的方案顺序；编号仅用于追溯原始记录。")
        if row.get("hypothesis"):
            st.write(f"原始假设：{row['hypothesis']}")
