from __future__ import annotations

import pytest

from budgetlab.schemas import ProposalBatch

pydantic_ai = pytest.importorskip("pydantic_ai")


def test_pydantic_ai_test_model_returns_final_nested_schema(monkeypatch) -> None:
    monkeypatch.setenv("PYDANTIC_AI_NO_BANNER", "1")
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel

    agent = Agent(TestModel(), output_type=ProposalBatch, retries=0)
    result = agent.run_sync("Return a schema-valid proposal batch for an offline fixture.")
    assert isinstance(result.output, ProposalBatch)
    assert len(result.output.candidates) == 2
    assert result.usage.requests == 1
