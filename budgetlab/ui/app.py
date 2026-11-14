"""Chat-first, read-only presentation of a BudgetLab research run.

Start with ``streamlit run budgetlab/ui/app.py`` from the repository root.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from importlib import import_module
from pathlib import Path

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
from budgetlab.ui.llm import llm_problem, llm_settings, log_call, research_config
from budgetlab.ui.presentation import artifact_preview, event_card, load_matrix, trajectory_rows

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "runs"
DATA = ROOT / "data"
STORE = EvidenceStore(RUNS, ROOT / "results")
TASKS = {
    "Bank Marketing": ("bank_marketing", ROOT / "configs/bank_marketing.yaml"),
    "Adult Income": ("adult", ROOT / "configs/adult.yaml"),
    "Breast Cancer (offline smoke)": ("breast_cancer", ROOT / "configs/night_smoke.yaml"),
}
LLM_CALLS = ROOT / "ui_state" / "llm_calls.jsonl"
QA_CALLS = ROOT / "ui_state" / "qa_calls.jsonl"
QA_LIMITS = {"requests": 20, "tokens": 50_000}  # per page session (INTERFACES 8.4)


def fmt(value: object, digits: int = 4) -> str:
    return f"{value:.{digits}f}" if isinstance(value, int | float) else "—"


def holdout_text(evaluation: dict) -> str:
    text = f"Holdout：{fmt(evaluation.get('holdout_score'))}"
    interval = evaluation.get("holdout_ci95")
    if interval and len(interval) == 2:
        text += f"（95% 区间 {fmt(interval[0])}–{fmt(interval[1])}）"
    return text + "，已评测"


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


def launch(task_id: str, config_path: Path, proposer: str) -> dict:
    RUNS.mkdir(exist_ok=True)
    before = {path.name for path in RUNS.iterdir() if path.is_dir()}
    if proposer == "llm":
        # Page runs reuse the official matrix's LLM budget and settings; shared configs stay put.
        base = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        config_path = ROOT / "ui_state" / "configs" / f"{task_id}-llm.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            yaml.safe_dump(research_config(base, "llm", ROOT), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    command = [
        sys.executable,
        "-m",
        "budgetlab.cli",
        "research",
        "--config",
        str(config_path),
        "--system",
        "budgetlab",
        "--proposer",
        proposer,
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
        "proposer": proposer,
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
    """Run the explicit, one-shot holdout command and return a user-facing error."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "budgetlab.cli",
            "evaluate",
            "--run-id",
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


def show_timeline(cards: list[dict], run_dir: Path, *, key: str) -> None:
    """Keep the story readable while leaving every raw event available."""
    st.caption(f"{len(cards)} 条关键事件，按研究顺序记录。")
    show_all = st.toggle("显示全部事件", key=f"all-events-{key}")
    if show_all:
        visible = cards
    else:
        first_by_stage = {}
        for card in cards:
            first_by_stage.setdefault(card["stage"], card)
        selected = {card["seq"] for card in first_by_stage.values()}
        selected.update(
            card["seq"]
            for card in cards
            if card["raw"]["event_type"] in {"llm_call_completed", "llm_call_failed"}
            or (
                card["raw"]["event_type"] == "evaluation_recorded"
                and (card["raw"].get("details") or {}).get("new_best")
            )
        )
        selected.update(card["seq"] for card in cards[-4:])
        visible = [card for card in cards if card["seq"] in selected]
        if len(visible) < len(cards):
            st.write("显示每个阶段的首个步骤、各轮提案、刷新最优分的裁决和最近 4 条事件。")
    for card in visible:
        with st.expander(f"{card['seq']}. {card['stage']} · {card['title']}"):
            if card["note"]:
                st.write(card["note"])
            for line in artifact_preview(run_dir, card):
                st.write(line)
            st.caption(f"证据文件：{card['artifact'] or 'events.jsonl'}")
            if show_all:
                st.json(card["raw"])


