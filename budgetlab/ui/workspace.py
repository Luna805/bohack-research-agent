"""Research workspace panels rendered from local run evidence."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from budgetlab.ui.insights import (
    branch_chart_spec,
    branch_tree,
    cycle_status,
    experiment_rows,
    explain_experiment,
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


def render_evidence_files(run_dir: Path | None) -> None:
    """Preview only allowlisted run artifacts, never sealed data or model files."""
    st.markdown("#### 证据文件")
    if run_dir is None or not run_dir.is_dir():
        st.write("开始研究后在这里查看证据。")
        return
    names = (
        "protocol.json",
        "contract.json",
        "eda.json",
        "events.jsonl",
        "budget.json",
        "summary.json",
        "final_evaluation.json",
        "report.md",
    )
    paths = [run_dir / name for name in names if (run_dir / name).is_file()]
    experiments = run_dir / "experiments"
    if experiments.is_dir():
        paths.extend(sorted(experiments.glob("*.json"))[-5:])
    if not paths:
        st.write("正在生成证据文件…")
        return
    st.caption(f"{len(paths)} 个可查看文件")
    for path in paths:
        label = str(path.relative_to(run_dir)).replace("\\", "/")
        with st.expander(f"↗ {label}"):
            content = path.read_text(encoding="utf-8", errors="replace")
            st.code(content[:4000], language="json" if path.suffix in {".json", ".jsonl"} else None)
            if len(content) > 4000:
                st.caption("预览前 4,000 字符")


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
            alt="各次实验的开发集分数，蓝点表示交付方案",
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
        st.metric("Holdout（仅一次）", f"{evaluation.get('holdout_score'):.3f}")
    else:
        st.caption("Holdout：尚未评测。")


def render_branch_map(run_dir: Path | None) -> None:
    with st.popover("图例与操作"):
        st.write("蓝色：最终交付；深灰：达到门槛；淡色：其他尝试。")
        st.write("悬停节点看结果，下方选择实验可看完整依据。")
    if run_dir is None:
        st.info("打开一条研究记录，或启动一次研究后查看分岔。")
        return
    summary = read_json(run_dir / "summary.json")
    rows = experiment_rows(run_dir, summary)
    tree = branch_tree(rows, summary.get("delivered_experiment_id"))
    if tree is None:
        st.info("当前还没有可展示的实验，运行开始后会出现分岔。")
        return
    st.echarts_chart(
        branch_chart_spec(tree),
        height=540,
        alt="研究实验分岔，蓝色节点为交付方案，深灰节点为通过门槛的方案",
    )
    chosen = st.selectbox(
        "查看节点说明",
        [row["id"] for row in rows],
        format_func=lambda experiment_id: f"实验 {experiment_id}",
        key=f"branch-detail-{run_dir.name}",
    )
    row = next(row for row in rows if row["id"] == chosen)
    st.info(explain_experiment(row, summary.get("delivered_experiment_id")))
    if row.get("hypothesis"):
        with st.expander("查看原始假设"):
            st.write(row["hypothesis"])
