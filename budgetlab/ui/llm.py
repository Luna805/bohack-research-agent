"""LLM wiring for the research page: availability, settings and call logs (no Streamlit).

The page uses the same ``llm`` and ``budget`` settings as the official matrix
(``configs/benchmark/final.yaml``), so a page run behaves like a matrix run. Credentials are
only read from the environment or ``.env`` by ``LLMSettings``; nothing here prints them.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import Any

import yaml

from ..benchmark import deep_merge
from ..ledger import utc_now
from ..proposers import CallOutcome, LLMSettings, load_dotenv

FINAL_MATRIX = Path("configs/benchmark/final.yaml")


def llm_overrides(root: Path) -> dict[str, Any]:
    """The ``budget`` and ``llm`` overrides of the official matrix (A's verified settings)."""
    matrix = yaml.safe_load((root / FINAL_MATRIX).read_text(encoding="utf-8"))
    overrides = matrix.get("overrides", {})
    return {key: overrides[key] for key in ("budget", "llm") if key in overrides}


def llm_problem(root: Path) -> str | None:
    """None when live LLM calls are possible, otherwise a short reason shown on the page."""
    load_dotenv(root / ".env")
    if importlib.util.find_spec("pydantic_ai") is None:
        return "未安装 LLM 依赖（uv sync --extra llm）"
    if not os.environ.get("LLM_MODEL") or not os.environ.get("LLM_API_KEY"):
        return "没有找到 LLM 配置（.env 里的 LLM_MODEL 和 LLM_API_KEY）"
    return None


def llm_settings(root: Path) -> LLMSettings:
    return LLMSettings.from_config({"llm": llm_overrides(root).get("llm", {})})


def research_config(base: dict[str, Any], proposer: str, root: Path) -> dict[str, Any]:
    """The config a page run uses: unchanged for scripted, matrix LLM settings for llm."""
    if proposer != "llm":
        return base
    config = deep_merge(base, llm_overrides(root))
    config["proposer"] = "llm"
    return config


def log_call(path: Path, kind: str, outcome: CallOutcome, **extra: Any) -> None:
    """Append one metered call (protocol draft or open question) to a ``ui_state`` log."""
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp": utc_now(),
        "kind": kind,
        **extra,
        "usage": outcome.usage.model_dump(),
        "unknown": outcome.unknown.model_dump(),
        "details": outcome.details,
        "error": outcome.error,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