def reset_task_draft() -> None:
    for key in (
        "request",
        "protocol_confirmed",
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
                "它只看了开发数据的字段画像，没有看 holdout。请逐列核对后再确认。"
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
            st.session_state["protocol_confirmed"] = True
            st.rerun()


st.set_page_config(page_title="BudgetLab 研究助手", page_icon="🧪", layout="wide")
try:
    import_module("pyarrow")
except ImportError as exc:
    st.error("页面数据表无法加载：当前 PyArrow 与项目固定的 NumPy 版本不兼容。")
    st.code(r'.\.venv\Scripts\python.exe -m pip install "pyarrow==25.0.1"')
    st.caption(f"技术信息：{exc}")
    st.stop()
LLM_PROBLEM = llm_problem(ROOT)
st.title("BudgetLab 研究助手")
st.caption("确认任务协议 · 查看实验轨迹 · 核对结论证据")

view = st.segmented_control("页面", ["研究过程", "系统对比"], default="研究过程")
if view == "系统对比":
    matrix_data = load_matrix(ROOT / "results")
    if matrix_data:
        matrix, rows, formal = matrix_data
        st.subheader("正式成绩" if formal else "开发数据")
        if not formal:
            st.warning("这是一轮脚本化提案的开发数据，仅用于搭建和检查页面，不是正式成绩。")
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
            alt="各研究系统的开发集、holdout 分数和运行成本对比",
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
    st.stop()

with st.sidebar:
    task_name = st.selectbox(
        "示例任务",
        list(TASKS),
        disabled=bool(st.session_state.get("job")),
        on_change=reset_task_draft,
    )
    task_id, config_path = TASKS[task_name]
    if st.session_state.get("custom_task"):
        custom_id, custom_config = st.session_state["custom_task"]
        task_id, config_path = custom_id, Path(custom_config)
        st.caption("当前任务：你上传的 CSV")
    use_llm = st.toggle(
        "使用 LLM",
        value=LLM_PROBLEM is None,
        key="use_llm",
        disabled=LLM_PROBLEM is not None or bool(st.session_state.get("job")),
    )
    llm_on = use_llm and LLM_PROBLEM is None
    proposer = "llm" if llm_on else "scripted"
    if LLM_PROBLEM is not None:
        st.caption(f"{LLM_PROBLEM}：使用脚本化提案和快捷问题，不使用 LLM。")
    elif llm_on:
        st.caption("LLM 负责起草 CSV 协议、提出实验和回答开放问题；指标和裁决仍由程序计算。")
    else:
        st.caption("已关闭 LLM：使用脚本化提案和快捷问题。")
    history = STORE.list_runs()
    history_id = st.selectbox("查看已有研究", ["开始新研究", *[row["run_id"] for row in history]])
    st.write("当前进度")
    active = st.session_state.get("job")
    if active:
        st.write(f"运行中：{active.get('run_id') or '启动中'}")
        active_run_id = active.get("run_id")
        if active_run_id and (RUNS / active_run_id / "summary.json").is_file():
            st.success("研究已完成")
            if st.button("开始另一个任务"):
                for key in ("job", "request", "protocol_confirmed", "faq_answer", "qa_pending"):
                    st.session_state.pop(key, None)
                st.rerun()
    else:
        st.write("等待任务")
    if active and active.get("run_id"):
        summary_path = RUNS / active["run_id"] / "summary.json"
        if summary_path.is_file():
            trajectory = STORE.get_summary(active["run_id"]).get("trajectory", [])
            if trajectory:
                st.line_chart(
                    {"最优分": [point.get("best_score_after") for point in trajectory]},
                    x_label="实验序号",
                    alt="当前运行的最优分变化",
                )

if history_id != "开始新研究":
    history_dir = RUNS / history_id
    st.subheader("已有研究")
    st.caption(f"{history_id} · 数据来自本机 runs/，不属于正式成绩")
    if (history_dir / "summary.json").is_file():
        history_summary = STORE.get_summary(history_id)
        with st.container(horizontal=True):
            baseline = history_summary.get("baseline_score")
            delivered = history_summary.get("delivered_dev_score")
            st.metric("基线", f"{baseline:.3f}" if baseline is not None else "—", border=True)
            st.metric("交付模型", f"{delivered:.3f}" if delivered is not None else "—", border=True)
            st.metric("确认状态", history_summary.get("confirmation_status", "未知"), border=True)
        evaluation = STORE.get_final_evaluation(history_id)
        if evaluation:
            st.write(holdout_text(evaluation))
        elif st.button("运行一次 holdout 评测", key=f"history-evaluate-{history_id}"):
            if error := evaluate_run(history_id):
                st.error(error)
            else:
                st.rerun()
        for question_id, question in QUICK_QUESTIONS.items():
            if st.button(question, key=f"history-faq-{history_id}-{question_id}"):
                st.session_state["history_faq"] = (
                    history_id,
                    answer_quick(question_id, history_id, STORE),
                )
        if (saved := st.session_state.get("history_faq")) and saved[0] == history_id:
            st.write(saved[1]["answer"])
            st.caption(f"证据：runs/{history_id}/summary.json · 0 Token")
    else:
        st.info("这次研究还没有最终汇总，可能正在运行，也可能已中断。步骤仍可查看。")
    cards = [card for item in read_events(history_dir) if (card := event_card(item))]
    st.write("**研究步骤**")
    show_timeline(cards, history_dir, key=f"history-{history_id}")
    st.stop()

if "request" not in st.session_state:
    with st.container(border=True):
        st.subheader("快速演示")
        st.write("选择示例任务，或在下方对话框附上二分类 CSV。确认协议后再启动研究。")
        if st.button("用所选示例开始", type="primary"):
            st.session_state["request"] = protocol_card(task_id)["business_question"]
            st.rerun()


def finished_run_id() -> str | None:
    job = st.session_state.get("job")
    if job and job.get("run_id") and (RUNS / job["run_id"] / "summary.json").is_file():
        return job["run_id"]
    return None


finished = finished_run_id()
prompt = st.chat_input(
    "就这次研究追问，例如：为什么最后选了这个模型？" if finished else "描述任务，可附上二分类 CSV",
    accept_file=True,
    file_type="csv",
)
if prompt:
    if finished and not prompt.files and prompt.text.strip():
        st.session_state["qa_pending"] = (finished, prompt.text.strip())
    elif prompt.files:
        uploaded = prompt.files[0]
        raw = uploaded.getvalue()
        digest = hashlib.sha256(raw).hexdigest()[:16]
        path = ROOT / "ui_state" / "uploads" / f"{digest}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        st.session_state["upload"] = {
            "path": str(path),
            "digest": digest,
            "filename": uploaded.name,
            "request": prompt.text.strip() or f"预测 {uploaded.name} 中的二分类目标",
        }
        st.session_state["request"] = st.session_state["upload"]["request"]
        st.session_state.pop("custom_task", None)
        st.session_state.pop("protocol_confirmed", None)
        for key in (
            "upload-target",
            "upload-positive",
            "upload-time",
            "upload-metric",
            "upload-demo-card",
        ):
            st.session_state.pop(key, None)
    elif prompt.text.strip():
        st.session_state["request"] = prompt.text.strip()
