"""Workbench page for one BudgetLab research: chat on the left, run files on the right.

Start with ``streamlit run budgetlab/ui/app.py`` from the repository root. The page only reads
run artifacts (and starts runs, each followed by its one-time final test, in the background);
numbers and verdicts
come from the program, never from the page.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime
from functools import partial
from importlib import import_module
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
import streamlit as st
import yaml

from budgetlab.data import prepare_task
from budgetlab.ledger import EventLedger
from budgetlab.qa.evidence import EvidenceStore
from budgetlab.qa.faq import QUICK_QUESTIONS, answer_quick
from budgetlab.tasks.csv_task import (
    CsvTaskError,
    config_for_upload,
    development_profile,
    read_csv_any,
    register_csv_task,
    validate_csv_for_task,
)
from budgetlab.ui.artifacts import (
    CURVE,
    GROUPS,
    answer_links,
    curve_rows,
    resolve_artifact,
    run_dir,
)
from budgetlab.ui.insights import experiment_label, experiment_rows, read_json, token_ledger
from budgetlab.ui.llm import llm_overrides, llm_problem, llm_settings, log_call, research_config
from budgetlab.ui.presentation import artifact_preview, load_matrix, trajectory_rows
from budgetlab.ui.row_table import row_table
from budgetlab.ui.workbench import (
    MODEL_NAMES,
    clock,
    describe_spec,
    experiment_table,
    history_rows,
    list_entries,
    progress,
    project_groups,
    round_started_at,
    run_strategy,
    size_text,
    sort_entries,
    when_text,
)
from budgetlab.ui.workspace import render_branch_map

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "runs"
DATA = ROOT / "data"
STORE = EvidenceStore(RUNS, ROOT / "results")
TASKS = {
    "Bank Marketing": ("bank_marketing", ROOT / "configs/bank_marketing.yaml"),
    "Adult Income": ("adult", ROOT / "configs/adult.yaml"),
}
LLM_CALLS = ROOT / "ui_state" / "llm_calls.jsonl"
QA_CALLS = ROOT / "ui_state" / "qa_calls.jsonl"
QA_LIMITS = {"requests": 20, "tokens": 50_000}  # per page session (INTERFACES 8.4)
WS_TABS = ["文件", "查看器", "研究路径", "得分曲线"]
PANEL_TABS = ["实验", "Token", "验证"]
EXAMPLES = {
    "Bank Marketing": "电话营销：预测客户是否订阅定期存款",
    "Adult Income": "人口普查：预测年收入是否超过 5 万美元",
}
DEMO_CSV = ROOT / "examples" / "student_risk" / "student_risk.csv"


def fmt(value: object, digits: int = 4) -> str:
    return f"{value:.{digits}f}" if isinstance(value, int | float) else "—"


def final_test_text(evaluation: dict) -> str:
    text = f"独立测试集分数：{fmt(evaluation.get('holdout_score'))}"
    interval = evaluation.get("holdout_ci95")
    if interval and len(interval) == 2:
        text += f"（95% 区间 {fmt(interval[0])}–{fmt(interval[1])}）"
    return text + "，最终测试已完成"


def read_events(run_dir: Path) -> list[dict]:
    path = run_dir / "events.jsonl"
    if not path.is_file():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # writer may be in the middle of the last line
    return events


def protocol_card(task_id: str) -> dict:
    if task_id.startswith("upload-"):
        path = DATA / "uploads" / task_id / "card.yaml"
    else:
        path = ROOT / "budgetlab" / "tasks" / "cards" / f"{task_id}.yaml"
    card = yaml.safe_load(path.read_text(encoding="utf-8"))
    return card


def launch(task_id: str, config_path: Path) -> dict:
    RUNS.mkdir(exist_ok=True)
    before = {path.name for path in RUNS.iterdir() if path.is_dir()}
    # Page runs reuse the official matrix's LLM budget and settings; shared configs stay put.
    base = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config_path = ROOT / "ui_state" / "configs" / f"{task_id}-llm.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.safe_dump(research_config(base, ROOT), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    command = [
        sys.executable,
        "-m",
        "budgetlab.ui.research_job",
        "--config",
        str(config_path),
        "--system",
        "budgetlab",
        "--proposer",
        "llm",
        "--runs-root",
        str(RUNS),
        "--data-root",
        str(DATA),
    ]
    log_path = ROOT / "ui_state" / "research.log"
    log_path.parent.mkdir(exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    return {
        "pid": process.pid,
        "process": process,
        "before": sorted(before),
        "run_id": None,
        "task_id": task_id,
        "proposer": "llm",
        "auto_final_test": True,
    }


def locate_run(job: dict) -> Path | None:
    if job.get("run_id"):
        return RUNS / job["run_id"]
    before = set(job["before"])
    newer = sorted(
        (path for path in RUNS.iterdir() if path.is_dir() and path.name not in before),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if newer:
        job["run_id"] = newer[0].name
        return newer[0]
    return None


def evaluate_run(run_id: str) -> str | None:
    """Run the one-time final test of a frozen model; return a user-facing error."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "budgetlab.ui.research_job",
            "--evaluate-run-id",
            run_id,
            "--runs-root",
            str(RUNS),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stderr[-1000:] if result.returncode else None


def own_job(run_id: str) -> dict | None:
    """The page's background job when it is the one that produced ``run_id``."""
    job = st.session_state.get("job")
    job_dir = locate_run(job) if job else None
    return job if job_dir is not None and job_dir.name == run_id else None


def final_test_pending(run_id: str) -> bool:
    """True while the background job is still testing the frozen model."""
    if STORE.get_final_evaluation(run_id):
        return False
    job = own_job(run_id)
    if job and job.get("auto_final_test") and job["process"].poll() is None:
        return True
    return read_json(RUNS / run_id / "ui_final_test.json").get("status") == "running"


def show_final_test(run_id: str, *, key: str) -> None:
    """Explain the final check; only legacy runs and failures need a manual action."""
    job = own_job(run_id)
    st.markdown("**最终测试**")
    st.caption(
        "用训练和选模型时未使用的独立测试集，检验最终模型对新样本的表现。"
        "每次研究仅测试一次，结果不再用于调参。"
    )
    evaluation = STORE.get_final_evaluation(run_id)
    state = read_json(RUNS / run_id / "ui_final_test.json")
    status = "completed" if evaluation else state.get("status")
    if job and job.get("auto_final_test") and status in {"completed", "failed"}:
        if job.get("final_test_seen") != status:
            job["final_test_seen"] = status
            st.rerun()
    if evaluation:
        st.write(final_test_text(evaluation))
        return
    process_running = job is not None and job["process"].poll() is None
    if (job and job.get("auto_final_test") and process_running) or (
        status == "running" and job is None
    ):
        st.info("模型已确定，正在自动完成最终测试……")
        return
    interrupted = status in {"running", "failed"} or (job and job.get("auto_final_test"))
    if interrupted:
        st.warning("模型研究已完成，但最终测试尚未完成。可在下方查看原因并重试。")
    else:
        st.info("这条旧研究记录尚未进行最终测试。新启动的研究会自动完成这一步。")
    with st.expander("查看原因与重试" if interrupted else "补充这条旧记录的最终测试"):
        if state.get("error"):
            st.error(state["error"])
        st.caption("仅测试已经确定的模型，不会重新训练或修改研究方案。")
        if st.button("重试最终测试" if interrupted else "测试已确定的模型", key=key):
            with st.spinner("正在测试最终模型……"):
                error = evaluate_run(run_id)
            if error:
                st.error(error)
            else:
                st.rerun()


def reset_task_draft() -> None:
    for key in (
        "request",
        "upload",
        "custom_task",
        "upload-target",
        "upload-positive",
        "upload-time",
        "upload-metric",
        "upload-demo-card",
    ):
        st.session_state.pop(key, None)


@st.cache_data(ttl=3600, max_entries=8)
def upload_frame(path: str) -> pd.DataFrame:
    return read_csv_any(Path(path))


def draft_with_agent(
    upload: dict[str, str], csv_path: Path, target_column: str, positive_label: str
) -> dict | None:
    """Ask A's protocol agent for a draft; it only sees development rows, never the holdout."""
    from budgetlab.agents.protocol_agent import ProtocolAgent, build_protocol_context

    try:
        columns, profile = development_profile(csv_path, target_column, positive_label)
        context = build_protocol_context(upload["request"], columns, profile)
        outcome = ProtocolAgent(llm_settings(ROOT)).draft(context)
    except Exception as exc:
        st.error(f"协议 Agent 没能起草：{type(exc).__name__}: {exc}。请逐列手动确认。")
        return None
    log_call(LLM_CALLS, "protocol", outcome, upload=upload["digest"], target=target_column)
    if outcome.output is None:
        st.error(f"协议 Agent 调用失败：{outcome.error}。请逐列手动确认。")
        return None
    draft = outcome.output.model_dump()
    draft["tokens"] = outcome.usage.llm_tokens + outcome.unknown.llm_tokens
    return draft


