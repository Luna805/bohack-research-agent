from __future__ import annotations

import json
from typing import Any

from .schemas import ProposalBatch


class LiveGatewayBlocked(RuntimeError):
    pass


class FixtureGateway:
    """Zero-credential parser used only for schema and repair-path tests."""

    @staticmethod
    def parse(payload: str | dict[str, Any]) -> ProposalBatch:
        value = json.loads(payload) if isinstance(payload, str) else payload
        return ProposalBatch.model_validate(value)


class PydanticAIGateway:
    """Optional live boundary blocked without explicit spending authorization."""

    def __init__(self, model: str, *, allow_live: bool, request_budget: int) -> None:
        if not allow_live or request_budget <= 0:
            raise LiveGatewayBlocked(
                "live model calls require explicit authorization and a positive request budget"
            )
        try:
            from pydantic_ai import Agent
        except ImportError as exc:
            raise RuntimeError("install the optional 'llm' dependency for live calls") from exc
        self.agent = Agent(model, output_type=ProposalBatch)
        self.remaining_requests = request_budget

    async def call(self, prompt: str) -> ProposalBatch:
        if self.remaining_requests <= 0:
            raise LiveGatewayBlocked("live request budget exhausted")
        self.remaining_requests -= 1
        result = await self.agent.run(prompt)
        return ProposalBatch.model_validate(result.output)
