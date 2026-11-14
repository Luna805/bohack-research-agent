"""Proposers (and the on-demand critic) behind one small interface.

* ``PydanticAIProposer`` / ``PydanticAICritic`` - one hosted LLM through PydanticAI with a
  strict output schema. Usage is reported back so the controller can settle the budget.
  This is the only proposer: every BudgetLab experiment proposal comes from the LLM.

Neither can compute metrics, change verdicts or touch the holdout: they only see the
compact context built by ``build_context`` from development-side facts.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .schemas import (
    CriticAdvice,
    ProposalBatch,
    ResourceVector,
    TaskContract,
)
from .state import ResearchState

# PydanticAI prints an observability banner on first use; keep CLI and CI logs clean.
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

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
    extra_body: dict[str, Any] | None = None
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
            extra_body=llm.get("extra_body"),
            input_price_per_mtok=llm.get("input_price_per_mtok"),
            output_price_per_mtok=llm.get("output_price_per_mtok"),
        )


class _PydanticAIRole:
    """One strict-output LLM role.

    Live calls go through our own ``httpx`` client so the controller sees every HTTP request:
    SDK-level retries are switched off (``max_retries=0``), each request is counted by a
    request hook, and token usage is read from the raw provider response. A request whose
    response carries no usage is booked as unknown, never as free. When a PydanticAI test
    ``model`` is injected (unit tests), the framework's usage counters are used instead.
    """

    source = "llm"

    def __init__(
        self,
        settings: LLMSettings,
        output_type: type,
        instructions: str,
        *,
        model: Any | None = None,
    ) -> None:
        if model is None:
            if not settings.model_name:
                raise RuntimeError("LLM model name is not configured (llm.model or LLM_MODEL)")
            if not settings.api_key:
                raise RuntimeError("LLM_API_KEY is not set in the environment or .env")
        self.settings = settings
        self.instructions = instructions
        self.output_type = output_type
        self._test_model = model

    def _agent(self, model: Any) -> Any:
        from pydantic_ai import Agent, NativeOutput, PromptedOutput, ToolOutput

        wrapped = {
            "tool": ToolOutput,
            "native": NativeOutput,
            "prompted": PromptedOutput,
        }[self.settings.output_mode](self.output_type)
        model_settings: dict[str, Any] = {
            "max_tokens": self.settings.max_output_tokens,
            "timeout": self.settings.timeout_seconds,
        }
        if self.settings.temperature is not None:
            model_settings["temperature"] = self.settings.temperature
        if self.settings.extra_body is not None:
            # e.g. {"enable_thinking": false} to switch a reasoning model's thinking off.
            model_settings["extra_body"] = self.settings.extra_body
        return Agent(
            model,
            output_type=wrapped,
            instructions=self.instructions,
            retries=self.settings.output_retries,
            model_settings=model_settings,
        )

    def _prompt_tokens(self, context: dict[str, Any]) -> int:
        return (len(json.dumps(context, ensure_ascii=False)) + len(self.instructions)) // 3

    def estimate(self, context: dict[str, Any]) -> ResourceVector:
        prompt_tokens = self._prompt_tokens(context)
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

    def _limits(self) -> Any:
        from pydantic_ai import UsageLimits

        return UsageLimits(request_limit=self.settings.output_retries + 1)

    async def _run_http(self, prompt: str, trace: dict[str, Any]) -> Any:
        try:  # openai>=3 ships its HTTP layer as ``httpx2``; older releases use ``httpx``
            import httpx2 as httpx
        except ImportError:
            import httpx
        from openai import AsyncOpenAI
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider

        async def on_request(request: Any) -> None:
            trace["requests"] += 1

        async def on_response(response: Any) -> None:
            await response.aread()
            try:
                usage = response.json().get("usage")
            except (ValueError, AttributeError):
                usage = None
            trace["usages"].append(usage if isinstance(usage, dict) else None)

        async with httpx.AsyncClient(
            timeout=self.settings.timeout_seconds,
            event_hooks={"request": [on_request], "response": [on_response]},
        ) as http_client:
            client = AsyncOpenAI(
                api_key=self.settings.api_key,
                base_url=self.settings.base_url,
                max_retries=0,
                timeout=self.settings.timeout_seconds,
                http_client=http_client,
            )
            model = OpenAIChatModel(
                self.settings.model_name, provider=OpenAIProvider(openai_client=client)
            )
            result = await self._agent(model).run(prompt, usage_limits=self._limits())
            return result.output

    def _call(self, context: dict[str, Any]) -> CallOutcome:
        from pydantic_ai.usage import RunUsage

        prompt = json.dumps(context, ensure_ascii=False)
        started = time.monotonic()
        output = None
        error = None
        trace: dict[str, Any] = {"requests": 0, "usages": []}
        framework_usage = RunUsage()
        try:
            if self._test_model is not None:
                result = self._agent(self._test_model).run_sync(
                    prompt, usage=framework_usage, usage_limits=self._limits()
                )
                output = result.output
            else:
                output = asyncio.run(self._run_http(prompt, trace))
        except Exception as exc:  # provider, validation and limit failures all end the call
            error = f"{type(exc).__name__}: {str(exc)[:500]}"
        if self._test_model is not None:
            usage_source = "framework"
            input_tokens = int(framework_usage.input_tokens or 0)
            output_tokens = int(framework_usage.output_tokens or 0)
            requests = int(framework_usage.requests or 0)
            missing = 1 if error is not None and requests == 0 else 0
        else:
            usage_source = "http"
            known = [
                usage
                for usage in trace["usages"]
                if usage and "prompt_tokens" in usage and "completion_tokens" in usage
            ]
            input_tokens = sum(int(usage["prompt_tokens"]) for usage in known)
            output_tokens = sum(int(usage["completion_tokens"]) for usage in known)
            requests = int(trace["requests"])
            missing = requests - len(known)
        actual = ResourceVector(
            llm_tokens=input_tokens + output_tokens,
            llm_requests=requests,
            cost_usd=self._cost(input_tokens, output_tokens),
        )
        unknown = ResourceVector()
        if missing > 0:
            # Requests whose usage never came back are charged at the conservative estimate.
            per_request = self._prompt_tokens(context) + self.settings.max_output_tokens
            unknown = ResourceVector(
                llm_tokens=missing * per_request,
                llm_requests=1 if usage_source == "framework" else 0,
            )
        details = {
            "model": self.settings.model_name,
            "output_mode": self.settings.output_mode,
            "usage_source": usage_source,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "requests": requests,
            "requests_without_usage": max(missing, 0),
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
