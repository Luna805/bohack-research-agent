"""Read-only evidence and quick answers for the research page.

``EvidenceRef`` and ``QAAnswer`` are the shared answer format of INTERFACES 8.4: the zero-token
quick answers (D) and the open-question agent (A) both describe where every claim comes from.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EvidenceKind = Literal["summary", "experiment", "round", "llm_call", "final_evaluation"]


class EvidenceRef(BaseModel):
    run_id: str
    kind: EvidenceKind
    ref_id: str  # experiment id, round number, LLM call action id, or the file name


class QAAnswer(BaseModel):
    answer: str
    evidence: list[EvidenceRef] = Field(default_factory=list)
    numbers: list[str] = Field(default_factory=list)  # numbers that appear in the answer
    verified_numbers: list[str] = Field(default_factory=list)  # filled by the program
    source: Literal["quick", "llm"]
