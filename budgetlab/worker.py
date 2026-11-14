from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import joblib
import numpy as np
from sklearn.model_selection import StratifiedKFold

from .data import load_dataset
from .ledger import atomic_write_json
from .pipeline import build_pipeline, score_predictions
from .schemas import ExperimentSpec, TaskContract


def execute(payload: dict[str, object]) -> dict[str, object]:
    started = time.monotonic()
    fit_attempts = 0
    fit_completed = 0
    if payload.get("simulate_sleep_seconds"):
        time.sleep(float(payload["simulate_sleep_seconds"]))
    try:
        bundle = load_dataset(str(payload["dataset_ref"]))
        spec = ExperimentSpec.model_validate(payload["spec"])
        contract = TaskContract.model_validate(payload["contract"])
        purpose = str(payload["purpose"])
        if purpose == "final_refit":
            fit_attempts = 1
            pipeline = build_pipeline(spec, bundle.features, contract.search_training_seed)
            pipeline.fit(bundle.features, bundle.target)
            fit_completed = 1
            model_path = Path(str(payload["model_path"]))
            model_path.parent.mkdir(parents=True, exist_ok=True)
            joblib.dump(pipeline, model_path)
            fold_scores: list[float] = []
        else:
            seed = int(payload["split_seed"])
            splitter = StratifiedKFold(n_splits=contract.cv_folds, shuffle=True, random_state=seed)
            fold_scores = []
            for fold_index, (train, valid) in enumerate(
                splitter.split(bundle.features, bundle.target)
            ):
                pipeline = build_pipeline(
                    spec, bundle.features.iloc[train], contract.search_training_seed + fold_index
                )
                fit_attempts += 1
                pipeline.fit(bundle.features.iloc[train], bundle.target.iloc[train])
                fit_completed += 1
                fold_scores.append(
                    score_predictions(
                        contract.primary_metric,
                        bundle.target.iloc[valid],
                        pipeline,
                        bundle.features.iloc[valid],
                    )
                )
        return {
            "status": "ok",
            "fold_scores": fold_scores,
            "mean_score": float(np.mean(fold_scores)) if fold_scores else None,
            "fit_attempts": fit_attempts,
            "fit_completed": fit_completed,
            "duration_seconds": time.monotonic() - started,
            "error": None,
        }
    except Exception as exc:  # worker boundary preserves the concrete failure
        return {
            "status": "failed",
            "fold_scores": [],
            "mean_score": None,
            "fit_attempts": fit_attempts,
            "fit_completed": fit_completed,
            "duration_seconds": time.monotonic() - started,
            "error": f"{type(exc).__name__}: {exc}",
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.job.read_text(encoding="utf-8"))
    result = execute(payload)
    atomic_write_json(args.result, result)
    return 0 if result["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
