"""Proposers (and the on-demand critic) behind one small interface.

* ``ScriptedProposer`` - deterministic, zero-token rules that react to program results.
  It exists to test the controller offline and is always labelled ``scripted``.
* ``PydanticAIProposer`` / ``PydanticAICritic`` - one hosted LLM through PydanticAI with a
  strict output schema. Usage is reported back so the controller can settle the budget.

Neither kind can compute metrics, change verdicts or touch the holdout: they only see the
compact context built by ``build_context`` from development-side facts.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .contracts import spec_hash
from .schemas import (
    AddMissingIndicators,
    Candidate,
    CriticAdvice,
    ExperimentSpec,
    ForestSpec,
    HistBoostSpec,
    Hypothesis,
    LogisticSpec,
    PreprocessingSpec,
    ProposalBatch,
    ResourceVector,
    SentinelToMissing,
    TaskContract,
)
from .state import ResearchState

# ------------------------------------------------------------------------------ context


def build_context(
    *,
    card: dict[str, Any],
    profile: dict[str, Any],
    contract: TaskContract,
    state: ResearchState,
    remaining: dict[str, Any],
    mode: str,
    max_rows: int = 10,
) -> dict[str, Any]:
    approved = set(contract.approved_feature_columns)
    profile_rows = []
    excluded = []
    for entry in profile["columns"]:
        if entry["name"] in approved:
            row = {key: value for key, value in entry.items() if key != "availability"}
            profile_rows.append(row)
        else:
            note = next(
                (f.get("note", "") for f in card.get("fields", []) if f["name"] == entry["name"]),
                "",
            )
            excluded.append(
                {"name": entry["name"], "availability": entry["availability"], "note": note.strip()}
            )
    rows = [record.summary() for record in state.experiments]
    keep = {state.baseline.experiment_id, state.best_id}
    if len(rows) > max_rows:
        tail = rows[-(max_rows - 2) :]
        head = [row for row in rows[: -(max_rows - 2)] if row["id"] in keep]
        rows = head + tail
    policy = contract.loop_policy
    return {
        "mode": mode,
        "task": {
            "title": card.get("title"),
            "business_question": " ".join(str(card.get("business_question", "")).split()),
            "prediction_time": card.get("prediction_time"),
            "decision_use": card.get("decision_use"),
            "primary_metric": contract.primary_metric,
            "development_rows": profile["rows"],
            "positive_rate": profile["positive_rate"],
        },
        "legal_space": {
            "model_families": list(contract.allowed_model_families),
            "feature_actions": [
                "drop_columns(columns)",
                "log1p(columns): numeric columns with all values > -1",
                "missing_indicator(columns): adds <column>__missing flags",
                "sentinel_to_missing(columns, value): numeric placeholder -> missing; "
                "follow with missing_indicator to keep the flag",
            ],
            "max_feature_actions": 4,
            "text_columns": list(contract.text_columns),
            "note": "Preprocessing is fitted inside each training fold by the program.",
        },
        "data_profile": profile_rows,
        "excluded_columns": excluded,
        "decision_rule": {
            "comparison": "paired same-fold mean delta of the primary metric (5-fold CV)",
            "min_effect": round(contract.decision_policy.min_effect, 5),
            "final_check": "the best passing candidate is re-run against the baseline on "
            "three unseen split seeds before it can be delivered",
        },
        "baseline_id": state.baseline.experiment_id,
        "best_id": state.best_id,
        "experiments": rows,
        "valid_evidence_refs": state.known_ids() + ["eda", "calibration", "scenario_card"],
        "controller_feedback": list(state.feedback),
        "critic_advice": state.critic_advice,
        "progress": {
            "rounds_used": len(state.rounds),
            "max_rounds": policy.max_rounds,
            "rounds_without_improvement": state.stagnation,
        },
        "budget_remaining": {
            key: remaining.get(key) for key in ("experiments", "llm_requests", "llm_tokens")
        },
    }


PROPOSER_INSTRUCTIONS = """\
You are the Proposer inside BudgetLab, a budget-aware machine-learning research loop.
Each call you return exactly one ProposalBatch with two candidates. Program code, not you,
trains the models, computes every metric, judges each hypothesis and chooses the delivery.