if "request" not in st.session_state:
    st.info("输入一句任务描述，可附上二分类 CSV；也可以先选择示例任务。")
    st.stop()

with st.chat_message("user"):
    st.write(st.session_state["request"])

if st.session_state.get("upload"):
    show_upload_protocol(st.session_state["upload"], llm_on)
    st.stop()

card = protocol_card(task_id)
config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
with st.chat_message("assistant"):
    if task_id.startswith("upload-"):
        st.write("这是你刚才逐列确认的 CSV 协议；请在开跑前再次核对。")
    else:
        st.write("请确认研究协议。以下内容来自所选示例的场景卡，不是对输入文字的自动解析。")
    st.write(f"**任务：** {card['title']}")
    st.write(f"**预测时点：** {card['prediction_time']}")
    st.write(f"**目标列：** {card['target']['column']}（正类：{card['target']['positive_label']}）")
    st.write(f"**指标：** {config.get('primary_metric', 'f1_macro')}")
    fields = card["fields"]
    excluded = [field["name"] for field in fields if field["availability"] != "available"]
    if excluded:
        st.warning(f"预测时不能使用：{', '.join(excluded)}。请在确认前核对原因。")
    elif card.get("default_availability"):
        st.caption("此示例按场景卡的默认规则使用字段，具体列由数据准备阶段确定。")
    with st.expander(f"查看字段依据（{len(fields)} 项）"):
        if fields:
            st.dataframe(
                [
                    {
                        "字段": field["name"],
                        "可用性": field["availability"],
                        "理由": field.get("note", field.get("description", "")),
                    }
                    for field in fields
                ],
                hide_index=True,
                alt="示例任务各字段的可用性及原因",
            )
        else:
            st.write("该示例使用场景卡的默认字段可用性规则。")
    confirmed = st.checkbox("我确认目标列、预测时点和字段可用性", key="protocol_confirmed")

