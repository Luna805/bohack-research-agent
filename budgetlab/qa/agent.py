"""Open-question agent over one finished run's saved evidence (role A, INTERFACES 8.4).

The program, not the model, reads the evidence: it calls the read-only ``EvidenceStore``
tools, builds one compact context and makes exactly one metered LLM call (no tool loop, so
the request count stays bounded). The model returns an answer plus the evidence it cites. The
program then drops citations that do not exist and marks which numbers in the answer can be
found in the evidence. The agent cannot start runs, evaluate the holdout or write files; the
caller records its tokens in ``ui_state/qa_calls.jsonl``, separately from the research budget.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..proposers import CallOutcome, LLMSettings, _PydanticAIRole
from . import EvidenceKind, EvidenceRef, QAAnswer
from .evidence import EvidenceStore

MAX_ROUNDS = 30
MAX_HISTORY = 3
QA_MAX_OUTPUT_TOKENS = 1200
# Per page session (INTERFACES 8.4); enforced by the caller before each question.
SESSION_LIMITS = {"requests": 20, "tokens": 50_000}


class CitedEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: EvidenceKind
    ref_id: str = Field(min_length=1)


class QADraft(BaseModel):
    """What the model may return: words and citations. Verification is done by the program."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)
    evidence: list[CitedEvidence] = Field(default_factory=list)


QA_INSTRUCTIONS = """\
You answer questions about ONE finished BudgetLab research run, for a person watching a demo.
The input JSON has `question`, optional `history` (earlier turns) and `evidence`: the run
summary (scores, budget used, stop reason, confirmation), one row per experiment, the best
score after each experiment (`progress`), the proposals of each round, the LLM call records
and, only if it was run, the one-shot holdout evaluation.

Rules:
- Answer in the language of the question (Chinese if the question is Chinese), in at most
  about 120 words. Be concrete: name experiment ids, rounds and scores.
- Use ONLY facts in `evidence`. If the evidence does not contain the answer, say so plainly.
  Never guess numbers and do not compute new statistics beyond a simple difference.
- Copy numbers as they appear in the evidence (at most 4 decimals).
- Cite what you used in `evidence`. kind is one of summary, experiment, round, llm_call,
  final_evaluation; ref_id is the experiment id (e.g. "r05-c2"), the round number (e.g. "3"),
  the LLM call action_id (e.g. "llm:proposer:r01"), or "summary.json" / "final_evaluation.json".
- Verdicts such as candidate_pass, not_met and confirmed_pass are computed by the program,
  not by an LLM; say so if asked who decided. If `final_evaluation` is null the holdout was
  not evaluated: never state a holdout score then.
"""


class QAAgent(_PydanticAIRole):
    """One strict-output role; every token is reported through the returned ``CallOutcome``."""

    def __init__(self, settings: LLMSettings, *, model: Any | None = None) -> None:
        capped = dataclasses.replace(
            settings, max_output_tokens=min(settings.max_output_tokens, QA_MAX_OUTPUT_TOKENS)
        )
        super().__init__(capped, QADraft, QA_INSTRUCTIONS, model=model)

    def ask(self, context: dict[str, Any]) -> CallOutcome:
        return self._call(context)


# ------------------------------------------------------------------------------ evidence


def gather_evidence(store: EvidenceStore, run_id: str) -> dict[str, Any]:
    """Collect one run's evidence through the read-only store (no holdout rows, no data files)."""
    summary = store.get_summary(run_id)
    budget = summary.get("budget") or {}
    compact = {
        key: value
        for key, value in summary.items()
        if key not in {"budget", "trajectory", "experiments", "git"}
    }
    compact["budget"] = {key: budget.get(key) for key in ("limits", "used", "unknown")}
    final = store.get_final_evaluation(run_id)
    if final is not None:
        final = {
            key: final.get(key)
            for key in (
                "metric",
                "holdout_score",
                "holdout_ci95",
                "holdout_rows",
                "development_cv_score",
                "dev_minus_holdout",
                "delivered_experiment_id",
            )
        }
    return {
        "run_id": run_id,
        "summary": compact,
        "experiments": summary.get("experiments", []),
        "progress": [
            {
                key: point.get(key)
                for key in (
                    "experiment_id",
                    "best_score_after",
                    "elapsed_seconds",
                    "llm_tokens_so_far",
                )
            }
            for point in summary.get("trajectory", [])
        ],
        "rounds": _rounds(store, run_id),
        "llm_calls": [_call_row(call) for call in store.get_llm_calls(run_id)],
        "final_evaluation": final,
    }


def _rounds(store: EvidenceStore, run_id: str) -> list[dict[str, Any]]:
    rows = []
    for index in range(1, MAX_ROUNDS + 1):
        try:
            record = store.get_round(run_id, index)
        except FileNotFoundError:
            break
        proposal = record.get("proposal") or {}
        rows.append(
            {
                "round": record.get("round_index", index),
                "intent": record.get("intent"),
                "direction": record.get("direction"),
                "trigger": record.get("trigger_source"),
                "selected": record.get("selected"),
                "rejected": record.get("rejected"),
                "not_run": record.get("not_run"),
                "improved": record.get("improved"),
                "proposal_error": record.get("proposal_error"),
                "interpretation": proposal.get("previous_result_interpretation"),
                "hypotheses": [
                    {
                        "candidate_id": candidate.get("candidate_id"),
                        "change": (candidate.get("hypothesis") or {}).get("proposed_change"),
                        "predicted_delta": (candidate.get("hypothesis") or {}).get(
                            "predicted_metric_delta"
                        ),
                    }
                    for candidate in proposal.get("candidates", [])
                ],
            }
        )
    return rows