Rules:
1. Each candidate is one falsifiable hypothesis about ONE research factor (model family,
   class weighting, one hyper-parameter group, or one feature-action group), tested against
   a named comparator experiment. Prefer changing one factor relative to the current best.
2. comparator_experiment_id must be an id listed in `experiments`; evidence_refs must come
   from `valid_evidence_refs`.
3. The two candidates must test different factors or opposite directions, not two tiny
   variations of the same change.
4. Never resubmit a specification that already appears in `experiments`; duplicates are
   rejected without running. Read `controller_feedback` for last round's rejections.
5. Use only columns from `data_profile`. Columns in `excluded_columns` are not available at
   prediction time and will be rejected.
6. A paired delta below decision_rule.min_effect counts as "not met". Look at fold_std before
   chasing very small gains.
7. When mode is "replan", progress has stalled: set intent to "replan" or "pivot" and choose a
   direction different from what has already been tried.
8. predicted_metric_delta is your honest estimate of the paired delta versus the comparator.
   It is only logged; it never influences selection.
Keep every text field to one or two short sentences.
"""

CRITIC_INSTRUCTIONS = """\
You are the Critic inside BudgetLab. Progress has stalled. Read the experiment table and the
data profile, explain in two or three sentences why recent hypotheses did not beat the best
result, and name one concrete next focus that has not been tried. You cannot change metrics,
verdicts or budgets; your advice is shown to the Proposer next round. Cite experiment ids
from `valid_evidence_refs`.
"""


# ------------------------------------------------------------------------------ interface


@dataclass
class CallOutcome:
    output: Any | None
    usage: ResourceVector = field(default_factory=ResourceVector)
    unknown: ResourceVector = field(default_factory=ResourceVector)
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class Proposer(Protocol):
    source: str

    def estimate(self, context: dict[str, Any]) -> ResourceVector: ...

    def propose(self, context: dict[str, Any]) -> CallOutcome: ...


class Critic(Protocol):
    source: str

    def estimate(self, context: dict[str, Any]) -> ResourceVector: ...

    def review(self, context: dict[str, Any]) -> CallOutcome: ...


# ------------------------------------------------------------------------------ scripted


class ScriptedProposer:
    """Deterministic zero-token rules: weight classes, switch family, fix sentinels, tune."""

    source = "scripted"

    def estimate(self, context: dict[str, Any]) -> ResourceVector:
        return ResourceVector()

    def _moves(self, best: ExperimentSpec, context: dict[str, Any]) -> list[tuple[str, Any]]:
        moves: list[tuple[str, ExperimentSpec]] = []
        model = best.model
        if getattr(model, "class_weight", None) is None:
            moves.append(
                (
                    "Balanced class weights should raise minority-class F1 on an imbalanced task.",
                    best.model_copy(
                        update={"model": model.model_copy(update={"class_weight": "balanced"})}
                    ),
                )
            )
        families = context["legal_space"]["model_families"]
        for family in families:
            if family == model.family:
                continue
            new_model: Any
            if family == "logistic_regression":
                new_model = LogisticSpec(family=family, class_weight="balanced", max_iter=500)
                prep = PreprocessingSpec(numeric_scaler="standard")
            elif family == "random_forest":
                new_model = ForestSpec(family=family, class_weight="balanced", min_samples_leaf=5)
                prep = PreprocessingSpec()
            else:
                new_model = HistBoostSpec(family=family, class_weight="balanced")
                prep = PreprocessingSpec()
            moves.append(
                (
                    f"A {family} model may capture structure the current best misses.",
                    ExperimentSpec(
                        model=new_model, preprocessing=prep, feature_actions=best.feature_actions
                    ),
                )
            )
        for column in context["data_profile"]:
            if "possible_sentinel" in column and not best.feature_actions:
                actions = (
                    SentinelToMissing(
                        kind="sentinel_to_missing",
                        columns=(column["name"],),
                        value=column["possible_sentinel"],
                    ),
                    AddMissingIndicators(kind="missing_indicator", columns=(column["name"],)),
                )
                moves.append(
                    (
                        f"{column['name']} uses {column['possible_sentinel']} as a placeholder; "
                        "an explicit flag may help.",
                        best.model_copy(update={"feature_actions": actions}),
                    )
                )
        tweaks: dict[str, list[dict[str, Any]]] = {
            "random_forest": [
                {"min_samples_leaf": 10},
                {"min_samples_leaf": 2},
                {"n_estimators": 200},
            ],
            "hist_gradient_boosting": [
                {"learning_rate": 0.05, "max_iter": 200},
                {"min_samples_leaf": 50},
            ],
            "logistic_regression": [{"c": 0.2}, {"c": 5.0}],
        }
        for update in tweaks[model.family]:
            moves.append(
                (
                    f"Tuning {', '.join(update)} may trade bias and variance better.",
                    best.model_copy(update={"model": model.model_copy(update=update)}),
                )
            )
        return moves

    def propose(self, context: dict[str, Any]) -> CallOutcome:
        rows = {row["id"]: row for row in context["experiments"]}
        best_id = context["best_id"]
        best = ExperimentSpec.model_validate(rows[best_id]["spec"])
        seen = {spec_hash(ExperimentSpec.model_validate(row["spec"])) for row in rows.values()}
        chosen: list[tuple[str, ExperimentSpec]] = []
        for statement, spec in self._moves(best, context):
            digest = spec_hash(spec)
            if digest in seen:
                continue
            seen.add(digest)
            chosen.append((statement, spec))
            if len(chosen) == 2:
                break
        if len(chosen) < 2:
            return CallOutcome(output=None, error="scripted proposer has no untried moves left")
        candidates = tuple(
            Candidate(
                candidate_id=f"s{index + 1}",
                hypothesis=Hypothesis(
                    statement=statement,
                    evidence_refs=(best_id, "eda"),
                    comparator_experiment_id=best_id,
                    decision_policy_id="practical_gain_v2",
                    proposed_change=json.dumps(spec.model.model_dump(mode="json"))[:200],
                ),
                experiment=spec,
            )
            for index, (statement, spec) in enumerate(chosen)
        )
        batch = ProposalBatch(
            previous_result_interpretation=f"Current best is {best_id}.",
            intent="replan" if context["mode"] == "replan" else "refine",
            direction=f"improve on {best_id}",
            candidates=candidates,
        )
        return CallOutcome(output=batch, details={"source": "scripted"})


# ------------------------------------------------------------------------------ live LLM


def load_dotenv(path: Path) -> None:
    """Minimal .env reader (KEY=VALUE lines); existing environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class LLMSettings:
    model_name: str
    base_url: str | None
    api_key: str | None
    output_mode: str = "tool"
    max_output_tokens: int = 3000
    temperature: float | None = None
    timeout_seconds: float = 120.0
    output_retries: int = 1
    input_price_per_mtok: float | None = None
    output_price_per_mtok: float | None = None

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> LLMSettings:
        llm = config.get("llm", {})
        return cls(
            model_name=llm.get("model") or os.environ.get("LLM_MODEL", ""),
            base_url=llm.get("base_url") or os.environ.get("LLM_BASE_URL") or None,
            api_key=os.environ.get("LLM_API_KEY") or None,
            output_mode=llm.get("output_mode", "tool"),
            max_output_tokens=int(llm.get("max_output_tokens", 3000)),
            temperature=llm.get("temperature"),
            timeout_seconds=float(llm.get("timeout_seconds", 120)),
            output_retries=int(llm.get("output_retries", 1)),
            input_price_per_mtok=llm.get("input_price_per_mtok"),
            output_price_per_mtok=llm.get("output_price_per_mtok"),
        )


