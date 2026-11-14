"""Template report filled only from program-computed facts in the run summary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .ledger import atomic_write_json


def _fmt(value: object, digits: int = 4) -> str:
    if value is None:
        return "–"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _spec_text(spec: dict[str, Any]) -> str:
    model = dict(spec["model"])
    family = model.pop("family")
    params = ", ".join(f"{key}={value}" for key, value in model.items())
    text = f"{family}({params})"
    actions = spec.get("feature_actions") or []
    if actions:
        text += " + " + "; ".join(
            f"{action['kind']}({','.join(action['columns'])}"
            + (f"={action['value']}" if "value" in action else "")
            + ")"
            for action in actions
        )
    return text


def write_report(run_dir: Path, summary: dict[str, Any]) -> Path:
    report = run_dir / "report.md"
    counts = summary["counts"]
    llm = summary["llm"]
    final_eval_path = run_dir / "final_evaluation.json"
    final_eval = (
        json.loads(final_eval_path.read_text(encoding="utf-8"))
        if final_eval_path.exists()
        else None
    )
    lines = [
        f"# BudgetLab run `{summary['run_id']}`",
        "",
        f"- task: `{summary['task_id']}` · system: `{summary['system']}` · "
        f"proposals: `{summary['proposal_source']}`",
        f"- primary metric: `{summary['primary_metric']}` (development 5-fold CV); "
        f"frozen min_effect = {_fmt(summary['min_effect'])}",
        f"- stop reason: `{summary['stop_reason']}` · wall time: {summary['wall_seconds']} s",
        f"- code version: `{summary.get('code_version', 'unknown')}`",
        "",
        "## Result",
        "",
        "| item | value |",
        "|---|---|",
        f"| baseline dev score | {_fmt(summary['baseline_score'])} |",
        f"| exploration best | {_fmt(summary['exploration_best_score'])} "
        f"(`{summary['exploration_best_id']}`) |",
        f"| finalist | `{summary['finalist_id']}` |",
        f"| confirmation on unseen split seeds | `{summary['confirmation_status']}` "
        f"{[round(d, 4) for d in summary['confirmation_deltas']]} |",
        f"| delivered | `{summary['delivered_experiment_id']}` · dev score "
        f"{_fmt(summary['delivered_dev_score'])} |",
        f"| sealed holdout score | "
        f"{_fmt(final_eval['holdout_score']) if final_eval else 'not evaluated yet'} |",
        "",
        "## Cost",
        "",
        f"- LLM calls: {llm['calls']} · requests: {llm['requests']} · tokens: {llm['tokens']} · "
        f"cost (USD, priced calls only): {llm['cost_usd']}",
        f"- by role: `{json.dumps(llm['by_role'])}`",
        f"- unknown (not reported by provider): `{json.dumps(llm['unknown'])}`",
        f"- training jobs: {summary['budget']['used']['experiments']} · estimator fits: "
        f"{summary['budget']['used']['fits']} · training seconds: "
        f"{round(summary['budget']['used']['seconds'], 1)}",
        "",
        "## Process",
        "",
        f"- rounds: {counts['rounds']} · experiments: {counts['experiments']} "
        f"(proposer {counts['proposer_experiments']}, tool search "
        f"{counts['tool_search_experiments']}) · failed: {counts['failed_experiments']}",
        f"- passed vs baseline: {counts['passed_vs_baseline']} · duplicates blocked: "
        f"{counts['duplicates_blocked']} · invalid rejected: {counts['invalid_rejected']} · "
        f"empty rounds: {counts['empty_rounds']}",
        f"- hypothesis verdicts (vs declared comparator): "
        f"`{json.dumps(counts['hypothesis_verdicts'])}`",
        f"- direction changes by trigger: `{json.dumps(counts['direction_changes'])}`",
        "",
        "## Experiments",
        "",
        "| id | origin | spec | dev score | Δ vs base | verdict | Δ vs prev best | hypothesis |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in summary["experiments"]:
        lines.append(
            f"| `{row['id']}` | {row['origin']} | {_spec_text(row['spec'])} | "
            f"{_fmt(row['mean_score'])} | {_fmt(row['delta_vs_baseline'])} | "
            f"{row.get('baseline_verdict') or '–'} | {_fmt(row['delta_vs_previous_best'])} | "
            f"{(row.get('hypothesis') or '').replace('|', '/')[:120]} |"
        )
    lines += [
        "",
        "## Evidence boundaries",
        "",
        "- Every score, delta and verdict above is computed by the evaluator from real fits; "
        "proposals never write metrics.",
        "- Verdicts are engineering thresholds (paired same-fold delta ≥ min_effect, then "
        "re-checked on unseen split seeds), not significance tests.",
        "- The sealed holdout is not read during research; it is scored once after delivery "
        "is frozen (`budgetlab evaluate`).",
    ]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    atomic_write_json(run_dir / "summary.json", summary)
    return report
