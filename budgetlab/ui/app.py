"""Chat-first, read-only presentation of a BudgetLab research run.

Start with ``streamlit run budgetlab/ui/app.py`` from the repository root.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import streamlit as st
import yaml

from budgetlab.qa.evidence import EvidenceStore
from budgetlab.qa.faq import QUICK_QUESTIONS, answer_quick

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "runs"
DATA = ROOT / "data"
STORE = EvidenceStore(RUNS, ROOT / "results")
TASKS = {
    "Bank Marketing": ("bank_marketing", ROOT / "configs/bank_marketing.yaml"),
    "Breast Cancer (offline smoke)": ("breast_cancer", ROOT / "configs/night_smoke.yaml"),
}
EVENT_LABELS = {
    "profile_written": "📊 数据画像",
    "baseline_completed": "📏 基线训练",
    "calibration_completed": "🎚️ 门槛标定",
    "contract_frozen": "🔒 研究协议冻结",
    "candidate_rejected": "🚫 候选被拒绝",
    "candidate_selected": "🧪 候选被选中",
    "experiment_completed": "🧪 实验完成",
    "experiment_failed": "⚠️ 实验失败",
    "evaluation_recorded": "✅ 裁决已记录",
    "tool_search_started": "🔎 规则搜索开始",
    "direction_changed": "🔄 调整方向",
    "stop_decided": "⏹️ 停止决策",
    "confirmation_completed": "✅ 新切分确认",
    "delivery_frozen": "📦 交付冻结",
    "run_terminal": "🏁 研究完成",
}


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
    path = ROOT / "budgetlab" / "tasks" / "cards" / f"{task_id}.yaml"
    card = yaml.safe_load(path.read_text(encoding="utf-8"))
    return card


def launch(task_id: str, config_path: Path) -> dict:
    RUNS.mkdir(exist_ok=True)
    before = {path.name for path in RUNS.iterdir() if path.is_dir()}
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
        "scripted",
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


st.set_page_config(page_title="BudgetLab 研究助手", page_icon="🧪", layout="wide")
st.title("🧪 BudgetLab 研究助手")
st.caption("从任务协议到训练证据，再到一次性评测。当前演示使用脚本化提案，未使用 LLM。")

view = st.radio("页面", ["研究过程", "系统对比"], horizontal=True)
if view == "系统对比":
    matrices = sorted((ROOT / "results").glob("final-*/aggregate.json"), reverse=True)
    label = "正式成绩"
    if not matrices:
        matrices = sorted((ROOT / "results").glob("dev-*/aggregate.json"), reverse=True)
        label = "开发数据（仅用于搭建页面，不是正式成绩）"
    if matrices:
        matrix = matrices[0]
        rows = json.loads(matrix.read_text(encoding="utf-8"))
        st.subheader(label)
        st.caption(f"来源：{matrix.parent.relative_to(ROOT)}；random_search 的提案来源为 none。")
        st.dataframe(rows, hide_index=True, use_container_width=True)
    else:
        st.info("当前分支尚未包含 results/dev-* 或 results/final-* 对照数据。")
    st.stop()

with st.sidebar:
    task_name = st.selectbox("示例任务", list(TASKS))
    task_id, config_path = TASKS[task_name]
    st.write("进度")
    active = st.session_state.get("job")
    if active:
        st.write(f"运行中：{active.get('run_id') or '启动中'}")
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
                )

prompt = st.chat_input("描述你的机器学习任务（当前可使用示例任务）")
if prompt:
    st.session_state["request"] = prompt
if "request" not in st.session_state:
    st.info("请描述任务，或输入“用示例数据开始”，查看并确认研究协议。")
    st.stop()

with st.chat_message("user"):
    st.write(st.session_state["request"])

card = protocol_card(task_id)
with st.chat_message("assistant"):
    st.write("请确认研究协议。此协议来自仓库已有的场景卡，未使用 LLM。")
    st.write(f"**任务：** {card['title']}")
    st.write(f"**预测时点：** {card['prediction_time']}")
    st.write(f"**目标列：** {card['target']['column']}（正类：{card['target']['positive_label']}）")
    st.write(f"**指标：** {('macro-F1' if task_id == 'bank_marketing' else '配置文件指定')}")
    st.dataframe(
        [
            {
                "字段": field["name"],
                "可用性": field["availability"],
                "理由": field.get("note", field.get("description", "")),
            }
            for field in card["fields"]
        ],
        hide_index=True,
        use_container_width=True,
    )
    confirmed = st.checkbox("我确认目标列、预测时点和字段可用性", key="protocol_confirmed")

with st.chat_message("assistant"):
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    budget = config["budget"]
    st.write(
        f"**研究预算：** 最多 {budget['max_experiments']} 次实验；"
        f"系统 `budgetlab`，提案来源 `scripted`（0 Token）。"
    )
    ready = (DATA / "prepared" / task_id / "development.csv").is_file()
    if not ready:
        st.warning("当前任务数据尚未准备。Bank 首次准备需下载数据；Breast Cancer 示例可离线准备。")
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
        st.session_state["job"] = launch(task_id, config_path)
        st.rerun()

job = st.session_state.get("job")
if not job:
    st.stop()
run_dir = locate_run(job)
if run_dir is None:
    if job["process"].poll() is not None:
        st.error("研究进程在创建 run 目录前退出。请查看 ui_state/research.log。")
    else:
        st.info("研究进程正在启动。")
    if st.button("刷新进度"):
        st.rerun()
    st.stop()

events = read_events(run_dir)
with st.chat_message("assistant"):
    st.write(f"**研究过程：** `{run_dir.name}`")
    for event in events:
        kind = event.get("event_type", "")
        if kind in EVENT_LABELS:
            with st.expander(f"{EVENT_LABELS[kind]} · {event.get('seq', '?')}"):
                st.json(event)
    if not (run_dir / "summary.json").is_file():
        if job["process"].poll() is None:
            st.info("研究仍在进行。点击刷新查看新增步骤。")
        else:
            st.error("研究进程已退出，但没有生成 summary.json；请查看运行日志。")
        if st.button("刷新进度"):
            st.rerun()
        log_path = ROOT / "ui_state" / "research.log"
        if log_path.is_file():
            with st.expander("运行日志末尾"):
                st.code(log_path.read_text(encoding="utf-8", errors="replace")[-2000:])
        st.stop()

summary = STORE.get_summary(run_dir.name)
with st.chat_message("assistant"):
    st.write("### 研究结论")
    st.write(
        f"基线：{summary.get('baseline_score')}；交付模型：{summary.get('delivered_dev_score')}"
    )
    st.write(
        f"确认状态：{summary.get('confirmation_status')}；代码版本：{summary.get('code_version')}"
    )
    st.caption("数值来自本次 run 的 summary.json；当前未使用 LLM。")
    evaluation = STORE.get_final_evaluation(run_dir.name)
    if evaluation:
        st.write(f"Holdout：{evaluation.get('holdout_score')}（已评测）")
    elif st.button("运行一次 holdout 评测"):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "budgetlab.cli",
                "evaluate",
                "--run-id",
                run_dir.name,
                "--runs-root",
                str(RUNS),
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

for question_id, question in QUICK_QUESTIONS.items():
    if st.button(question, key=f"faq-{question_id}"):
        response = answer_quick(question_id, run_dir.name, STORE)
        with st.chat_message("assistant"):
            st.write(response["answer"])
            st.caption(f"证据：runs/{run_dir.name}/summary.json · 0 Token")