class _PydanticAIRole:
    """Shared plumbing: one Agent, strict output type, usage captured even on failure."""

    source = "llm"

    def __init__(
        self,
        settings: LLMSettings,
        output_type: type,
        instructions: str,
        *,
        model: Any | None = None,
    ) -> None:
        from pydantic_ai import Agent, NativeOutput, PromptedOutput, ToolOutput

        if model is None:
            if not settings.model_name:
                raise RuntimeError("LLM model name is not configured (llm.model or LLM_MODEL)")
            from pydantic_ai.models.openai import OpenAIChatModel
            from pydantic_ai.providers.openai import OpenAIProvider

            model = OpenAIChatModel(
                settings.model_name,
                provider=OpenAIProvider(base_url=settings.base_url, api_key=settings.api_key),
            )
        wrapped = {
            "tool": ToolOutput,
            "native": NativeOutput,
            "prompted": PromptedOutput,
        }[settings.output_mode](output_type)
        model_settings: dict[str, Any] = {
            "max_tokens": settings.max_output_tokens,
            "timeout": settings.timeout_seconds,
        }
        if settings.temperature is not None:
            model_settings["temperature"] = settings.temperature
        self.settings = settings
        self.instructions = instructions
        self.agent = Agent(
            model,
            output_type=wrapped,
            instructions=instructions,
            retries=settings.output_retries,
            model_settings=model_settings,
        )

    def estimate(self, context: dict[str, Any]) -> ResourceVector:
        prompt_tokens = (len(json.dumps(context, ensure_ascii=False)) + len(self.instructions)) // 3
        attempts = self.settings.output_retries + 1
        return ResourceVector(
            llm_tokens=(prompt_tokens + self.settings.max_output_tokens) * attempts,
            llm_requests=attempts,
            cost_usd=self._cost(
                prompt_tokens * attempts, self.settings.max_output_tokens * attempts
            ),
        )

    def _cost(self, input_tokens: int, output_tokens: int) -> float:
        if (
            self.settings.input_price_per_mtok is None
            or self.settings.output_price_per_mtok is None
        ):
            return 0.0
        return (
            input_tokens * self.settings.input_price_per_mtok
            + output_tokens * self.settings.output_price_per_mtok
        ) / 1_000_000

    def _call(self, context: dict[str, Any]) -> CallOutcome:
        from pydantic_ai import UsageLimits
        from pydantic_ai.usage import RunUsage

        usage = RunUsage()
        started = time.monotonic()
        output = None
        error = None
        try:
            result = self.agent.run_sync(
                json.dumps(context, ensure_ascii=False),
                usage=usage,
                usage_limits=UsageLimits(request_limit=self.settings.output_retries + 1),
            )
            output = result.output
        except Exception as exc:  # provider, validation and limit failures all end the call
            error = f"{type(exc).__name__}: {str(exc)[:500]}"
        tokens = int(usage.input_tokens or 0) + int(usage.output_tokens or 0)
        actual = ResourceVector(
            llm_tokens=tokens,
            llm_requests=int(usage.requests or 0),
            cost_usd=self._cost(int(usage.input_tokens or 0), int(usage.output_tokens or 0)),
        )
        unknown = ResourceVector()
        if error is not None and usage.requests == 0:
            # A request may have been sent without usage coming back: never book it as free.
            unknown = ResourceVector(llm_requests=1, llm_tokens=self.settings.max_output_tokens)
        details = {
            "model": self.settings.model_name,
            "output_mode": self.settings.output_mode,
            "input_tokens": int(usage.input_tokens or 0),
            "output_tokens": int(usage.output_tokens or 0),
            "requests": int(usage.requests or 0),
            "seconds": round(time.monotonic() - started, 2),
            "priced": self.settings.input_price_per_mtok is not None,
        }
        return CallOutcome(
            output=output, usage=actual, unknown=unknown, details=details, error=error
        )


class PydanticAIProposer(_PydanticAIRole):
    def __init__(self, settings: LLMSettings, *, model: Any | None = None) -> None:
        super().__init__(settings, ProposalBatch, PROPOSER_INSTRUCTIONS, model=model)

    def propose(self, context: dict[str, Any]) -> CallOutcome:
        return self._call(context)


class PydanticAICritic(_PydanticAIRole):
    def __init__(self, settings: LLMSettings, *, model: Any | None = None) -> None:
        super().__init__(settings, CriticAdvice, CRITIC_INSTRUCTIONS, model=model)

    def review(self, context: dict[str, Any]) -> CallOutcome:
        return self._call(context)