def _call_row(call: dict[str, Any]) -> dict[str, Any]:
    details = call.get("details") or {}
    return {
        "action_id": call.get("action_id"),
        "role": call.get("role"),
        "round": call.get("round"),
        "input_tokens": details.get("input_tokens"),
        "output_tokens": details.get("output_tokens"),
        "requests": details.get("requests"),
        "seconds": details.get("seconds"),
        "error": call.get("error"),
    }


def _rounded(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, dict):
        return {key: _rounded(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_rounded(item) for item in value]
    return value


# ------------------------------------------------------------------------------ verification

_NUMBER = re.compile(
    r"(?<![A-Za-z0-9_.:\-])(-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(%?)(?![A-Za-z0-9_:\-])"
)


def extract_numbers(text: str) -> list[str]:
    """Numbers as written in an answer, skipping ids such as ``r05-c2`` or run ids."""
    seen: list[str] = []
    for match in _NUMBER.finditer(text):
        token = match.group(1) + match.group(2)
        if token not in seen:
            seen.append(token)
    return seen


def _evidence_numbers(value: Any, found: list[float]) -> list[float]:
    if isinstance(value, bool):
        return found
    if isinstance(value, int | float):
        found.append(float(value))
    elif isinstance(value, str):
        for match in _NUMBER.finditer(value):
            found.append(float(match.group(1).replace(",", "")))
    elif isinstance(value, dict):
        for item in value.values():
            _evidence_numbers(item, found)
    elif isinstance(value, list):
        for item in value:
            _evidence_numbers(item, found)
    return found


def number_in_evidence(token: str, known: list[float]) -> bool:
    """True when the number matches an evidence value up to its own rounding (max 4 decimals).

    "7.1%" is compared as 0.071. Numbers written with more than 4 decimals must match to 4.
    """
    percent = token.endswith("%")
    digits = token.rstrip("%").replace(",", "")
    value = float(digits)
    decimals = len(digits.split(".")[1]) if "." in digits else 0
    tolerance = 0.5 * 10 ** -min(decimals, 4) + 1e-12
    candidates = [(value, tolerance)]
    if percent:
        candidates = [(value / 100, tolerance / 100)]
    return any(
        abs(known_value - target) <= tol for target, tol in candidates for known_value in known
    )


def _valid_ref(
    store: EvidenceStore, run_id: str, cited: CitedEvidence, call_ids: set[str]
) -> EvidenceRef | None:
    ref_id = cited.ref_id.strip()
    try:
        if cited.kind == "summary":
            store.get_summary(run_id)
            ref_id = "summary.json"
        elif cited.kind == "final_evaluation":
            if store.get_final_evaluation(run_id) is None:
                return None
            ref_id = "final_evaluation.json"
        elif cited.kind == "experiment":
            store.get_experiment(run_id, ref_id)
        elif cited.kind == "round":
            digits = re.search(r"\d+", ref_id)
            if digits is None:
                return None
            ref_id = str(int(digits.group()))
            store.get_round(run_id, int(ref_id))
        elif ref_id not in call_ids:
            return None
    except (FileNotFoundError, ValueError):
        return None
    return EvidenceRef(run_id=run_id, kind=cited.kind, ref_id=ref_id)


# ------------------------------------------------------------------------------ entry point


def answer_open(
    question: str,
    run_id: str,
    history: list[dict[str, str]],
    *,
    store: EvidenceStore,
    settings: LLMSettings,
    model: Any | None = None,
) -> tuple[QAAnswer, CallOutcome]:
    """Answer one open question about ``run_id``; numbers and citations are checked by code."""
    evidence = gather_evidence(store, run_id)
    context = {
        "question": " ".join(question.split())[:500],
        "history": [
            {"question": turn.get("question", "")[:300], "answer": turn.get("answer", "")[:600]}
            for turn in history[-MAX_HISTORY:]
        ],
        "evidence": _rounded(evidence),
    }
    outcome = QAAgent(settings, model=model).ask(context)
    if outcome.output is None:
        return QAAnswer(answer="", source="llm"), outcome
    draft: QADraft = outcome.output
    call_ids = {str(call.get("action_id")) for call in evidence["llm_calls"]}
    refs: list[EvidenceRef] = []
    for cited in draft.evidence:
        ref = _valid_ref(store, run_id, cited, call_ids)
        if ref is not None and ref not in refs:
            refs.append(ref)
    known = _evidence_numbers(evidence, [])
    numbers = extract_numbers(draft.answer)
    verified = [token for token in numbers if number_in_evidence(token, known)]
    outcome.details["evidence_cited"] = len(draft.evidence)
    outcome.details["evidence_dropped"] = len(draft.evidence) - len(refs)
    answer = QAAnswer(
        answer=draft.answer,
        evidence=refs,
        numbers=numbers,
        verified_numbers=verified,
        source="llm",
    )
    return answer, outcome
