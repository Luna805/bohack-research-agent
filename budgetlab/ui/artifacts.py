"""Turn an answer's evidence into run files the page can link and open (read-only, no Streamlit).

The page links each file as ``?run=<run id>&file=<path inside the run>`` and shows it in a
read-only viewer. Only text files inside one run directory are linked or opened. The score
curve has no file of its own: it is drawn from the ``trajectory`` in ``summary.json``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

VIEWABLE_SUFFIXES = {".json", ".jsonl", ".md", ".log", ".csv", ".txt"}
CURVE = "curve"  # the score curve, drawn from summary.json
INTERMEDIATE, CURVES, FINAL = "中间关键结果", "曲线", "最终结果"
GROUPS = (INTERMEDIATE, CURVES, FINAL)
MAX_EXPERIMENTS = 6

_EXPERIMENT_ID = re.compile(
    r"(?<![A-Za-z0-9_-])(r\d{2}-c\d+|tool-\d+|calibration-\d+|baseline)(?![A-Za-z0-9_-])"
)
_FINAL_FILES = (
    ("summary.json", "运行汇总", "基线、交付分数、预算和停止原因"),
    ("confirmation.json", "新切分复核", "交付模型在新的随机切分上是否仍优于基线"),
    ("delivery/frozen_delivery.json", "交付模型冻结记录", "配置哈希和重新训练的数据"),
    ("final_evaluation.json", "Holdout 评测", "封存数据上的一次性评测结果"),
    ("report.md", "研究报告", "本次研究的完整报告"),
)


@dataclass(frozen=True)
class ArtifactLink:
    group: str  # one of GROUPS
    item: str  # what the row is about, e.g. "实验 r05-c1（交付模型）"
    path: str  # path inside the run directory, or CURVE
    note: str  # what the file holds (tooltip and viewer header)

    def href(self, run_id: str) -> str:
        return "?" + urlencode({"run": run_id, "file": self.path}, safe="/")

    def markdown(self, run_id: str) -> str:
        link = f'({self.href(run_id)} "{self.note}")'
        if self.path == CURVE:
            return f"[打开曲线图]{link}（数据：`summary.json` 的 trajectory）"
        return f"[`{self.path}`]{link}"


def run_dir(runs_root: Path, run_id: str) -> Path | None:
    """The run directory when ``run_id`` names a direct child of ``runs_root``."""
    if not run_id:
        return None
    root = runs_root.resolve()
    path = (root / run_id).resolve()
    return path if path.parent == root and path.is_dir() else None


def resolve_artifact(runs_root: Path, run_id: str, relative: str) -> Path | None:
    """The file behind a link, or None if it is outside the run, missing or not a text file."""
    base = run_dir(runs_root, run_id)
    if base is None or not relative or relative == CURVE:
        return None
    path = (base / relative).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        return None
    return path if path.suffix.lower() in VIEWABLE_SUFFIXES else None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _llm_calls(base: Path) -> list[dict]:
    path = base / "llm_calls.jsonl"
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return [row for row in rows if isinstance(row, dict)]


def answer_links(
    runs_root: Path, run_id: str, evidence: list[dict], answer: str = ""
) -> list[ArtifactLink]:
    """Files behind one answer: cited and named experiments, rounds and LLM calls, the score
    curve and the run's final results. Every file is checked to exist; ids are never trusted."""
    base = run_dir(runs_root, run_id)
    if base is None:
        return []
    summary = _read_json(base / "summary.json")
    summary = summary if isinstance(summary, dict) else {}
    links: list[ArtifactLink] = []

    def add(group: str, item: str, path: str | None, note: str, *, skip_empty=False) -> None:
        if not path or any(link.path == path for link in links):
            return
        file = None if path == CURVE else resolve_artifact(runs_root, run_id, path)
        if path != CURVE and (file is None or (skip_empty and file.stat().st_size == 0)):
            return
        links.append(ArtifactLink(group, item, path, note))

    experiments: list[str] = []
    rounds: list[int] = []
    actions: list[str] = []
    for ref in evidence:
        kind, ref_id = ref.get("kind"), str(ref.get("ref_id", "")).strip()
        if kind == "experiment" and ref_id:
            experiments.append(ref_id)
        elif kind == "round" and ref_id.isdigit():
            rounds.append(int(ref_id))
        elif kind == "llm_call" and ref_id:
            actions.append(ref_id)
    experiments.extend(_EXPERIMENT_ID.findall(answer))
    delivered = summary.get("delivered_experiment_id")
    if delivered:
        experiments.append(str(delivered))

    for experiment in list(dict.fromkeys(experiments))[:MAX_EXPERIMENTS]:
        item = f"实验 {experiment}" + ("（交付模型）" if experiment == delivered else "")
        add(INTERMEDIATE, item, f"experiments/{experiment}.json", "配置、各折分数和假设检验")
        add(INTERMEDIATE, item, f"evaluations/{experiment}.json", "程序裁决：对比基线和此前最优")
        # Successful fits usually leave empty logs; link them only when they say something.
        add(INTERMEDIATE, item, f"logs/{experiment}.stdout.log", "训练输出", skip_empty=True)
        add(INTERMEDIATE, item, f"logs/{experiment}.stderr.log", "警告和错误", skip_empty=True)

    calls = _llm_calls(base)
    by_action = {str(call.get("action_id")): call for call in calls}
    for index in dict.fromkeys(rounds):
        item = f"第 {index} 轮"
        add(INTERMEDIATE, item, f"rounds/round-{index:02d}.json", "本轮提案、选中的候选和结果")
        for call in calls:
            if call.get("round") == index and call.get("role") == "proposer":
                add(INTERMEDIATE, item, call.get("output_ref"), "LLM 提案原文")
    for action in dict.fromkeys(actions):
        call = by_action.get(action)
        if call:
            item = f"LLM 调用 {action}"
            add(INTERMEDIATE, item, call.get("output_ref"), "模型输出原文")
            add(INTERMEDIATE, item, call.get("context_ref"), "发给模型的上下文")

    if summary.get("trajectory"):
        metric = summary.get("primary_metric") or "开发集分数"
        add(CURVES, f"得分曲线（{metric}）", CURVE, "每个实验的开发集分数和截至当时的最优分")
    for path, item, note in _FINAL_FILES:
        add(FINAL, item, path, note)
    return links