with st.chat_message("assistant"):
    run_config = research_config(config, proposer, ROOT)
    budget = run_config["budget"]
    if proposer == "llm":
        source = (
            f"提案来源 `llm`（{run_config['llm'].get('model') or os.environ.get('LLM_MODEL')}，"
            f"最多 {budget['max_llm_requests']} 次请求、{budget['max_llm_tokens']:,} Token）"
        )
    else:
        source = "提案来源 `scripted`（0 Token）"
    st.write(
        f"**研究预算：** 最多 {budget['max_experiments']} 次实验；系统 `budgetlab`，{source}。"
    )
    ready = (DATA / "prepared" / task_id / "development.csv").is_file()
    if not ready:
        st.warning(
            "当前任务数据尚未准备。Bank 和 Adult 首次准备需下载数据；Breast Cancer 可离线准备。"
        )
        if st.button("准备示例数据", disabled=not confirmed):
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
        "开始研究", disabled=not confirmed or not ready or bool(st.session_state.get("job"))
    ):
        st.session_state["job"] = launch(task_id, config_path, proposer)
        st.rerun()


@st.fragment(run_every="2s")
def show_active_run() -> None:
    job = st.session_state.get("job")
    if not job:
        return
    run_dir = locate_run(job)
    if run_dir is None:
        if job["process"].poll() is not None:
            st.error("研究进程在创建 run 目录前退出。请查看 ui_state/research.log。")
        else:
            st.info("研究进程正在启动，页面会自动更新。")
        return

    events = read_events(run_dir)
    with st.chat_message("assistant"):
        st.write(f"**研究过程：** `{run_dir.name}`")
        cards = [card for event in events if (card := event_card(event))]
        show_timeline(cards, run_dir, key=f"active-{run_dir.name}")
        if not (run_dir / "summary.json").is_file():
            if job["process"].poll() is None:
                st.info("研究仍在进行；步骤卡每 2 秒自动更新。")
            else:
                st.error("研究进程已退出，但没有生成 summary.json；请查看运行日志。")
            log_path = ROOT / "ui_state" / "research.log"
            if log_path.is_file():
                with st.expander("运行日志末尾"):
                    st.code(log_path.read_text(encoding="utf-8", errors="replace")[-2000:])
            return

    if not job.get("finished_seen"):
        # One full rerun so the sidebar and the chat box switch to the finished state.
        job["finished_seen"] = True
        st.rerun()
    summary = STORE.get_summary(run_dir.name)
    with st.chat_message("assistant"):
        st.write("### 研究结论")
        st.write(
            f"开发集：基线 {fmt(summary.get('baseline_score'))} → 交付模型 "
            f"{fmt(summary.get('delivered_dev_score'))}（{summary.get('delivered_experiment_id')}）"
        )
        st.write(
            f"确认状态：{summary.get('confirmation_status')}；"
            f"代码版本：{summary.get('code_version')}"
        )
        llm = summary.get("llm") or {}
        if summary.get("proposal_source") == "llm":
            st.caption(
                f"数值来自本次 run 的 summary.json；提案来自 LLM（{llm.get('requests', 0)} 次请求、"
                f"{llm.get('tokens', 0):,} Token），裁决由程序计算。"
            )
        else:
            st.caption("数值来自本次 run 的 summary.json；本次提案为脚本化，未使用 LLM。")
        evaluation = STORE.get_final_evaluation(run_dir.name)
        if evaluation:
            st.write(holdout_text(evaluation))
        elif st.button("运行一次 holdout 评测", key=f"evaluate-{run_dir.name}"):
            if error := evaluate_run(run_dir.name):
                st.error(error)
            else:
                st.rerun(scope="fragment")

    for question_id, question in QUICK_QUESTIONS.items():
        if st.button(question, key=f"faq-{question_id}"):
            st.session_state["faq_answer"] = (
                run_dir.name,
                answer_quick(question_id, run_dir.name, STORE),
            )
    saved_answer = st.session_state.get("faq_answer")
    if saved_answer and saved_answer[0] == run_dir.name:
        with st.chat_message("assistant"):
            st.write(saved_answer[1]["answer"])
            st.caption(f"证据：runs/{run_dir.name}/summary.json · 0 Token")


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


def show_open_qa(run_id: str) -> None:
    thread = st.session_state.setdefault("qa_threads", {}).setdefault(run_id, [])
    pending = st.session_state.pop("qa_pending", None)
    if pending and pending[0] == run_id:
        thread.append(ask_open_question(run_id, pending[1], thread))
    for turn in thread:
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


show_active_run()
if finished_run_id():
    show_open_qa(finished_run_id())
