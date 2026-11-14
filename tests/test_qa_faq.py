"""Evidence access and zero-token answer checks."""

import json

import pytest

from budgetlab.qa.evidence import EvidenceStore
from budgetlab.qa.faq import answer_quick


def test_quick_answer_uses_saved_summary(tmp_path):
    runs = tmp_path / "runs"
    run = runs / "demo"
    run.mkdir(parents=True)
    (run / "summary.json").write_text(
        json.dumps(
            {
                "baseline_score": 0.6,
                "delivered_dev_score": 0.7,
                "confirmation_status": "confirmed_pass",
                "delivered_experiment_id": "exp-1",
                "wall_seconds": 12,
                "llm": {"requests": 0, "tokens": 0},
            }
        ),
        encoding="utf-8",
    )
    store = EvidenceStore(runs, tmp_path / "results")
    answer = answer_quick("score", "demo", store)
    assert "0.6" in answer["answer"] and "0.7" in answer["answer"]
    assert answer["evidence"][0]["ref_id"] == "summary.json"


def test_evidence_rejects_path_traversal(tmp_path):
    store = EvidenceStore(tmp_path / "runs", tmp_path / "results")
    with pytest.raises(ValueError, match="Invalid run ID"):
        store.get_summary("../other")
    with pytest.raises(ValueError, match="Invalid experiment ID"):
        store.get_experiment("safe", "../other")
