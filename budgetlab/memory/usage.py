"""What happened to the lessons a run retrieved: cited, tested, and the program verdicts.

Retrieval is not improvement. A lesson counts as ``tested`` only when an experiment in this
run reused its exact spec or repeated its action against the same kind of comparator, and its
outcome is whatever the program verdict said.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..contracts import spec_hash
from ..schemas import ExperimentSpec
from .extract import observations


def _cited(run_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """lesson ref -> candidates that cited it in evidence_refs (whether or not they ran)."""
    cited: dict[str, list[dict[str, Any]]] = {}
    for path in sorted((run_dir / "rounds").glob("round-*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        proposal = record.get("proposal") or {}
        for candidate in proposal.get("candidates", []):
            for ref in candidate["hypothesis"]["evidence_refs"]:
                if ref.startswith("lesson:"):
                    cited.setdefault(ref, []).append(
                        {"round": record["round_index"], "candidate_id": candidate["candidate_id"]}
                    )
    return cited


def lesson_usage(run_dir: Path, retrieved: list[dict[str, Any]]) -> dict[str, Any]:
    found = observations(run_dir)
    by_spec: dict[str, list[dict[str, Any]]] = {}
    by_candidate: dict[tuple[int, str], dict[str, Any]] = {}
    for path in sorted((run_dir / "experiments").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("origin") not in ("proposer", "tool_search"):
            continue
        digest = spec_hash(ExperimentSpec.model_validate(payload["spec"]))
        verdict = (payload.get("vs_baseline") or {}).get("policy_status")
        row = {
            "experiment_id": payload["experiment_id"],
            "origin": payload["origin"],
            "comparator": "baseline",
            "verdict": verdict or payload["result"].get("status"),
            "delta": (payload.get("vs_baseline") or {}).get("mean_paired_delta"),
        }
        by_spec.setdefault(digest, []).append({**row, "match": "same_spec"})
        if payload.get("candidate_id"):
            by_candidate[(payload["round"], payload["candidate_id"])] = row
    cited = _cited(run_dir)
    rows = []
    for lesson in retrieved:
        tested = list(by_spec.get(lesson["action"]["spec_hash"], []))
        seen = {item["experiment_id"] for item in tested}
        for ref in cited.get(f"lesson:{lesson['lesson_id']}", []):
            ran = by_candidate.get((ref["round"], ref["candidate_id"]))
            if ran is not None and ran["experiment_id"] not in seen:
                tested.append({**ran, "match": "cited_adapted"})
                seen.add(ran["experiment_id"])
        for item in found:
            obs = item["observation"]
            if item["action_key"] == lesson["action_key"] and obs.experiment_id not in seen:
                tested.append(
                    {
                        "experiment_id": obs.experiment_id,
                        "match": "same_action",
                        "comparator": obs.comparator,
                        "verdict": obs.verdict,
                        "delta": obs.delta,
                    }
                )
        verdicts = [t["verdict"] for t in tested]
        rows.append(
            {
                "lesson_id": lesson["lesson_id"],
                "cited_by": cited.get(f"lesson:{lesson['lesson_id']}", []),
                "tested": tested,
                "outcome": "untested"
                if not tested
                else "helpful"
                if any(v in ("candidate_pass", "confirmed_pass") for v in verdicts)
                else "not_helpful",
            }
        )
    return {
        "retrieved": len(retrieved),
        "cited": sum(bool(row["cited_by"]) for row in rows),
        "tested": sum(bool(row["tested"]) for row in rows),
        "helpful": sum(row["outcome"] == "helpful" for row in rows),
        "not_helpful": sum(row["outcome"] == "not_helpful" for row in rows),
        "lessons": rows,
    }
