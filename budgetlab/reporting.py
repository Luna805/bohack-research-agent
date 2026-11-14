from __future__ import annotations

from pathlib import Path
from typing import Any

from .ledger import atomic_write_json


def format_optional(value: object) -> str:
    return "not_available" if value is None else f"{float(value):.6f}"


def write_report(run_dir: Path, summary: dict[str, Any]) -> Path:
    report = run_dir / "report.md"
    budget = summary["budget"]
    lines = [
        f"# BudgetLab Run {summary['run_id']}",
        "",
        f"- proposal_source: `{summary['proposal_source']}`",
        f"- dataset: `{summary['dataset_ref']}`",
        f"- baseline_score: {summary['baseline_score']:.6f}",
        f"- exploration_best_score: {format_optional(summary.get('exploration_best_score'))}",
        f"- confirmation_status: `{summary['confirmation_status']}`",
        f"- delivered_spec_hash: `{summary['delivered_spec_hash']}`",
        f"- delivered_model: `{summary['model_ref']}`",
        "",
        "## Budget Evidence",
        "",
        f"- estimator_fit_attempts: {budget['used']['fits']}",
        f"- training_jobs: {budget['used']['experiments']}",
        f"- actual_llm_requests: {budget['used']['llm_requests']}",
        f"- known_api_cost_usd: {budget['used']['cost_usd']}",
        f"- unknown_resources: `{budget['unknown']}`",
        "",
        "## Evidence Boundaries",
        "",
        "This run used the real scikit-learn breast-cancer dataset and real estimator fits.",
        "Scripted proposals, when present, are offline controller tests, not LLM results.",
        "No project API request was authorized or made. No Kaggle holdout was accessed.",
        "Application-level separation exists; OS-level sandbox isolation was not verified.",
    ]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    atomic_write_json(run_dir / "summary.json", summary)
    return report
