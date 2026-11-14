"""Extract lesson drafts from a finished run's development artifacts.

Allowed fact sources: ``eda.json``, ``contract.json``, ``experiments/*.json`` and
``confirmation.json``. Never read: ``final_evaluation.json``, holdout predictions, ``data/sealed``.
LLM or critic text is never copied into a lesson; only program verdicts and spec differences.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..contracts import canonical_spec, spec_hash, stable_hash
from ..schemas import ExperimentSpec
from .models import Lesson, LessonAction, LessonConditions, Observation, ObservedEffect

EXPLORATION_ORIGINS = ("proposer", "tool_search")
COUNTED_VERDICTS = ("candidate_pass", "confirmed_pass", "not_met")
FEATURE_KIND_NEEDS = {
    "sentinel_to_missing": "possible_sentinel",
    "missing_indicator": "has_missing",
    "log1p": "skewed_numeric",
}
IMBALANCED_MAX_MINORITY = 0.35
ROWS_FACTOR = 5


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical(spec: dict[str, Any]) -> dict[str, Any]:
    return canonical_spec(ExperimentSpec.model_validate(spec))


def _changes(new: dict[str, Any], old: dict[str, Any], skip: tuple[str, ...] = ()) -> dict:
    keys = sorted((set(new) | set(old)) - set(skip))
    return {
        key: {"from": old.get(key), "to": new.get(key)}
        for key in keys
        if new.get(key) != old.get(key)
    }


def spec_diff(spec: dict[str, Any], comparator: dict[str, Any]) -> list[dict[str, Any]]:
    """Factor-level difference between a tested spec and its comparator (program-computed)."""
    new, old = _canonical(spec), _canonical(comparator)
    parts: list[dict[str, Any]] = []
    new_model, old_model = new["model"], old["model"]
    if new_model["family"] != old_model["family"]:
        params = {
            key: value
            for key, value in new_model.items()
            if key not in ("family", "class_weight") and value is not None
        }
        parts.append(
            {
                "factor": "model_family",
                "from": old_model["family"],
                "to": new_model["family"],
                "params": params,
            }
        )
    else:
        hyper = _changes(new_model, old_model, skip=("family", "class_weight"))
        if hyper:
            parts.append(
                {"factor": "hyperparameters", "family": new_model["family"], "changes": hyper}
            )
    if new_model.get("class_weight") != old_model.get("class_weight"):
        parts.append(
            {
                "factor": "class_weight",
                "from": old_model.get("class_weight"),
                "to": new_model.get("class_weight"),
            }
        )
    prep = _changes(new["preprocessing"], old["preprocessing"])
    if prep:
        parts.append({"factor": "preprocessing", "changes": prep})
    new_actions = {json.dumps(a, sort_keys=True): a for a in new["feature_actions"]}
    old_actions = {json.dumps(a, sort_keys=True): a for a in old["feature_actions"]}
    added = [new_actions[key] for key in sorted(set(new_actions) - set(old_actions))]
    removed = [old_actions[key] for key in sorted(set(old_actions) - set(new_actions))]
    if added or removed:
        parts.append({"factor": "feature_actions", "added": added, "removed": removed})
    return parts


def describe(parts: list[dict[str, Any]]) -> str:
    """Short human-readable action text built only from the parts."""
    texts = []
    for part in parts:
        factor = part["factor"]
        if factor == "model_family":
            params = ", ".join(f"{k}={v}" for k, v in sorted(part["params"].items()))
            texts.append(f"{part['to']}({params}) instead of {part['from']}")
        elif factor == "class_weight":
            texts.append(f"class_weight {part['from']} -> {part['to']}")
        elif factor == "hyperparameters":
            changes = ", ".join(f"{k} {v['from']} -> {v['to']}" for k, v in part["changes"].items())
            texts.append(f"{part['family']}: {changes}")
        elif factor == "preprocessing":
            texts.append(
                "preprocessing: "
                + ", ".join(f"{k} {v['from']} -> {v['to']}" for k, v in part["changes"].items())
            )
        else:
            added = [
                f"{a['kind']}({','.join(a['columns'])}"
                + (f"={a['value']}" if "value" in a else "")
                + ")"
                for a in part["added"]
            ]
            removed = [f"{a['kind']}({','.join(a['columns'])})" for a in part["removed"]]
            text = []
            if added:
                text.append("add " + " + ".join(added))
            if removed:
                text.append("remove " + " + ".join(removed))
            texts.append("; ".join(text))
    return "; ".join(texts)


def action_key(parts: list[dict[str, Any]]) -> str:
    return stable_hash(parts)[:12]


def _action(parts: list[dict[str, Any]], spec: dict[str, Any], confirmed: bool) -> LessonAction:
    kind = parts[0]["factor"] if len(parts) == 1 else "combined"
    return LessonAction(
        kind=kind,
        scope="confirmed_recipe" if confirmed else "single_comparison",
        parts=tuple(parts),
        summary=describe(parts),
        spec=_canonical(spec),
        spec_hash=spec_hash(ExperimentSpec.model_validate(spec)),
    )


def _minority_range(positive_rate: float) -> tuple[float, float]:
    minority = min(positive_rate, 1.0 - positive_rate)
    if minority < IMBALANCED_MAX_MINORITY:
        return (0.0, IMBALANCED_MAX_MINORITY)
    return (IMBALANCED_MAX_MINORITY, 0.5)


def _conditions(
    parts: list[dict[str, Any]], spec: dict[str, Any], eda: dict[str, Any], contract: dict
) -> LessonConditions:
    rows = int(eda["rows"])
    added = [a for part in parts if part["factor"] == "feature_actions" for a in part["added"]]
    needs = [FEATURE_KIND_NEEDS.get(a["kind"]) for a in added]
    kinds = sorted({need for need in needs if need is not None})
    columns = sorted({column for a in added for column in a["columns"]})
    return LessonConditions(
        primary_metric=contract["primary_metric"],
        rows_range=(max(1, rows // ROWS_FACTOR), rows * ROWS_FACTOR),
        minority_rate_range=_minority_range(float(eda.get("positive_rate", 0.5))),
        requires_families=(spec["model"]["family"],),
        requires_column_kinds=tuple(kinds),
        source_columns=tuple(columns),
        source_task_ids=(contract["task_id"],),
    )


def _exploration_payloads(run_dir: Path) -> dict[str, dict[str, Any]]:
    payloads = {}
    for path in sorted((run_dir / "experiments").glob("*.json")):
        value = _read(path)
        if value.get("origin") in ("baseline", *EXPLORATION_ORIGINS):
            payloads[value["experiment_id"]] = value
    return payloads


def observations(run_dir: Path) -> list[dict[str, Any]]:
    """One observation per judged exploration experiment, plus the confirmation if any."""
    contract = _read(run_dir / "contract.json")
    eda = _read(run_dir / "eda.json")
    run_id = run_dir.name
    min_effect = float(contract["decision_policy"]["min_effect"])
    metric = contract["primary_metric"]
    payloads = _exploration_payloads(run_dir)
    found: list[dict[str, Any]] = []

    def add(experiment_id: str, comparator_id: str, check: dict[str, Any], confirmed: bool) -> None:
        if check.get("policy_status") not in COUNTED_VERDICTS:
            return
        if check.get("mean_paired_delta") is None or comparator_id not in payloads:
            return
        spec = payloads[experiment_id]["spec"]
        parts = spec_diff(spec, payloads[comparator_id]["spec"])
        if not parts:
            return
        found.append(
            {
                "action_key": action_key(parts),
                "action": _action(parts, spec, confirmed),
                "conditions": _conditions(parts, spec, eda, contract),
                "observation": Observation(
                    task_id=contract["task_id"],
                    run_id=run_id,
                    experiment_id=experiment_id,
                    comparator=comparator_id,
                    metric=metric,
                    delta=float(check["mean_paired_delta"]),
                    min_effect=min_effect,
                    verdict=check["policy_status"],
                ),
            }
        )

    for experiment_id, payload in payloads.items():
        if payload["origin"] not in EXPLORATION_ORIGINS:
            continue
        if payload["result"].get("status") != "ok":
            continue
        check = payload.get("hypothesis_check") or payload.get("vs_baseline")
        if not check:
            continue
        comparator = check.get("comparator_experiment_id") or "baseline"
        add(experiment_id, comparator, check, confirmed=False)
    confirmation_path = run_dir / "confirmation.json"
    if confirmation_path.exists():
        confirmation = _read(confirmation_path)
        finalist = confirmation.get("experiment_id")
        if finalist in payloads:
            add(finalist, "baseline", confirmation, confirmed=True)
    return found


def _limitations(lesson_obs: list[Observation], conditions: LessonConditions) -> tuple[str, ...]:
    notes = [
        "Measured with paired same-fold development CV only; no holdout score was used.",
    ]
    if len({obs.run_id for obs in lesson_obs}) == 1:
        notes.append("Single source run; treat as a hypothesis to re-test, not a rule.")
    if conditions.source_columns:
        notes.append(
            "Feature actions name source-task columns; on new data apply them only to columns "
            "with the same property and the same prediction-time availability."
        )
    return tuple(notes)


def build_lessons(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group observations by action; only actions with at least one pass become lessons."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in found:
        groups.setdefault(item["action_key"], []).append(item)
    lessons = []
    for key, items in sorted(groups.items()):
        positive = [i for i in items if i["observation"].verdict != "not_met"]
        negative = [i["observation"] for i in items if i["observation"].verdict == "not_met"]
        if not positive:
            continue
        confirmed = [i for i in positive if i["observation"].verdict == "confirmed_pass"]
        lead = max(confirmed or positive, key=lambda i: i["observation"].delta)
        evidence = [i["observation"] for i in positive]
        conditions = _merge_conditions([i["conditions"] for i in items])
        support = len(evidence)
        status = "supported_in_sources" if confirmed else "candidate"
        if len(negative) > support:
            status = "deprecated"
        lessons.append(
            Lesson(
                lesson_id=f"L-{key}",
                action_key=key,
                conditions=conditions,
                action=lead["action"],
                observed_effect=ObservedEffect(
                    metric=lead["observation"].metric,
                    delta=round(lead["observation"].delta, 6),
                    comparator=lead["observation"].comparator,
                    run_id=lead["observation"].run_id,
                    experiment_ids=tuple(sorted({o.experiment_id for o in evidence})),
                    min_effect=lead["observation"].min_effect,
                ),
                support=support,
                counterexamples=tuple(negative),
                evidence=tuple(evidence),
                status=status,
                limitations=_limitations(evidence + negative, conditions),
            ).model_dump(mode="json")
        )
    return lessons


def _merge_conditions(items: list[LessonConditions]) -> LessonConditions:
    first = items[0]
    return first.model_copy(
        update={
            "rows_range": (
                min(c.rows_range[0] for c in items),
                max(c.rows_range[1] for c in items),
            ),
            "minority_rate_range": (
                min(c.minority_rate_range[0] for c in items),
                max(c.minority_rate_range[1] for c in items),
            ),
            "requires_families": tuple(sorted({f for c in items for f in c.requires_families})),
            "source_task_ids": tuple(sorted({t for c in items for t in c.source_task_ids})),
        }
    )


def extract_run(run_dir: Path) -> dict[str, Any]:
    """Lesson draft for one finished run (not published; publishing is a separate step)."""
    found = observations(run_dir)
    return {
        "run_id": run_dir.name,
        "task_id": _read(run_dir / "contract.json")["task_id"],
        "observations": len(found),
        "lessons": build_lessons(found),
    }


def merge_runs(run_dirs: list[Path]) -> list[dict[str, Any]]:
    """Lessons built from all observations of several finished runs (for a snapshot)."""
    found = [item for run_dir in run_dirs for item in observations(run_dir)]
    return build_lessons(found)
