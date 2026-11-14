"""Agent building blocks owned by role A (Agent & model)."""

from .protocol_agent import (
    DraftProtocol,
    FieldDecision,
    ProtocolAgent,
    build_protocol_context,
    score_draft,
)

__all__ = [
    "DraftProtocol",
    "FieldDecision",
    "ProtocolAgent",
    "build_protocol_context",
    "score_draft",
]
