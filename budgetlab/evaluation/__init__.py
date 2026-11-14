"""Final, one-shot evaluation on the sealed holdout. Never called by the research loop."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

from ..data import ROW_ID, file_sha256, sealed_holdout_path
from ..ledger import EventLedger, atomic_write_json, utc_now
from ..pipeline import score_predictions
from ..reporting import write_report
from ..schemas import TaskContract


def evaluate_frozen_run(run_id: str, runs_root: Path = Path("runs")) -> dict[str, Any]:
    run_dir = runs_root / run_id
    output = run_dir / "final_evaluation.json"
    if output.exists():
        raise RuntimeError(f"{run_id} was already evaluated once; refusing a second look")
    contract = TaskContract.model_validate_json(
        (run_dir / "contract.json").read_text(encoding="utf-8")
    )
    delivery = json.loads((run_dir / "delivery" / "frozen_delivery.json").read_text("utf-8"))
    run_config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
    model_path = run_dir / delivery["model_ref"]
    if hashlib.sha256(model_path.read_bytes()).hexdigest() != delivery["model_hash"]:
        raise ValueError("delivered model changed after freezing")
    holdout_path = sealed_holdout_path(Path(run_config["data_root"]), contract.task_id)
    if file_sha256(holdout_path) != contract.sealed_holdout_sha256:
        raise ValueError("sealed holdout file does not match the contract")
    frame = pd.read_csv(holdout_path)
    frame.pop(ROW_ID)
    target = frame.pop(contract.target_column).astype(int)
    features = frame[list(contract.approved_feature_columns)]
    pipeline = joblib.load(model_path)
    score = score_predictions(contract.primary_metric, target, pipeline, features)
    result = {
        "run_id": run_id,
        "metric": contract.primary_metric,
        "holdout_score": score,
        "holdout_rows": len(target),
        "development_cv_score": delivery["development_cv_score"],
        "dev_minus_holdout": None
        if delivery["development_cv_score"] is None
        else delivery["development_cv_score"] - score,
        "delivered_experiment_id": delivery["delivered_experiment_id"],
        "model_hash": delivery["model_hash"],
        "evaluated_at": utc_now(),
    }
    atomic_write_json(output, result)
    EventLedger(run_id, run_dir).append(
        "final_evaluation_recorded", artifact_ref="final_evaluation.json"
    )
    summary_path = run_dir / "summary.json"
    if summary_path.exists():
        write_report(run_dir, json.loads(summary_path.read_text(encoding="utf-8")))
    return result
