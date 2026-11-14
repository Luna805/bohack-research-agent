from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import joblib
import numpy as np
from sklearn.model_selection import StratifiedKFold

from .contracts import stable_hash
from .data import load_development
from .ledger import atomic_write_json
from .pipeline import build_pipeline, score_predictions
from .schemas import ExperimentSpec, TaskContract


def execute(payload: dict[str, object]) -> dict[str, object]:
    started = time.monotonic()
    fit_attempts = 0
    fit_completed = 0
    fold_hash = None
    dataset_hash = None
    metric = None
    if payload.get("simulate_sleep_seconds"):
        time.sleep(float(payload["simulate_sleep_seconds"]))
    try:
        spec = ExperimentSpec.model_validate(payload["spec"])
        contract = TaskContract.model_validate(payload["contract"])
        bundle = load_development(contract.dataset_ref, Path(str(payload["data_root"])))
        if bundle.dataset_hash != contract.dataset_hash:
            raise ValueError("development data hash does not match the frozen contract")
        features = bundle.features[list(contract.approved_feature_columns)]
        dataset_hash = bundle.dataset_hash
        metric = contract.primary_metric
        purpose = str(payload["purpose"])
        if purpose == "final_refit":
            fit_attempts = 1
            pipeline = build_pipeline(spec, features, contract.search_training_seed)
            pipeline.fit(features, bundle.target)
            fit_completed = 1
            model_path = Path(str(payload["model_path"]))
            model_path.parent.mkdir(parents=True, exist_ok=True)
            joblib.dump(pipeline, model_path)
            fold_scores: list[float] = []
        else:
            seed = int(payload["split_seed"])
            splitter = StratifiedKFold(n_splits=contract.cv_folds, shuffle=True, random_state=seed)
            fold_scores = []
            splits = list(splitter.split(features, bundle.target))
            # Fingerprint of which rows validate in each fold; paired comparisons require equality.
            fold_hash = stable_hash([[bundle.row_ids[i] for i in valid] for _, valid in splits])
            for fold_index, (train, valid) in enumerate(splits):
                pipeline = build_pipeline(
                    spec, features.iloc[train], contract.search_training_seed + fold_index
                )
                fit_attempts += 1
                pipeline.fit(features.iloc[train], bundle.target.iloc[train])
                fit_completed += 1
                fold_scores.append(
                    score_predictions(
                        contract.primary_metric,
                        bundle.target.iloc[valid],
                        pipeline,
                        features.iloc[valid],
                    )
                )
        return {
            "status": "ok",
            "fold_scores": fold_scores,
            "mean_score": float(np.mean(fold_scores)) if fold_scores else None,
            "fit_attempts": fit_attempts,
            "fit_completed": fit_completed,
            "fold_hash": fold_hash,
            "dataset_hash": dataset_hash,
            "metric": metric,
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