def show_upload_protocol(upload: dict[str, str], llm_on: bool) -> None:
    """Let a person confirm every CSV field before the adapter registers a task."""
    csv_path = Path(upload["path"])
    with st.chat_message("assistant"):
        if llm_on:
            st.write(
                "已收到 CSV。先选目标列和正类，再让协议 Agent 起草每个字段能否在预测时使用；"
                "最后由你逐列确认。"
            )
        else:
            st.write(
                "已收到 CSV。先确定预测目标和时点，再逐列确认哪些字段在预测时可用。未使用 LLM。"
            )
        try:
            frame = upload_frame(str(csv_path))
        except Exception as exc:
            st.error(f"无法读取这个 CSV：{type(exc).__name__}: {exc}")
            return
        if frame.empty:
            st.error("CSV 里没有数据行")
            return
        st.caption(f"{len(frame):,} 行 · {len(frame.columns)} 列 · {upload['filename']}")
        demo_path = ROOT / "examples" / "student_risk" / "student_risk.csv"
        if (
            demo_path.is_file()
            and upload["digest"] == hashlib.sha256(demo_path.read_bytes()).hexdigest()[:16]
        ):
            st.info(
                "识别到仓库自带的学生预警演示数据。可载入 C 编写的人工标准协议，再由你核对确认。"
            )
            if st.button("载入演示协议（人工标准答案）"):
                answer_key = yaml.safe_load(
                    (demo_path.parent / "card.yaml").read_text(encoding="utf-8")
                )
                st.session_state["upload-demo-card"] = answer_key
                st.session_state["upload-target"] = answer_key["target"]["column"]
                st.session_state["upload-positive"] = answer_key["target"]["positive_label"]
                st.session_state["upload-time"] = answer_key["prediction_time"]
                st.session_state["upload-metric"] = answer_key.get("primary_metric", "f1_macro")
                st.session_state.pop(
                    f"upload-fields-{upload['digest']}-{answer_key['target']['column']}", None
                )
                st.rerun()
        target_column = st.selectbox("目标列", list(frame.columns), key="upload-target")
        reasons = validate_csv_for_task(csv_path, target_column)
        if reasons:
            for reason in reasons:
                st.error(reason)
            return
        values = sorted(frame[target_column].dropna().astype(str).str.strip().unique().tolist())
        positive_label = st.selectbox("哪一个值代表正类？", values, key="upload-positive")
        draft_key = f"upload-llm-draft-{upload['digest']}-{target_column}-{positive_label}"
        draft = st.session_state.get(draft_key)
        if llm_on and draft is None:
            if st.button("让协议 Agent 起草字段可用性（LLM）", type="primary"):
                with st.spinner("协议 Agent 正在阅读开发数据的字段画像……"):
                    draft = draft_with_agent(upload, csv_path, target_column, positive_label)
                if draft is not None:
                    st.session_state[draft_key] = draft
                    if not st.session_state.get("upload-time"):
                        st.session_state["upload-time"] = draft["prediction_time"]
                    st.session_state["upload-metric"] = draft["primary_metric"]
                    st.rerun()
        if draft is not None:
            st.info(
                f"下表预填了协议 Agent 的草稿（LLM，{draft['tokens']:,} Token）。"
                "它只看了开发数据的字段画像，没有看独立测试集。请逐列核对后再确认。"
            )
            if draft["target_column"] != target_column:
                st.warning(f"Agent 认为目标列是 {draft['target_column']}，请核对。")
            for question in draft.get("questions_for_user") or []:
                st.write(f"❓ {question}")
        prediction_time = st.text_input(
            "预测发生在什么时候？", placeholder="例如：拨打电话之前", key="upload-time"
        )
        metric = st.selectbox("评估指标", ["f1_macro", "accuracy", "roc_auc"], key="upload-metric")
        answer_key = st.session_state.get("upload-demo-card")
        answer_fields = {field["name"]: field for field in (answer_key or {}).get("fields", [])}
        agent_fields = {field["name"]: field for field in (draft or {}).get("fields", [])}
        if answer_key and draft:
            from budgetlab.agents.protocol_agent import DraftProtocol, score_draft

            draft_model = DraftProtocol(**{k: v for k, v in draft.items() if k != "tokens"})
            score = score_draft(draft_model, answer_key)
            missed = [error["name"] for error in score["errors"] if error["got"] == "available"]
            st.write(
                f"**协议 Agent 对照标准答案：** {score['fields_correct']}/{score['fields_total']}"
                f" 个字段一致" + (f"；漏排除 {', '.join(missed)}" if missed else "")
            )
        source = "card" if answer_key else ("llm" if draft else "manual")
        fields = []
        for column in frame.columns:
            if column == target_column:
                continue
            answer = answer_fields.get(column) if answer_key else None
            agent = agent_fields.get(column, {})
            fields.append(
                {
                    "字段": column,
                    "可用性": (answer or agent).get("availability", "available"),
                    "原因": (answer or {}).get("note") or agent.get("reason", ""),
                }
            )
        edited = st.data_editor(
            pd.DataFrame(fields),
            hide_index=True,
            disabled=["字段"],
            column_config={
                "可用性": st.column_config.SelectboxColumn(
                    "可用性", options=["available", "post_outcome", "identifier"], required=True
                )
            },
            key=f"upload-fields-{upload['digest']}-{target_column}-{source}",
            alt="逐列确认预测时的字段可用性",
        )
        st.caption("available＝预测时已知；post_outcome＝结果出现后才知道；identifier＝标识列。")
        available_count = sum(row["可用性"] == "available" for row in edited.to_dict("records"))
        if available_count < 1:
            st.warning("至少需要 1 个预测时可用的特征；请调整字段，或更换数据。")
        confirmed = st.checkbox(
            "我确认目标、正类、预测时点和每个字段的可用性", key="upload-confirmed"
        )
        if st.button(
            "确认协议并准备数据",
            disabled=not confirmed or not prediction_time.strip() or available_count < 1,
        ):
            card = {
                "title": f"CSV 任务：{upload['filename']}",
                "business_question": upload["request"],
                "prediction_time": prediction_time.strip(),
                "target": {"column": target_column, "positive_label": positive_label},
                "primary_metric": metric,
                "fields": [
                    {"name": row["字段"], "availability": row["可用性"], "note": row["原因"]}
                    for row in edited.to_dict("records")
                ],
            }
            draft_key = hashlib.sha256(
                json.dumps(card, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()[:10]
            draft_dir = ROOT / "ui_state" / "protocols" / upload["digest"] / draft_key
            draft_ledger = EventLedger(f"upload-draft-{draft_key}", draft_dir)
            draft_ledger.write_artifact("draft_protocol.json", card)
            draft_ledger.append("protocol_drafted", artifact_ref="draft_protocol.json")
            if draft is not None:
                draft_ledger.write_artifact("agent_draft_protocol.json", draft)
                draft_ledger.append("agent_draft_saved", artifact_ref="agent_draft_protocol.json")
            try:
                task_id = register_csv_task(csv_path, card, DATA)
                prepare_task(task_id, DATA)
            except CsvTaskError as exc:
                for reason in exc.reasons:
                    st.error(reason)
                return
            except Exception as exc:
                st.error(f"数据准备失败：{type(exc).__name__}: {exc}")
                return
            base = yaml.safe_load(
                (ROOT / "configs/bank_marketing.yaml").read_text(encoding="utf-8")
            )
            generated = config_for_upload(task_id, base)
            config_path = ROOT / "ui_state" / "configs" / f"{task_id}.yaml"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                yaml.safe_dump(generated, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
            st.session_state["custom_task"] = (task_id, str(config_path))
            st.session_state.pop("upload", None)
            st.rerun()


def ask_open_question(run_id: str, question: str, thread: list[dict]) -> dict:
    """One metered call to A's QA agent; numbers and citations are checked by code."""
    if not llm_on:
        return {"question": question, "note": "开放问答需要 LLM；现在可以用上面的快捷问题。"}
    usage = st.session_state.setdefault("qa_usage", {"requests": 0, "tokens": 0})
    if usage["requests"] >= QA_LIMITS["requests"] or usage["tokens"] >= QA_LIMITS["tokens"]:
        return {
            "question": question,
            "note": f"本次会话的问答额度已用完（{QA_LIMITS['requests']} 次请求或 "
            f"{QA_LIMITS['tokens']:,} Token）。",
        }
    from budgetlab.qa.agent import answer_open

    history = [
        {"question": turn["question"], "answer": turn["answer"]}
        for turn in thread
        if turn.get("answer")
    ]
    with st.spinner("正在根据本次研究的证据回答……"):
        try:
            answer, outcome = answer_open(
                question, run_id, history, store=STORE, settings=llm_settings(ROOT)
            )
        except Exception as exc:
            return {"question": question, "error": f"{type(exc).__name__}: {exc}"}
    log_call(QA_CALLS, "qa", outcome, run_id=run_id, question=question[:300])
    tokens = outcome.usage.llm_tokens + outcome.unknown.llm_tokens
    usage["requests"] += max(outcome.usage.llm_requests, 1)
    usage["tokens"] += tokens
    if outcome.output is None:
        return {"question": question, "error": outcome.error}
    return {"question": question, **answer.model_dump(), "tokens": tokens}


# ------------------------------------------------------------------------------ viewer

VIEWER_TEXT_LIMIT = 50_000


def show_score_curve(run_id: str, summary: dict) -> None:
    """Each experiment's own development score and the best score so far."""
    import altair as alt

    rows = curve_rows(summary)
    metric = summary.get("primary_metric") or "score"
    st.markdown(f"**得分曲线（{metric}）**")
    st.caption(
        "开发集交叉验证分数，越高越好。圆点是每个实验自己的分数，阶梯线是截至该实验的最优分，"
        "虚线是基线，菱形是最终交付的实验。数据来自 summary.json 的 trajectory"
        "（研究进行中时取自 experiments/ 里已完成的实验）。"
    )
    if not rows:
        st.info("还没有完成的实验，暂时画不出得分曲线。")
        return
    frame = pd.DataFrame(rows)
    x = alt.X("序号:Q", title="实验序号", axis=alt.Axis(tickMinStep=1))
    y_scale = alt.Scale(zero=False)
    tooltip = ["实验", "来源", "轮次", "本实验分数", "历史最优", "累计 Token"]
    layers = [
        alt.Chart(frame)
        .mark_line(interpolate="step-after")
        .encode(x=x, y=alt.Y("历史最优:Q", title=metric, scale=y_scale), tooltip=tooltip),
        alt.Chart(frame)
        .mark_circle(size=70)
        .encode(
            x=x,
            y=alt.Y("本实验分数:Q", title=metric, scale=y_scale),
            color=alt.Color("来源:N", title="来源"),
            tooltip=tooltip,
        ),
    ]
    if summary.get("baseline_score") is not None:
        baseline = pd.DataFrame({"基线": [summary["baseline_score"]]})
        layers.append(alt.Chart(baseline).mark_rule(strokeDash=[4, 4]).encode(y="基线:Q"))
    delivered = frame[frame["实验"] == summary.get("delivered_experiment_id")]
    if not delivered.empty:
        layers.append(
            alt.Chart(delivered)
            .mark_point(shape="diamond", size=220, filled=False, strokeWidth=2)
            .encode(x=x, y="本实验分数:Q", tooltip=tooltip)
        )
    st.altair_chart(alt.layer(*layers), width="stretch", alt=f"{run_id} 每个实验的分数与历史最优分")
    st.dataframe(frame, hide_index=True)


def render_artifact(run_id: str, relative: str) -> None:
    """One run file, read-only: JSON tree, rendered Markdown, CSV table or plain text."""
    base = run_dir(RUNS, run_id)
    if base is None:
        st.error("找不到这次研究。")
        return
    if relative == CURVE:
        show_score_curve(run_id, curve_summary(base))
        return
    path = resolve_artifact(RUNS, run_id, relative)
    if path is None:
        st.error("只能打开这次研究目录里已存在的文本证据文件（json、md、log、csv 等）。")
        return
    st.code(str(path), language=None)
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        st.info("这个文件是空的。")
        return
    st.download_button("下载原文件", text, file_name=path.name, key=f"download-{run_id}-{relative}")
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            st.code(text[-VIEWER_TEXT_LIMIT:], language=None)
            return
        for line in artifact_preview(base, {"artifact": relative}):
            st.write(line)
        st.json(payload, expanded=2)
    elif suffix == ".md":
        st.markdown(text)
    elif suffix == ".csv":
        st.dataframe(pd.read_csv(path, nrows=5000), hide_index=True)
    else:
        if len(text) > VIEWER_TEXT_LIMIT:
            st.caption(f"文件较长，只显示最后 {VIEWER_TEXT_LIMIT:,} 个字符；完整内容请下载。")
        st.code(text[-VIEWER_TEXT_LIMIT:], language="json" if suffix == ".jsonl" else None)


def show_artifact_page(run_id: str, relative: str) -> None:
    """Full-page view of one run file, for links opened in a new tab."""
    st.title("研究证据")
    st.caption(f"研究 {run_id} · 只读")
    if relative != CURVE:
        st.subheader(relative)
    render_artifact(run_id, relative)


# ------------------------------------------------------------------------------ navigation


def open_file(run_id: str, path: str) -> None:
    """Show one run file in the workspace viewer; the score curve has its own tab."""
    if path == CURVE:
        st.session_state["ws_tab_next"] = "得分曲线"
    else:
        current = st.session_state.get("viewer")
        if current and current != (run_id, path):
            st.session_state.setdefault("viewer_back", []).append(current)
        st.session_state["viewer"] = (run_id, path)
        st.session_state["ws_tab_next"] = "查看器"
    st.session_state["need_rerun"] = True


def rerun_if_asked() -> None:
    """Widgets inside a fragment only rerun the fragment; a file click must move the tabs."""
    if st.session_state.pop("need_rerun", False):
        st.rerun()


def set_state(key: str, value: object) -> None:
    st.session_state[key] = value


def toggle(key: str) -> None:
    st.session_state[key] = not st.session_state.get(key, False)


def viewer_back() -> None:
    history = st.session_state.get("viewer_back") or []
    if history:
        st.session_state["viewer"] = history.pop()


def set_folder(run_id: str, folder: str) -> None:
    st.session_state.setdefault("ws_dir", {})[run_id] = folder


def open_run(run_id: str) -> None:
    job = st.session_state.get("job")
    own = bool(job and job.get("run_id") == run_id)
    st.session_state["view_run"] = None if own else run_id
    st.session_state["page"] = "research"
    st.session_state["viewer"] = None
    st.session_state["ws_tab_next"] = "文件"


def set_page(page: str) -> None:
    st.session_state["page"] = page


def new_research() -> None:
    job = st.session_state.get("job")
    if job and job.get("run_id") and (RUNS / job["run_id"] / "summary.json").is_file():
        st.session_state.pop("job", None)
    for key in ("view_run", "qa_pending", "viewer"):
        st.session_state.pop(key, None)
    reset_task_draft()
    st.session_state["page"] = "research"
    st.session_state["ws_tab_next"] = "文件"


def start_example(task_name: str) -> None:
    st.session_state["task_name"] = task_name
    reset_task_draft()
    st.session_state["request"] = protocol_card(TASKS[task_name][0])["business_question"]


def start_demo_upload() -> None:
    raw = DEMO_CSV.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()[:16]
    path = ROOT / "ui_state" / "uploads" / f"{digest}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    reset_task_draft()
    st.session_state["upload"] = {
        "path": str(path),
        "digest": digest,
        "filename": DEMO_CSV.name,
        "request": "预测哪些学生期末可能不及格，提前干预",
    }
    st.session_state["request"] = st.session_state["upload"]["request"]


def project_names() -> dict[str, str]:
    """Projects for the drawer: the built-in tasks, then every registered CSV upload."""
    names = {task_id: name for name, (task_id, _) in TASKS.items()}
    uploads = DATA / "uploads"
    if uploads.is_dir():
        for meta_path in sorted(uploads.glob("*/task.json")):
            meta = read_json(meta_path)
            if meta.get("task_id"):
                names.setdefault(meta["task_id"], meta.get("source_file_name") or meta["task_id"])
    return names


def toggle_project(task_id: str, default: bool) -> None:
    opened = st.session_state.setdefault("project_open", {})
    opened[task_id] = not opened.get(task_id, default)


def new_in_project(task_id: str) -> None:
    """Start a new research draft inside an existing project (task)."""
    new_research()
    name = next((name for name, (tid, _) in TASKS.items() if tid == task_id), None)
    if name:
        start_example(name)
        return
    config_path = ROOT / "ui_state" / "configs" / f"{task_id}.yaml"
    if not config_path.is_file():
        base = yaml.safe_load((ROOT / "configs/bank_marketing.yaml").read_text(encoding="utf-8"))
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            yaml.safe_dump(config_for_upload(task_id, base), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    card = protocol_card(task_id)
    st.session_state["custom_task"] = (task_id, str(config_path))
    st.session_state["request"] = card.get("business_question") or card.get("title") or task_id
    st.session_state.setdefault("project_open", {})[task_id] = True


def live(func, running: bool):
    """Refresh a block every 2 seconds only while a run is in progress."""
    return st.fragment(func, run_every="2s" if running else None)


def effect_text(value: object) -> str:
    return f"{value:.4g}" if isinstance(value, int | float) else "—"


def number_text(value: object, pattern: str) -> str:
    """Table cell for a number that may be missing, text or NaN; anything unusable shows —."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "—"
    return format(number, pattern) if math.isfinite(number) else "—"


def local_time(seconds: float | None, pattern: str = "%H:%M:%S") -> str:
    return datetime.fromtimestamp(seconds).strftime(pattern) if seconds else ""


# ------------------------------------------------------------------------------ chat pieces


def show_file_chips(run_id: str, evidence: list[dict], answer: str, *, key: str) -> None:
    """Files behind an answer as chips; a click opens the file in the workspace viewer."""
    links = answer_links(RUNS, run_id, evidence, answer)
    if not links:
        return
    st.caption("相关文件 · 点文件在右侧查看器打开")
    for group in GROUPS:
        items = [link for link in links if link.group == group]
        if not items:
            continue
        widget = f"{key}-{group}"
        names = {link.path: ("得分曲线" if link.path == CURVE else link.path) for link in items}
        st.pills(
            group,
            list(names),
            format_func=names.get,
            key=widget,
            on_change=pick_chip,
            args=(run_id, widget),
        )


def pick_chip(run_id: str, widget: str) -> None:
    if value := st.session_state.get(widget):
        open_file(run_id, value)


def show_quick_questions(run_id: str, *, key: str) -> None:
    """Zero-token quick questions as light chips in one row; the chosen one is answered below."""
    chosen = st.pills(
        "快捷问题（不花 Token）",
        list(QUICK_QUESTIONS),
        format_func=QUICK_QUESTIONS.get,
        key=key,
    )
    if chosen:
        answer = answer_quick(chosen, run_id, STORE)
        with st.chat_message("assistant"):
            st.write(answer["answer"])
            st.caption(f"证据：runs/{run_id}/summary.json · 0 Token")
            show_file_chips(run_id, answer["evidence"], answer["answer"], key=f"{key}-{chosen}")


def show_open_qa(run_id: str) -> None:
    thread = st.session_state.setdefault("qa_threads", {}).setdefault(run_id, [])
    pending = st.session_state.pop("qa_pending", None)
    if pending and pending[0] == run_id:
        thread.append(ask_open_question(run_id, pending[1], thread))
    for index, turn in enumerate(thread):
        with st.chat_message("user"):
            st.write(turn["question"])
        with st.chat_message("assistant"):
            if turn.get("error"):
                st.error(f"问答失败：{turn['error']}")
                continue
            if turn.get("note"):
                st.info(turn["note"])
                continue
            st.write(turn["answer"])
            verified = set(turn.get("verified_numbers", []))
            if turn.get("numbers"):
                marks = " ".join(
                    f"{number} {'✅' if number in verified else '⚠️'}" for number in turn["numbers"]
                )
                st.caption(f"数字核对：{marks}（⚠️＝没在证据里找到原值）")
            refs = [f"{ref['kind']}:{ref['ref_id']}" for ref in turn.get("evidence", [])]
            cited = " · ".join(refs) if refs else "无可核对的引用"
            st.caption(f"证据：{cited} · LLM {turn['tokens']:,} Token")
            show_file_chips(
                run_id, turn.get("evidence", []), turn["answer"], key=f"qa-{run_id}-{index}"
            )


def protocol_summary(run_id: str) -> None:
    """The confirmed research plan of a run, folded into one line."""
    base = RUNS / run_id
    card = read_json(base / "scenario_card.json")
    contract = read_json(base / "contract.json")
    excluded = []
    for event in read_events(base):
        if event.get("event_type") == "protocol_accepted":
            excluded = (event.get("details") or {}).get("excluded_features") or []
            break
    target = card.get("target") or {}
    metric = contract.get("primary_metric") or "f1_macro"
    line = f"目标列 {target.get('column', '?')} · {metric}"
    if excluded:
        line += f" · 不能用 {'、'.join(map(str, excluded))}"
    with st.expander(f"研究方案已确认 · {line}"):
        st.write(f"**任务：** {card.get('title', run_id)}")
        st.write(f"**预测时点：** {card.get('prediction_time', '—')}")
        st.write(
            f"**目标列：** {target.get('column', '—')}（正类：{target.get('positive_label', '—')}）"
        )
        st.write(f"**指标：** {metric}")
        budgets = contract.get("budgets") or {}
        if budgets:
            st.caption(
                f"预算：最多 {budgets.get('max_experiments')} 次实验、"
                f"{budgets.get('max_llm_requests')} 次 LLM 请求、"
                f"{int(budgets.get('max_llm_tokens') or 0):,} Token"
            )


STATUS_COLORS = {
    "run": "blue",
    "best": "green",
    "delivered": "blue",
    "warn": "orange",
    "fail": "red",
    "base": "gray",
    "plain": "gray",
}


def show_process(run_id: str, running: bool) -> None:
    """Search experiments in order, one line each, grouped by round, with their record file."""
    rows = list(reversed(experiment_table(RUNS / run_id)))
    done = [row for row in rows if row["kind"] != "run"]
    rounds = {row["round"] for row in done if isinstance(row["round"], int) and row["round"] > 0}
    with st.expander(
        f"研究过程 · {len(done)} 次实验 · {len(rounds)} 轮", expanded=running or len(done) < 4
    ):
        if not rows:
            st.caption("还没有完成的实验。")
        for row in rows:
            if row["source"] == "基线":
                stage = "基线"
            elif row["source"] == "规则搜索":
                stage = "规则搜索"
            elif isinstance(row["round"], int):
                stage = f"第 {row['round']} 轮"
            else:
                stage = row["source"]
            score = f"`{row['score']:.4f}`" if isinstance(row["score"], int | float) else ""
            color = STATUS_COLORS.get(row["kind"], "gray")
            line = st.container(horizontal=True, vertical_alignment="center", gap="small")
            with line:
                st.markdown(
                    f"`{clock(row['elapsed'])}` **{stage}** {row['id']} {row['change']} "
                    f"{score} :{color}[{row['status']}]"
                )
                if row["path"]:
                    st.button(
                        "打开",
                        key=f"process-{run_id}-{row['id']}",
                        type="tertiary",
                        icon=":material/description:",
                        help=row["path"],
                        on_click=open_file,
                        args=(run_id, row["path"]),
                    )
        st.button(
            "在查看器打开全部事件（events.jsonl）",
            key=f"process-events-{run_id}",
            type="tertiary",
            on_click=open_file,
            args=(run_id, "events.jsonl"),
        )
    rerun_if_asked()


def show_progress(run_id: str) -> None:
    """Pinned above the input while a run is in progress; reruns the page once it finishes."""
    base = RUNS / run_id
    job = st.session_state.get("job") or {}
    if (base / "summary.json").is_file():
        if not job.get("finished_seen"):
            job["finished_seen"] = True
            # A 2-second block may still be mid-refresh; one more clean pass settles the page.
            st.session_state["settle_rerun"] = True
            st.rerun()
        return
    process = job.get("process")
    if process is not None and process.poll() is not None:
        st.error("研究进程已退出，但没有生成 summary.json；请查看运行日志 ui_state/research.log。")
        return
    state = progress(base)
    best = f"`{state['best']:.4f}`（{state['best_id']}）" if state["best"] is not None else "—"
    with st.container(border=True, key="progress_card"):
        st.markdown(
            f"**研究进度** · 第 {state['round']} 轮 · {state['experiments']} / "
            f"{state['max_experiments'] or '—'} 次实验 · 用时 {clock(state['elapsed'])} · "
            f"当前最优 {best}"
        )
        stages = " → ".join(
            f":green[:material/check_circle: {label}]"
            if done
            else f":gray[:material/radio_button_unchecked: {label}]"
            for label, done in state["stages"]
        )
        running = f" · 正在训练 {state['running']}" if state["running"] else ""
        st.caption(stages + running)


def show_conclusion(run_id: str) -> None:
    summary = STORE.get_summary(run_id)
    evaluation = STORE.get_final_evaluation(run_id)
    llm = summary.get("llm") or {}
    with st.container(border=True):
        st.markdown("**研究结论**")
        with st.container(horizontal=True):
            st.metric(
                "开发集 · 基线 → 交付",
                f"{fmt(summary.get('baseline_score'))} → {fmt(summary.get('delivered_dev_score'))}",
                border=True,
            )
            st.metric(
                "最终测试 · 只测一次",
                fmt(evaluation.get("holdout_score"))
                if evaluation
                else ("进行中" if final_test_pending(run_id) else "未完成"),
                border=True,
            )
            st.metric("新切分复核", summary.get("confirmation_status", "未知"), border=True)
            st.metric("LLM Token", f"{int(llm.get('tokens') or 0):,}", border=True)
        delivered = summary.get("delivered_experiment_id")
        detail = read_json(RUNS / run_id / "experiments" / f"{delivered}.json") if delivered else {}
        delivered_row = next(
            (row for row in experiment_rows(RUNS / run_id, summary) if row["id"] == delivered),
            {"id": delivered or ""},
        )
        spec_text = describe_spec(detail.get("spec") or {})
        lines = [f"交付「{experiment_label(delivered_row)}」：{spec_text}"] if delivered else []
        if evaluation:
            lines.append(final_test_text(evaluation))
        lines.append(
            f"LLM {llm.get('requests', 0)} 次请求 · 用时 {clock(summary.get('wall_seconds'))} · "
            f"代码版本 {summary.get('code_version')}"
        )
        st.caption("  \n".join(lines))
        if not evaluation:
            live(show_final_test, final_test_pending(run_id))(run_id, key=f"evaluate-{run_id}")
        st.caption(
            "数值来自 summary.json 和 final_evaluation.json；是否通过由程序判断，不由 LLM 判断。"
        )
    show_quick_questions(run_id, key=f"faq-{run_id}")


def show_starting() -> None:
    """The run directory appears a moment after launch; show the run as soon as it does."""
    job = st.session_state.get("job")
    if not job:
        return
    if locate_run(job) is not None:
        st.rerun()
    if job["process"].poll() is not None:
        st.error("研究进程在创建 run 目录前退出。请查看 ui_state/research.log。")
        log_path = ROOT / "ui_state" / "research.log"
        if log_path.is_file():
            st.code(log_path.read_text(encoding="utf-8", errors="replace")[-2000:])
        return
    st.info("研究进程正在启动，页面会自动更新。")


def show_empty_state() -> None:
    st.markdown("## 接下来想研究什么？")
    st.caption("在下方描述要预测什么，可以附上一份二分类 CSV。示例任务自动采用已有任务说明。")
    st.markdown("**从示例开始**")
    cards = [(name, text) for name, text in EXAMPLES.items()]
    grid = st.columns(2)
    for index, (name, text) in enumerate(cards):
        with grid[index % 2], st.container(border=True):
            st.button(
                name,
                key=f"example-{name}",
                type="tertiary",
                on_click=start_example,
                args=(name,),
            )
            st.caption(text)
    if DEMO_CSV.is_file():
        with grid[len(cards) % 2], st.container(border=True):
            st.button(
                "学生成绩预警（上传 CSV 示例）",
                key="example-upload",
                type="tertiary",
                on_click=start_demo_upload,
            )
            st.caption("逐列确认哪些数据列能用，附人工标准协议")
    recent = history_rows(RUNS, STORE.list_runs())[:3]
    if recent:
        st.markdown("**最近研究**")
        for row in recent:
            label = f"{row['title']} · {row['source']}"
            if row["score"]:
                label += f" · {row['score']}"
            st.button(
                label,
                key=f"recent-{row['run_id']}",
                type="tertiary",
                on_click=open_run,
                args=(row["run_id"],),
            )


def show_setup_flow() -> None:
    """Show the research plan (example card or saved CSV protocol) and start the run."""
    with st.chat_message("user"):
        st.write(st.session_state["request"])

    if st.session_state.get("upload"):
        show_upload_protocol(st.session_state["upload"], llm_on)
        return

    card = protocol_card(task_id)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    with st.chat_message("assistant"):
        if task_id.startswith("upload-"):
            st.write("以下是已保存的 CSV 任务说明，研究将使用这些设置。")
        else:
            st.write("已采用该示例的任务说明，可直接准备数据并开始研究。")
        st.write(f"**任务：** {card['title']}")
        st.write(f"**预测时点：** {card['prediction_time']}")
        st.write(
            f"**目标列：** {card['target']['column']}（正类：{card['target']['positive_label']}）"
        )
        st.write(f"**指标：** {config.get('primary_metric', 'f1_macro')}")
        fields = card["fields"]
        usable = {
            "available": "✅ 可以用",
            "post_outcome": "❌ 不能用：结果出来后才知道",
            "identifier": "➖ 不用：只是编号",
        }
        count = f"（共 {len(fields)} 列）" if fields else ""
        with st.expander(f"哪些数据列可以用来预测{count}"):
            if fields:
                # Columns that cannot be used come first so they are easy to check.
                ordered = sorted(fields, key=lambda field: field["availability"] == "available")
                st.dataframe(
                    [
                        {
                            "数据列": field["name"],
                            "能否用来预测": usable.get(
                                field["availability"], field["availability"]
                            ),
                            "说明": field.get("note", field.get("description", "")),
                        }
                        for field in ordered
                    ],
                    hide_index=True,
                    alt="示例任务的每个数据列能否用来预测，以及说明",
                )
            elif card.get("default_availability") == "available":
                st.write("这个示例的所有数据列都可以用来预测。")
            else:
                st.write("这个示例的数据列按任务说明里的默认规则判断能否使用。")

    with st.chat_message("assistant"):
        run_config = research_config(config, ROOT)
        budget = run_config["budget"]
        model = run_config["llm"].get("model") or os.environ.get("LLM_MODEL")
        source = (
            f"实验方案由 LLM 提出（{model}，"
            f"最多 {budget['max_llm_requests']} 次请求、{budget['max_llm_tokens']:,} Token）"
        )
        st.write(
            f"**研究预算：** 最多 {budget['max_experiments']} 次实验；系统 `budgetlab`，{source}。"
        )
        st.caption("开始后自动完成模型研究和独立测试集上的最终测试。")
        if LLM_PROBLEM is not None:
            st.error(f"{LLM_PROBLEM}。实验方案只由 LLM 提出，配置好之后才能开始研究。")
        ready = (DATA / "prepared" / task_id / "development.csv").is_file()
        if not ready:
            st.warning("当前任务数据尚未准备，Bank 和 Adult 首次准备需要下载数据。")
            if st.button("准备示例数据"):
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "budgetlab.cli",
                        "prepare",
                        "--task",
                        task_id,
                        "--data-root",
                        str(DATA),
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode:
                    st.error(result.stderr[-1000:])
                else:
                    st.rerun()
        if st.button(
            "开始研究",
            disabled=not ready or not llm_on or bool(st.session_state.get("job")),
        ):
            st.session_state["job"] = launch(task_id, config_path)
            st.session_state["view_run"] = None
            st.session_state["ws_tab_next"] = "研究路径"
            st.rerun()


def show_compare() -> None:
    st.button("返回研究", icon=":material/arrow_back:", on_click=set_page, args=("research",))
    matrix_data = load_matrix(ROOT / "results")
    if matrix_data:
        matrix, rows, formal = matrix_data
        st.subheader("正式成绩" if formal else "开发数据")
        if not formal:
            st.warning("这是开发数据，仅用于搭建和检查页面，不是正式成绩。")
        st.caption(f"来源：{matrix.parent.relative_to(ROOT)}")
        valid = [row for row in rows if row.get("status") == "ok"]
        with st.container(horizontal=True):
            st.metric("系统", len({row.get("system") for row in valid}), border=True)
            st.metric("完成的运行", len(valid), border=True)
            st.metric("任务", len({row.get("task_id") for row in valid}), border=True)
        columns = [
            "system",
            "proposal_source",
            "baseline_score",
            "delivered_dev_score",
            "holdout_score",
            "llm_tokens",
            "wall_seconds",
            "experiments",
            "run_id",
        ]
        st.dataframe(
            [{key: row.get(key) for key in columns} for row in rows],
            hide_index=True,
            alt="各研究系统的开发集、独立测试集分数和运行成本对比",
        )
        run_options = [row["run_id"] for row in valid if row.get("run_id")]
        if run_options:
            chosen = st.selectbox("查看单次运行轨迹", run_options)
            summary_path = matrix.parent / "runs" / chosen / "summary.json"
            if summary_path.is_file():
                trajectory = trajectory_rows(json.loads(summary_path.read_text(encoding="utf-8")))
                if trajectory:
                    if any(row["累计 Token"] for row in trajectory):
                        st.line_chart(
                            trajectory,
                            x="累计 Token",
                            y="最优分",
                            alt="最优分随累计 Token 的变化",
                        )
                    else:
                        st.caption("这次运行没有消耗 LLM Token，改按实验顺序展示最优分。")
                        st.line_chart(
                            trajectory,
                            x="实验",
                            y="最优分",
                            alt="零 Token 运行中最优分随实验顺序的变化",
                        )
                    st.line_chart(
                        trajectory,
                        x="累计秒数",
                        y="最优分",
                        alt="最优分随累计运行时间的变化",
                    )
    else:
        st.info("当前分支尚未包含 results/dev-* 或 results/final-* 对照数据。")


# ------------------------------------------------------------------------------ workspace


def show_files(run_id: str, running: bool, highlight: set[str]) -> None:
    base = RUNS / run_id
    folders = st.session_state.setdefault("ws_dir", {})
    folder = folders.get(run_id, "")
    entries = list_entries(RUNS, run_id, folder)
    if entries is None:
        folder, entries = "", list_entries(RUNS, run_id) or []
    with st.container(horizontal=True, vertical_alignment="center"):
        if folder:
            parent = folder.rsplit("/", 1)[0] if "/" in folder else ""
            st.button(
                "上一级",
                key=f"files-up-{run_id}",
                icon=":material/arrow_upward:",
                type="tertiary",
                on_click=set_folder,
                args=(run_id, parent),
            )
        st.markdown(f"`runs / {run_id}" + (f" / {folder}`" if folder else "`"))
    with st.container(horizontal=True, vertical_alignment="center"):
        query = st.text_input(
            "筛选文件名",
            key="files_filter",
            placeholder="筛选文件名…",
            label_visibility="collapsed",
        )
        order = st.segmented_control(
            "排序",
            ["时间", "名称"],
            key="files_sort",
            default="时间",
            required=True,
            label_visibility="collapsed",
        )
        only = st.checkbox("只看本轮" if running else "只看相关", key="files_only")
    since = round_started_at(read_events(base)) if running else None

    def fresh(entry: dict) -> bool:
        if running:
            return since is not None and entry["mtime"] >= since
        return entry["path"] in highlight or any(
            path.startswith(entry["path"] + "/") for path in highlight
        )

    rows = [
        entry
        for entry in sort_entries(entries, "name" if order == "名称" else "time")
        if query.strip().lower() in entry["name"].lower() and (not only or fresh(entry))
    ]
    count = sum(fresh(entry) for entry in entries)
    if count:
        reason = "本轮新写入" if running else "最近一次回答引用"
        st.markdown(f":green-background[● 绿色标出的是{reason}的文件（共 {count} 个）]")
    row_table(
        [
            {"label": "名称", "width": "50%"},
            {"label": "大小", "width": "20%"},
            {"label": "时间", "width": "30%"},
        ],
        [
            {
                "id": entry["path"],
                "open": entry["path"],
                "cells": [
                    entry["name"],
                    f"{entry['items']} 项" if entry["is_dir"] else size_text(entry["size"]),
                    local_time(entry["mtime"], "%m-%d %H:%M:%S"),
                ],
                "tones": ["green-strong"] * 3 if fresh(entry) else None,
            }
            for entry in rows
        ],
        key=f"files-{run_id}",
        on_open=partial(open_entry, run_id, {entry["path"]: entry for entry in rows}),
        empty="没有匹配的文件",
        fit=True,
    )
    dirs = sum(entry["is_dir"] for entry in entries)
    st.caption(f"{dirs} 个文件夹 · {len(entries) - dirs} 个文件 · 双击打开")
    rerun_if_asked()


def open_entry(run_id: str, entries: dict[str, dict], path: str) -> None:
    entry = entries.get(path)
    if entry is None:
        return
    if entry["is_dir"]:
        set_folder(run_id, entry["path"])
    elif entry["viewable"]:
        open_file(run_id, entry["path"])
    else:
        st.session_state["files_notice"] = f"{entry['path']} 不是文本文件，不在页面里打开。"
        st.session_state["need_rerun"] = True  # the notice sits outside the file-list fragment


def show_viewer() -> None:
    current = st.session_state.get("viewer")
    if not current:
        st.info("双击文件列表或实验表格里的一行，或点回答下的文件，会在这里打开。")
        return
    run_id, path = current
    with st.container(horizontal=True, vertical_alignment="center"):
        st.button(
            "后退",
            key="viewer-back",
            icon=":material/arrow_back:",
            type="tertiary",
            disabled=not st.session_state.get("viewer_back"),
            on_click=viewer_back,
        )
        st.markdown(f"`{path}`")
        st.link_button(
            "新标签打开",
            "?" + urlencode({"run": run_id, "file": path}, safe="/"),
            icon=":material/open_in_new:",
            type="tertiary",
        )
    render_artifact(run_id, path)


def curve_summary(base: Path) -> dict:
    """summary.json once a run ends; during a run, a trajectory rebuilt from its experiments."""
    summary = read_json(base / "summary.json")
    if summary.get("trajectory"):
        return summary
    rows = [
        row
        for row in experiment_table(base)
        if row["kind"] != "run" and isinstance(row["elapsed"], int | float)
    ]
    rows.sort(key=lambda row: row["elapsed"])
    return {
        "primary_metric": read_json(base / "contract.json").get("primary_metric"),
        "baseline_score": next((row["score"] for row in rows if row["kind"] == "base"), None),
        "trajectory": [
            {
                "experiment_id": row["id"],
                "best_score_after": row["best_after"],
                "mean_score": row["score"],
                "origin": row["source"],
                "round": row["round"],
                "llm_tokens_so_far": row["tokens"],
                "elapsed_seconds": row["elapsed"],
            }
            for row in rows
        ],
    }


def show_workspace(run_id: str | None, running: bool, highlight: set[str], tall: bool) -> None:
    with st.container(key="ws_panel_tall" if tall else "ws_panel"):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.segmented_control(
                "工作区", WS_TABS, key="ws_tab", required=True, label_visibility="collapsed"
            )
            if running:
                st.caption(":green[●] 每 2 秒更新")
        tab = st.session_state.get("ws_tab") or "文件"
        with st.container(key="ws_body"):
            if run_id is None:
                st.markdown("**这里会显示研究生成的文件**")
                st.caption(
                    "开始研究后，每次实验的记录、程序裁决、每轮提案、日志和最终报告都会实时出现在这里。"
                    "双击文件就在查看器里打开。"
                )
                return
            if notice := st.session_state.pop("files_notice", None):
                st.info(notice)
            if tab == "文件":
                live(show_files, running)(run_id, running, highlight)
            elif tab == "查看器":
                show_viewer()
            elif tab == "研究路径":
                live(render_branch_map, running)(RUNS / run_id, running=running)
            else:
                show_score_curve(run_id, curve_summary(RUNS / run_id))


# ------------------------------------------------------------------------------ experiment panel


def show_experiments(run_id: str, running: bool) -> None:
    base = RUNS / run_id
    rows = experiment_table(base)
    metric = read_json(base / "contract.json").get("primary_metric") or "score"
    if not rows:
        st.caption("还没有实验。")
        return
    tones = {
        "run": "blue",
        "best": "green",
        "delivered": "blue-strong",
        "warn": "amber",
        "fail": "red",
    }
    row_table(
        [
            {"label": "实验"},
            {"label": metric, "align": "right"},
            {"label": "较此前最优", "align": "right"},
            {"label": "状态"},
            {"label": "来源"},
            {"label": "耗时(s)", "align": "right"},
            {"label": "做了什么", "max": "18rem"},
        ],
        [
            {
                "id": row["id"],
                "open": row["path"] or None,
                "cells": [
                    row["id"],
                    number_text(row["score"], ".4f"),
                    number_text(row["delta"], "+.4f"),
                    row["status"],
                    row["source"],
                    number_text(row["seconds"], ".1f"),
                    row["change"] or MODEL_NAMES.get(row["model"], row["model"]),
                ],
                "tones": [None, None, None, tones.get(row["kind"]), None, None, None],
            }
            for row in rows
        ],
        key=f"experiments-{run_id}",
        on_open=partial(open_file, run_id),
    )
    kinds = [row["kind"] for row in rows]
    rounds = {row["round"] for row in rows if isinstance(row["round"], int) and row["round"] > 0}
    policy = read_json(base / "contract.json").get("decision_policy") or {}
    st.caption(
        f"共 {sum(kind != 'run' for kind in kinds)} 个实验 · {len(rounds)} 轮 · "
        f"最小提升 {effect_text(policy.get('min_effect'))} · 双击一行在查看器打开"
    )
    rerun_if_asked()


def show_tokens(run_id: str) -> None:
    ledger = token_ledger(RUNS / run_id)
    used, unknown, limit = ledger["used"], ledger["unknown"], ledger["limit"]
    with st.container(horizontal=True):
        st.metric("本次研究 LLM Token", f"{used:,}", border=True)
        st.metric("预算", f"{limit:,}" if limit else "—", border=True)
        st.metric("未知用量", f"{unknown:,}", border=True)
    if limit:
        st.progress(min((used + unknown) / limit, 1.0), text="已记 + 未知 / 预算")
    roles = ledger["by_role"]
    st.caption(
        f"提案 {roles.get('proposer', {}).get('tokens', 0):,} · "
        f"审查 {roles.get('critic', {}).get('tokens', 0):,} Token"
    )
    if unknown:
        st.warning("有请求未返回完整 usage；未知用量单列，未当作 0 Token。")
    if ledger["by_round"]:
        st.dataframe(ledger["by_round"], hide_index=True, alt="每轮提案和审查的 Token 使用记录")
    usage = st.session_state.get("qa_usage") or {}
    if usage.get("requests"):
        st.caption(
            f"本会话追问：{usage['requests']} 次请求、{usage['tokens']:,} Token"
            "（记在 ui_state/qa_calls.jsonl）"
        )
    st.caption(
        "只统计本次研究的提案和审查。CSV 协议起草和开放问答的 Token 另记在 ui_state/；"
        "程序实验和快捷问答不调用 LLM。"
    )


def show_validation(run_id: str) -> None:
    base = RUNS / run_id
    summary = read_json(base / "summary.json")
    if not summary:
        st.info("研究结束后，这里显示新切分复核和最终测试结果。")
        return
    evaluation = STORE.get_final_evaluation(run_id)
    left, right = st.columns(2)
    with left:
        st.markdown(f"**新切分复核** · `{summary.get('confirmation_status', '未知')}`")
        policy = read_json(base / "contract.json").get("decision_policy") or {}
        seeds = policy.get("confirmation_split_seeds") or []
        deltas = summary.get("confirmation_deltas") or []
        if deltas:
            st.dataframe(
                [
                    {
                        "切分": f"seed {seeds[index]}" if index < len(seeds) else f"#{index + 1}",
                        "交付减基线": round(delta, 4),
                    }
                    for index, delta in enumerate(deltas)
                ],
                hide_index=True,
            )
        st.caption(f"门槛：每次都要高于最小提升 {effect_text(policy.get('min_effect'))}")
    with right:
        st.markdown("**最终测试** · 每次研究只测一次")
        if evaluation:
            st.metric("最终测试分数", fmt(evaluation.get("holdout_score")))
            interval = evaluation.get("holdout_ci95") or []
            if len(interval) == 2:
                st.caption(f"95% 区间 {fmt(interval[0])}–{fmt(interval[1])}")
            st.caption(
                f"独立测试集 {evaluation.get('holdout_rows', '—'):,} 行 · 开发集 "
                f"{fmt(evaluation.get('development_cv_score'))}，差 "
                f"{fmt(evaluation.get('dev_minus_holdout'))}"
            )
        elif final_test_pending(run_id):
            st.caption("正在独立测试集上检验模型……")
        elif read_json(base / "ui_final_test.json").get("status") == "failed":
            st.caption("未完成，可在研究结论中查看原因并重试。")
        else:
            st.caption("尚未完成。独立测试集不参与训练或选模型。")


def show_compare_compact() -> None:
    matrix_data = load_matrix(ROOT / "results")
    if not matrix_data:
        st.caption("还没有 results/ 下的对比数据。")
        return
    matrix, rows, formal = matrix_data
    st.markdown(f"**系统对比** · {'正式成绩' if formal else ':orange[开发数据]'}")
    st.dataframe(
        [
            {
                "任务": row.get("task_id"),
                "系统": row.get("system"),
                "基线": row.get("baseline_score"),
                "交付": row.get("delivered_dev_score"),
            }
            for row in rows
            if row.get("status") == "ok"
        ],
        hide_index=True,
    )
    st.caption(f"来源：{matrix.parent.relative_to(ROOT)}" + ("" if formal else " · 不是正式成绩"))


def show_panel(run_id: str | None, running: bool) -> None:
    opened = st.session_state.get("panel_open", True)
    rows = experiment_table(RUNS / run_id) if run_id else []
    counts = (
        f"运行 {sum(row['kind'] == 'run' for row in rows)} · "
        f"完成 {sum(row['kind'] not in {'run', 'fail'} for row in rows)} · "
        f"失败 {sum(row['kind'] == 'fail' for row in rows)}"
        if run_id
        else "暂无运行"
    )
    with st.container(key="exp_panel" if opened else "exp_panel_closed"):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown("**实验面板**")
            st.caption(counts)
            if opened and run_id:
                st.segmented_control(
                    "面板内容",
                    PANEL_TABS,
                    key="panel_tab",
                    default="实验",
                    required=True,
                    label_visibility="collapsed",
                )
            st.space("stretch")
            st.button(
                "收起" if opened else "展开",
                key="panel-toggle",
                on_click=set_state,
                args=("panel_open", not opened),
            )
        if not opened:
            return
        with st.container(key="exp_body"):
            if run_id is None:
                show_compare_compact()
            elif (st.session_state.get("panel_tab") or "实验") == "实验":
                live(show_experiments, running)(run_id, running)
            elif st.session_state.get("panel_tab") == "Token":
                show_tokens(run_id)
            else:
                show_validation(run_id)


# ------------------------------------------------------------------------------ drawer


def show_drawer(focus: str | None, busy: bool, running_id: str | None) -> None:
    with st.container(key="drawer_panel"):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.button(
                ":material/menu:",
                key="drawer-close",
                help="收起项目栏",
                type="tertiary",
                on_click=toggle,
                args=("drawer",),
            )
            st.markdown("**项目**")
            st.space("stretch")
            st.button(
                "新研究",
                key="drawer-new",
                icon=":material/add:",
                disabled=busy,
                help="研究运行中，结束后才能开始新研究" if busy else None,
                on_click=new_research,
            )
        query = (
            st.text_input(
                "搜索项目和研究记录",
                key="history_query",
                placeholder="搜索项目、系统或编号",
                label_visibility="collapsed",
            )
            .strip()
            .lower()
        )
        names = project_names()
        groups = project_groups(history_rows(RUNS, STORE.list_runs()), names)
        if query:
            fields = ("title", "strategy", "task_id", "system", "run_id", "source")
            for group in groups:
                if query not in group["name"].lower() and query not in group["task_id"].lower():
                    group["runs"] = [
                        row
                        for row in group["runs"]
                        if any(query in str(row.get(field) or "").lower() for field in fields)
                    ]
                    group["hide"] = not group["runs"]
            groups = [group for group in groups if not group.get("hide")]
        opened = st.session_state.get("project_open") or {}
        now = datetime.now().astimezone()
        with st.container(key="history_list"):
            for group in groups:
                task_id, runs = group["task_id"], group["runs"]
                is_open = bool(query) or opened.get(task_id, bool(runs))
                active = any(row["run_id"] == focus for row in runs)
                with st.container(
                    key=f"proj{'_on' if active else ''}-{task_id}",
                    horizontal=True,
                    wrap=False,
                    vertical_alignment="center",
                    gap=None,
                ):
                    st.button(
                        group["name"],
                        key=f"projbtn-{task_id}",
                        icon=":material/folder_open:" if is_open else ":material/folder:",
                        type="tertiary",
                        help=EXAMPLES.get(group["name"]) or task_id,
                        on_click=toggle_project,
                        args=(task_id, bool(runs)),
                        width="stretch",
                    )
                    if runs:
                        st.caption(str(len(runs)))
                    if task_id in names:  # retired tasks keep their runs but get no +
                        st.button(
                            ":material/add:",
                            key=f"projnew-{task_id}",
                            type="tertiary",
                            disabled=busy,
                            help=(
                                "研究运行中，结束后才能开始新研究"
                                if busy
                                else f"在「{group['name']}」里新建研究"
                            ),
                            on_click=new_in_project,
                            args=(task_id,),
                        )
                if not is_open:
                    continue
                with st.container(key=f"projruns-{task_id}", gap=None):
                    if not runs:
                        st.caption("还没有研究，点 + 开始")
                    for row in runs:
                        row_running = row["run_id"] == running_id
                        # The title names the delivered strategy; source and score go below.
                        if row_running:
                            title, status = "研究进行中…", "运行中"
                        else:
                            title = row["strategy"] or (
                                "已完成" if row["finished"] else "已中断，没有交付"
                            )
                            status = row["score"] or ("已完成" if row["finished"] else "未完成")
                        meta = [row["source"], status, when_text(row["started"], now)]
                        detail = row["strategy_detail"] or str(row["system"] or "")
                        key = "on-" if row["run_id"] == focus else ""
                        with st.container(key=f"hrow-{key}{row['run_id']}", gap=None):
                            st.button(
                                title,
                                key=f"open-{row['run_id']}",
                                icon=":material/progress_activity:" if row_running else None,
                                type="tertiary",
                                help=f"{detail}\n\n`{row['run_id']}`",
                                on_click=open_run,
                                args=(row["run_id"],),
                                width="stretch",
                            )
                            st.caption(" · ".join(part for part in meta if part))
            if not groups:
                st.caption("没有匹配的项目或研究记录。")
        st.button(
            "系统对比",
            key="drawer-compare",
            icon=":material/insights:",
            type="tertiary",
            on_click=set_page,
            args=("compare",),
        )
        st.caption("读取 results/ 下最新的正式或开发矩阵")


# ------------------------------------------------------------------------------ page

st.set_page_config(
    page_title="BudgetLab 研究助手",
    page_icon=":material/science:",
    layout="wide",
    initial_sidebar_state="collapsed",
)
try:
    import_module("pyarrow")
except ImportError as exc:
    st.error("页面数据表无法加载：当前 PyArrow 与项目固定的 NumPy 版本不兼容。")
    st.code(r'.\.venv\Scripts\python.exe -m pip install "pyarrow==25.0.1"')
    st.caption(f"技术信息：{exc}")
    st.stop()
if "file" in st.query_params:
    # Evidence links opened in a new tab show one file, without the research page.
    show_artifact_page(st.query_params.get("run", ""), st.query_params.get("file", ""))
    st.stop()
LLM_PROBLEM = llm_problem(ROOT)
MODEL = (llm_overrides(ROOT).get("llm") or {}).get("model") or os.environ.get("LLM_MODEL") or "LLM"
st.html("""<style>
[data-testid="stMainBlockContainer"] {padding: 3.25rem .5rem .5rem; max-width: 100%;}
[data-testid="stHeader"] {background: rgba(245, 246, 248, .9);}
.st-key-drawer_panel, .st-key-chat_panel, .st-key-ws_panel, .st-key-ws_panel_tall,
.st-key-exp_panel, .st-key-exp_panel_closed {
  background: #FFFFFF; border: 1px solid #E4E7EC; border-radius: 12px;
  padding: .6rem .9rem; box-sizing: border-box;
}
.st-key-drawer_panel, .st-key-chat_panel, .st-key-ws_panel, .st-key-ws_panel_tall,
.st-key-exp_panel {flex: none !important;}
.st-key-drawer_panel, .st-key-chat_panel {height: calc(100vh - 4rem) !important;}
.st-key-ws_panel {height: calc(100vh - 4rem - 330px) !important;}
.st-key-ws_panel_tall {height: calc(100vh - 4rem - 66px) !important;}
.st-key-exp_panel {height: 318px !important;}
/* Streamlit wraps nested containers; the wrapper takes the free height, the block scrolls. */
[data-testid="stLayoutWrapper"]:has(> .st-key-chat_scroll),
[data-testid="stLayoutWrapper"]:has(> .st-key-ws_body),
[data-testid="stLayoutWrapper"]:has(> .st-key-exp_body),
[data-testid="stLayoutWrapper"]:has(> .st-key-history_list) {
  flex: 1 1 0 !important; min-height: 0 !important;
}
.st-key-chat_scroll, .st-key-ws_body, .st-key-exp_body, .st-key-history_list {
  height: 100% !important; overflow-y: auto !important; overflow-x: hidden;
}
/* Project drawer: folders with their runs nested underneath, like a file tree. */
.st-key-history_list {gap: .1rem !important;}
.st-key-history_list button {justify-content: flex-start; text-align: left; min-height: 0;}
.st-key-history_list [data-testid="stTooltipHoverTarget"] {justify-content: flex-start;}
.st-key-history_list button > div {justify-content: flex-start; min-width: 0;}
.st-key-history_list button p {white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
[class*="st-key-proj-"], [class*="st-key-proj_on-"] {
  border-radius: 6px; padding: .1rem .2rem; margin-top: .35rem;
}
[class*="st-key-proj-"]:hover, [class*="st-key-proj_on-"]:hover {background: #F2F4F7;}
[class*="st-key-proj_on-"] [class*="st-key-projbtn-"] p {font-weight: 600;}
[class*="st-key-projbtn-"] {min-width: 0; flex: 1 1 auto;}
[class*="st-key-projbtn-"] button {width: 100%; padding: .15rem 0;}
[class*="st-key-projbtn-"] button:focus:not(:focus-visible) {color: inherit;}
[class*="st-key-projnew-"] button {opacity: .45; padding: 0 .2rem;}
[class*="st-key-proj-"]:hover [class*="st-key-projnew-"] button,
[class*="st-key-proj_on-"]:hover [class*="st-key-projnew-"] button {opacity: 1;}
[class*="st-key-projruns-"] {
  padding-left: 1.15rem;
  background: linear-gradient(#E4E7EC, #E4E7EC) no-repeat left .78rem top 0 / 1px 100%;
}
[class*="st-key-projruns-"] > [data-testid="stElementContainer"] p {margin: .1rem .5rem;}
/* A run row: strategy title (up to two lines) over a small source · score · time line. */
[class*="st-key-hrow-"] {position: relative; border-radius: 6px; padding: .25rem 0 .3rem;}
[class*="st-key-hrow-"]:hover {background: #F2F4F7;}
[class*="st-key-hrow-on-"], [class*="st-key-hrow-on-"]:hover {background: #EEF3FF;}
[class*="st-key-hrow-"] button {width: 100%; padding: 0 .5rem; color: #344054;}
[class*="st-key-hrow-"] button:hover {background: transparent;}
[class*="st-key-hrow-on-"] button {color: #1D4ED8;}
[class*="st-key-hrow-"] button p {
  white-space: normal; display: -webkit-box; -webkit-line-clamp: 2;
  -webkit-box-orient: vertical; line-height: 1.35;
}
/* The whole row, caption included, opens the run: the overlay must anchor to the row,
   so Streamlit's position:relative element containers inside it are made static. */
[class*="st-key-hrow-"] [data-testid="stElementContainer"] {position: static;}
[class*="st-key-hrow-"] button::after {content: ""; position: absolute; inset: 0;}
[class*="st-key-hrow-"] [data-testid="stCaptionContainer"] {pointer-events: none;}
/* Streamlit pulls captions up by -1rem to cancel the paragraph margin we drop here. */
[class*="st-key-hrow-"] [data-testid="stCaptionContainer"],
[class*="st-key-projruns-"] > [data-testid="stElementContainer"]
  [data-testid="stCaptionContainer"] {
  margin-bottom: 0 !important;
}
[class*="st-key-hrow-"] [data-testid="stCaptionContainer"] p {
  margin: .05rem .5rem 0; font-size: .75rem;
}
.st-key-chat_head {flex-wrap: nowrap !important;}
.st-key-chat_head [data-testid="stElementContainer"]:has([data-testid="stMarkdown"]) {
  min-width: 0; flex: 0 1 auto;
}
.st-key-chat_head [data-testid="stMarkdownContainer"] p {
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin: 0;
}
.st-key-progress_card {background: #FCFCFD;}
[data-testid="stMetricValue"] {font-variant-numeric: tabular-nums;}
[data-testid="stMetricLabel"] p {font-size: .85rem;}
code {font-variant-numeric: tabular-nums;}
</style>""")

for key, value in (("ws_tab", "文件"), ("page", "research"), ("panel_open", True)):
    st.session_state.setdefault(key, value)
if "ws_tab_next" in st.session_state:
    st.session_state["ws_tab"] = st.session_state.pop("ws_tab_next")

job = st.session_state.get("job")
job_dir = locate_run(job) if job else None
job_done = bool(
    job_dir
    and (job_dir / "summary.json").is_file()
    and (
        not job.get("auto_final_test")
        or (job_dir / "final_evaluation.json").is_file()
        or read_json(job_dir / "ui_final_test.json").get("status") == "failed"
    )
)
busy = bool(job and not job_done and job["process"].poll() is None)
view_run = st.session_state.get("view_run")
if view_run and run_dir(RUNS, view_run) is None:
    view_run = st.session_state["view_run"] = None
focus = view_run or (job_dir.name if job_dir else None)
running = bool(focus and job_dir and focus == job_dir.name and busy)
starting = bool(job and job_dir is None and not view_run)
finished_focus = bool(focus and (RUNS / focus / "summary.json").is_file())

drawer_open = st.session_state.get("drawer", False)
ws_hidden = st.session_state.get("ws_hidden", False)
widths = ([0.62] if drawer_open else []) + [1.35] + ([] if ws_hidden else [1.0])
columns = st.columns(widths, gap="small")
if drawer_open:
    with columns[0]:
        show_drawer(focus, busy, job_dir.name if busy and job_dir else None)
chat_col = columns[1 if drawer_open else 0]

with chat_col, st.container(key="chat_panel"):
    head = st.container(horizontal=True, vertical_alignment="center", key="chat_head")
    scroll = st.container(key="chat_scroll")
    footer = st.container(key="chat_footer")

with footer:
    if running:
        live(show_progress, True)(focus)
    if running or starting:
        placeholder = "研究完成后可以就结果追问；运行中可以先在右侧查看实时生成的文件"
    elif finished_focus:
        placeholder = "就这次研究追问，例如：为什么最后选了这个模型？"
    else:
        placeholder = "描述任务，可附上二分类 CSV"
    prompt = st.chat_input(
        placeholder,
        key="composer",
        accept_file=not finished_focus,
        file_type="csv",
        disabled=running or starting,
    )
    with st.container(horizontal=True, vertical_alignment="center"):
        task_name = st.selectbox(
            "任务",
            list(TASKS),
            key="task_name",
            disabled=bool(job),
            on_change=reset_task_draft,
            format_func=lambda name: f"任务 · {name}",
            label_visibility="collapsed",
            width=240,
        )
        if busy:
            st.caption(f"运行中，任务已锁定 · 实验方案由 {MODEL} 提出")
        elif LLM_PROBLEM is not None:
            st.caption(f"{LLM_PROBLEM}：不能开始新研究，只能查看已有研究和快捷问题。")
        else:
            st.caption(f"{MODEL} 起草协议、提出实验、回答追问；指标和裁决由程序计算")
    task_id, config_path = TASKS[task_name]
    if st.session_state.get("custom_task"):
        task_id, config_path = st.session_state["custom_task"]
        config_path = Path(config_path)
    llm_on = LLM_PROBLEM is None

if prompt:
    if finished_focus and not prompt.files and prompt.text.strip():
        st.session_state["qa_pending"] = (focus, prompt.text.strip())
        st.session_state["page"] = "research"
    elif prompt.files:
        uploaded = prompt.files[0]
        raw = uploaded.getvalue()
        digest = hashlib.sha256(raw).hexdigest()[:16]
        path = ROOT / "ui_state" / "uploads" / f"{digest}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        reset_task_draft()
        st.session_state["upload"] = {
            "path": str(path),
            "digest": digest,
            "filename": uploaded.name,
            "request": prompt.text.strip() or f"预测 {uploaded.name} 中的二分类目标",
        }
        st.session_state["request"] = st.session_state["upload"]["request"]
        st.session_state["view_run"] = None
        st.rerun()
    elif prompt.text.strip():
        st.session_state["request"] = prompt.text.strip()
        st.session_state["view_run"] = None
        st.rerun()

page = st.session_state.get("page", "research")
if page == "compare":
    title, badge = "系统对比", None
elif focus:
    card = read_json(RUNS / focus / "scenario_card.json")
    own = bool(job_dir and focus == job_dir.name)
    title = card.get("title") or (st.session_state.get("request") if own else None) or focus
    strategy = run_strategy(RUNS / focus)["title"]
    if strategy:
        task = read_json(RUNS / focus / "summary.json").get("task_id")
        title = f"{project_names().get(task) or title} · {strategy}"
    badge = (
        ("运行中", "blue")
        if running
        else (("已完成", "green") if finished_focus else ("未完成", "orange"))
    )
else:
    title = st.session_state.get("request") or "新研究"
    badge = None
with head:
    if not drawer_open:
        st.button(
            ":material/menu:",
            key="drawer-open",
            help="打开项目栏",
            type="tertiary",
            on_click=toggle,
            args=("drawer",),
        )
    st.markdown(f"**{title}**")
    if badge:
        st.badge(badge[0], color=badge[1])
    st.space("stretch")
    st.button(
        ":material/right_panel_open:" if ws_hidden else ":material/right_panel_close:",
        key="ws-toggle",
        help="显示工作区" if ws_hidden else "隐藏工作区",
        type="tertiary",
        on_click=toggle,
        args=("ws_hidden",),
    )

if not ws_hidden:
    highlight: set[str] = set()
    if focus and finished_focus:
        thread = (st.session_state.get("qa_threads") or {}).get(focus) or []
        last = next((turn for turn in reversed(thread) if turn.get("answer")), None)
        if last:
            highlight = {
                link.path
                for link in answer_links(RUNS, focus, last.get("evidence", []), last["answer"])
            }
    with columns[-1]:
        show_workspace(focus, running, highlight, tall=not st.session_state.get("panel_open", True))
        show_panel(focus, running)

with scroll:
    if page == "compare":
        show_compare()
    elif focus:
        own = bool(job_dir and focus == job_dir.name)
        with st.chat_message("user"):
            card = read_json(RUNS / focus / "scenario_card.json")
            st.write(
                (st.session_state.get("request") if own else None)
                or card.get("business_question")
                or focus
            )
        protocol_summary(focus)
        live(show_process, running)(focus, running)
        if finished_focus:
            show_conclusion(focus)
            show_open_qa(focus)
        elif not running:
            st.info("这次研究还没有最终汇总，可能已中断。研究过程和文件仍可查看。")
            log_path = ROOT / "ui_state" / "research.log"
            if own and log_path.is_file():
                with st.expander("运行日志末尾"):
                    st.code(log_path.read_text(encoding="utf-8", errors="replace")[-2000:])
    elif starting:
        with st.chat_message("user"):
            st.write(st.session_state.get("request") or "开始研究")
        st.fragment(show_starting, run_every="2s")()
    elif "request" in st.session_state:
        show_setup_flow()
    else:
        show_empty_state()

if st.session_state.pop("settle_rerun", False):
    time.sleep(1.0)
    st.rerun()