def links_markdown(run_id: str, links: list[ArtifactLink]) -> str:
    """One bullet per item, grouped; link text is the file's place inside the run."""
    lines: list[str] = []
    for group in GROUPS:
        rows: dict[str, list[ArtifactLink]] = {}
        for link in links:
            if link.group == group:
                rows.setdefault(link.item, []).append(link)
        if not rows:
            continue
        lines.append(f"**{group}**\n")
        for item, items in rows.items():
            lines.append(f"- {item}：" + " · ".join(link.markdown(run_id) for link in items))
        lines.append("")
    return "\n".join(lines).strip()


def curve_rows(summary: dict) -> list[dict]:
    """One row per trajectory point: the experiment's own score and the best so far."""
    scores = {
        str(row.get("id")): row.get("mean_score")
        for row in summary.get("experiments") or []
        if isinstance(row, dict)
    }
    rows = []
    for point in summary.get("trajectory") or []:
        best = point.get("best_score_after")
        if best is None:
            continue
        experiment = str(point.get("experiment_id", ""))
        own = point.get("mean_score", scores.get(experiment))
        rows.append(
            {
                "序号": len(rows) + 1,
                "实验": experiment,
                "来源": point.get("origin") or "",
                "轮次": point.get("round"),
                "本实验分数": own,
                "历史最优": best,
                "累计 Token": point.get("llm_tokens_so_far", 0),
                "累计秒数": point.get("elapsed_seconds", 0),
            }
        )
    return rows
