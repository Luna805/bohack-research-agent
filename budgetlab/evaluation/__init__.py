"""Final, one-shot evaluation on the sealed holdout. Never called by the research loop.

Besides the single holdout score, this module reports how much that score could move by
chance: a percentile bootstrap over holdout rows (``holdout_ci95``) and, for two frozen
deliveries of the same task, a paired bootstrap of their difference on the same rows. Both
are descriptive uncertainty estimates for reporting, not significance tests, and nothing here
feeds back into search.

Row-level predictions are saved next to the run (``holdout_predictions.csv``: row id,
predicted label, positive-class score) **without labels**; labels stay in ``data/sealed/``
and are read only inside this module.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from ..data import ROW_ID, file_sha256, sealed_holdout_path
from ..ledger import EventLedger, atomic_write_json, utc_now
from ..reporting import write_report
from ..schemas import TaskContract

BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = 20261114
PREDICTIONS_FILE = "holdout_predictions.csv"


# ---------------------------------------------------------------------------- metrics


def metric_value(
    metric: str, y_true: np.ndarray, y_pred: np.ndarray, y_score: np.ndarray | None
) -> float:
    """Same definitions as training-time scoring (binary labels 0/1, macro-F1 zero_division=0)."""
    if metric == "roc_auc":
        if y_score is None:
            raise ValueError("roc_auc requires positive-class scores")
        if len(np.unique(y_true)) < 2:
            return float("nan")
        return float(roc_auc_score(y_true, y_score))
    counts = np.bincount(2 * y_true + y_pred, minlength=4)
    return _from_counts(metric, counts)


def _from_counts(metric: str, counts: np.ndarray) -> float:
    tn, fp, fn, tp = (float(value) for value in counts)
    if metric == "accuracy":
        return (tp + tn) / max(tp + tn + fp + fn, 1.0)
    if metric == "f1_macro":
        f1_pos = 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 0.0
        f1_neg = 2 * tn / (2 * tn + fn + fp) if (2 * tn + fn + fp) else 0.0
        return (f1_pos + f1_neg) / 2
    raise ValueError(f"unsupported metric: {metric}")


def _resample_values(
    metric: str,
    y_true: np.ndarray,
    predictions: list[tuple[np.ndarray, np.ndarray | None]],
    resamples: int,
    seed: int,
) -> np.ndarray:
    """Metric of each prediction set on the same bootstrap resamples: shape (resamples, sets)."""
    rng = np.random.default_rng(seed)
    n = len(y_true)
    values = np.empty((resamples, len(predictions)))
    codes = [2 * y_true + y_pred for y_pred, _ in predictions]
    for b in range(resamples):
        idx = rng.integers(0, n, size=n)
        for k, (_, y_score) in enumerate(predictions):
            if metric == "roc_auc":
                values[b, k] = metric_value(metric, y_true[idx], codes[k][idx] % 2, y_score[idx])
            else:
                values[b, k] = _from_counts(metric, np.bincount(codes[k][idx], minlength=4))
    return values


def bootstrap_ci(
    metric: str,
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_score: np.ndarray | None,
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float]:
    values = _resample_values(metric, y_true, [(y_pred, y_score)], resamples, seed)[:, 0]
    values = values[~np.isnan(values)]
    return float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))


# ---------------------------------------------------------------------------- holdout access


def _load_holdout(run_dir: Path) -> tuple[TaskContract, pd.Series, pd.DataFrame]:
    contract = TaskContract.model_validate_json(
        (run_dir / "contract.json").read_text(encoding="utf-8")
    )
    run_config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
    holdout_path = sealed_holdout_path(Path(run_config["data_root"]), contract.task_id)
    if file_sha256(holdout_path) != contract.sealed_holdout_sha256:
        raise ValueError("sealed holdout file does not match the contract")
    frame = pd.read_csv(holdout_path)
    row_ids = frame.pop(ROW_ID).astype(str)
    target = frame.pop(contract.target_column).astype(int)
    target.index = row_ids
    return contract, target, frame[list(contract.approved_feature_columns)]


def _load_predictions(run_dir: Path) -> pd.DataFrame:
    path = run_dir / PREDICTIONS_FILE
    if not path.exists():
        raise FileNotFoundError(f"{run_dir.name} has no {PREDICTIONS_FILE} (evaluated before CIs)")
    return pd.read_csv(path, dtype={"row_id": str}).set_index("row_id")


# ---------------------------------------------------------------------------- public API


def evaluate_frozen_run(run_id: str, runs_root: Path = Path("runs")) -> dict[str, Any]:
    run_dir = runs_root / run_id
    output = run_dir / "final_evaluation.json"
    if output.exists():
        raise RuntimeError(f"{run_id} was already evaluated once; refusing a second look")
    delivery = json.loads((run_dir / "delivery" / "frozen_delivery.json").read_text("utf-8"))
    model_path = run_dir / delivery["model_ref"]
    if hashlib.sha256(model_path.read_bytes()).hexdigest() != delivery["model_hash"]:
        raise ValueError("delivered model changed after freezing")
    contract, target, features = _load_holdout(run_dir)
    pipeline = joblib.load(model_path)
    y_true = target.to_numpy()
    y_pred = np.asarray(pipeline.predict(features)).astype(int)
    y_score = (
        np.asarray(pipeline.predict_proba(features))[:, 1]
        if hasattr(pipeline, "predict_proba")
        else None
    )
    metric = contract.primary_metric
    score = metric_value(metric, y_true, y_pred, y_score)
    low, high = bootstrap_ci(metric, y_true, y_pred, y_score)
    predictions = pd.DataFrame(
        {
            "row_id": target.index,
            "y_pred": y_pred,
            "y_score": y_score if y_score is not None else np.nan,
        }
    )
    predictions.to_csv(run_dir / PREDICTIONS_FILE, index=False, float_format="%.6g")
    result = {
        "run_id": run_id,
        "metric": metric,
        "holdout_score": score,
        "holdout_ci95": [low, high],
        "bootstrap": {
            "method": "percentile bootstrap over holdout rows",
            "resamples": BOOTSTRAP_RESAMPLES,
            "seed": BOOTSTRAP_SEED,
        },
        "holdout_rows": len(target),
        "development_cv_score": delivery["development_cv_score"],
        "dev_minus_holdout": None
        if delivery["development_cv_score"] is None
        else delivery["development_cv_score"] - score,
        "delivered_experiment_id": delivery["delivered_experiment_id"],
        "model_hash": delivery["model_hash"],
        "predictions_ref": PREDICTIONS_FILE,
        "predictions_sha256": file_sha256(run_dir / PREDICTIONS_FILE),
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


def paired_bootstrap(
    run_dir: Path,
    reference_dir: Path,
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Holdout metric of ``run_dir`` minus ``reference_dir`` on identical bootstrap resamples.

    Both runs must be frozen, evaluated deliveries of the same task and sealed holdout.
    """
    contract, target, _ = _load_holdout(run_dir)
    reference_contract, _, _ = _load_holdout(reference_dir)
    if (contract.task_id, contract.sealed_holdout_sha256) != (
        reference_contract.task_id,
        reference_contract.sealed_holdout_sha256,
    ):
        raise ValueError("paired bootstrap needs two runs of the same task and holdout")
    mine, theirs = _load_predictions(run_dir), _load_predictions(reference_dir)
    if set(mine.index) != set(target.index) or set(theirs.index) != set(target.index):
        raise ValueError("prediction files do not cover the sealed holdout rows")
    mine, theirs = mine.loc[target.index], theirs.loc[target.index]
    metric = contract.primary_metric
    y_true = target.to_numpy()

    def unpack(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray | None]:
        scores = frame["y_score"].to_numpy(dtype=float)
        return frame["y_pred"].to_numpy(dtype=int), None if np.isnan(scores).all() else scores

    sets = [unpack(mine), unpack(theirs)]
    point = metric_value(metric, y_true, *sets[0]) - metric_value(metric, y_true, *sets[1])
    values = _resample_values(metric, y_true, sets, resamples, seed)
    deltas = values[:, 0] - values[:, 1]
    deltas = deltas[~np.isnan(deltas)]
    return {
        "metric": metric,
        "delta": point,
        "ci95": [float(np.percentile(deltas, 2.5)), float(np.percentile(deltas, 97.5))],
        "share_positive": float(np.mean(deltas > 0)),
        "identical_predictions": bool(np.array_equal(sets[0][0], sets[1][0])),
        "resamples": resamples,
        "seed": seed,
        "rows": len(y_true),
    }
