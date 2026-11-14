from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .budget import Budget
from .ledger import EventLedger, atomic_write_json
from .schemas import ExecutionResult, ExperimentSpec, ResourceVector, TaskContract

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Runner:
    def __init__(self, run_dir: Path, ledger: EventLedger, budget: Budget, data_root: Path) -> None:
        self.run_dir = run_dir.resolve()
        self.data_root = data_root.resolve()
        self.ledger = ledger
        self.budget = budget
        (run_dir / "work").mkdir(parents=True, exist_ok=True)
        (run_dir / "experiments").mkdir(parents=True, exist_ok=True)
        (run_dir / "logs").mkdir(parents=True, exist_ok=True)

    def execute(
        self,
        spec: ExperimentSpec,
        contract: TaskContract,
        *,
        purpose: str,
        split_seed: int | None = None,
        experiment_id: str | None = None,
        simulate_sleep_seconds: float = 0,
    ) -> ExecutionResult:
        experiment_id = experiment_id or f"exp-{uuid.uuid4().hex[:12]}"
        action_id = f"train:{experiment_id}"
        planned_fits = 1 if purpose == "final_refit" else contract.cv_folds
        timeout = contract.budgets.experiment_timeout_seconds
        self.budget.reserve(
            action_id, ResourceVector(experiments=1, fits=planned_fits, seconds=timeout)
        )
        artifact_rel = f"experiments/{experiment_id}.json"
        job_path = self.run_dir / "work" / f"{experiment_id}.job.json"
        result_path = self.run_dir / "work" / f"{experiment_id}.result.json"
        model_path = self.run_dir / "delivery" / "model.joblib"
        payload = {
            "dataset_ref": contract.dataset_ref,
            "data_root": str(self.data_root),
            "spec": spec.model_dump(mode="json"),
            "contract": contract.model_dump(mode="json"),
            "purpose": purpose,
            "split_seed": split_seed,
            "model_path": str(model_path),
            "simulate_sleep_seconds": simulate_sleep_seconds,
        }
        started = time.monotonic()
        status = "failed"
        raw: dict[str, object] = {}
        unknown = ResourceVector()

        def write_logs(stdout: object, stderr: object) -> None:
            def text(value: object) -> str:
                if value is None:
                    return ""
                if isinstance(value, bytes):
                    return value.decode("utf-8", errors="replace")
                return str(value)

            try:
                (self.run_dir / "logs" / f"{experiment_id}.stdout.log").write_text(
                    text(stdout), encoding="utf-8"
                )
                (self.run_dir / "logs" / f"{experiment_id}.stderr.log").write_text(
                    text(stderr), encoding="utf-8"
                )
            except OSError:
                # Accounting must still close even when the filesystem cannot retain logs.
                pass

        try:
            atomic_write_json(job_path, payload)
            self.ledger.append(
                "experiment_started",
                action_id=action_id,
                artifact_ref=artifact_rel,
                details={"purpose": purpose},
            )
            env = os.environ.copy()
            env.update(
                {
                    "OMP_NUM_THREADS": "1",
                    "MKL_NUM_THREADS": "1",
                    "OPENBLAS_NUM_THREADS": "1",
                    "NUMEXPR_NUM_THREADS": "1",
                }
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "budgetlab.worker",
                    "--job",
                    str(job_path),
                    "--result",
                    str(result_path),
                ],
                cwd=PROJECT_ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            write_logs(completed.stdout, completed.stderr)
            if result_path.exists():
                try:
                    decoded = json.loads(result_path.read_text(encoding="utf-8"))
                    if not isinstance(decoded, dict):
                        raise ValueError("worker result must be a JSON object")
                    raw = decoded
                    status = str(raw.get("status", "failed"))
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    raw = {"error": f"invalid worker result: {type(exc).__name__}: {exc}"}
                    unknown = ResourceVector(fits=planned_fits)
            else:
                raw = {"error": f"worker exited {completed.returncode} without a result"}
                unknown = ResourceVector(fits=planned_fits)
        except subprocess.TimeoutExpired as exc:
            status = "timeout"
            raw = {"error": f"worker timeout after {timeout}s: {exc}"}
            unknown = ResourceVector(fits=planned_fits)
            write_logs(exc.stdout, exc.stderr)
        except OSError as exc:
            raw = {"error": f"failed to start worker: {type(exc).__name__}: {exc}"}
            unknown = ResourceVector(fits=planned_fits)
            write_logs("", raw["error"])
        except Exception:
            self.budget.mark_interrupted_unknown(action_id)
            raise
        duration = time.monotonic() - started

        def fit_count(name: str) -> int:
            value = raw[name]
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
            return value

        if unknown.fits:
            fit_attempts = 0
            fit_completed = 0
        else:
            try:
                worker_status = raw["status"]
                if worker_status not in {"ok", "failed", "timeout", "invalid"}:
                    raise ValueError(f"unsupported status: {worker_status!r}")
                status = str(worker_status)
                fit_attempts = fit_count("fit_attempts")
                fit_completed = fit_count("fit_completed")
                if not 0 <= fit_completed <= fit_attempts <= planned_fits:
                    raise ValueError("fit counters are outside the planned range")
            except (KeyError, TypeError, ValueError) as exc:
                status = "failed"
                raw = {"error": f"invalid worker result: {type(exc).__name__}: {exc}"}
                unknown = ResourceVector(fits=planned_fits)
                fit_attempts = 0
                fit_completed = 0
        self.budget.settle(
            action_id,
            ResourceVector(experiments=1, fits=fit_attempts, seconds=duration),
            unknown=unknown,
        )
        try:
            scores_value = raw.get("fold_scores", [])
            if not isinstance(scores_value, (list, tuple)):
                raise ValueError("fold_scores must be an array")
            fold_scores = tuple(float(value) for value in scores_value)
            mean_value = raw.get("mean_score")
            mean_score = None if mean_value is None else float(mean_value)
            error_value = raw.get("error")
            if error_value is not None and not isinstance(error_value, str):
                raise ValueError("error must be a string or null")
            error = error_value
        except (TypeError, ValueError, OverflowError) as exc:
            status, fold_scores, mean_score = "failed", (), None
            error = f"invalid worker result: {type(exc).__name__}: {exc}"
        if not all(math.isfinite(value) for value in fold_scores) or (
            mean_score is not None and not math.isfinite(mean_score)
        ):
            status, fold_scores, mean_score = "invalid", (), None
            error = "worker returned a non-finite score"
        result = ExecutionResult(
            experiment_id=experiment_id,
            purpose=purpose,
            status=status,
            split_seed=split_seed,
            fold_scores=fold_scores,
            mean_score=mean_score,
            fit_attempts=fit_attempts,
            fit_completed=fit_completed,
            fold_hash=raw.get("fold_hash"),
            dataset_hash=raw.get("dataset_hash"),
            metric=raw.get("metric"),
            duration_seconds=duration,
            artifact_ref=artifact_rel,
            error=error,
        )
        atomic_write_json(
            self.run_dir / artifact_rel,
            {"spec": spec.model_dump(mode="json"), "result": result.model_dump(mode="json")},
        )
        self.ledger.append(
            "experiment_completed" if status == "ok" else "experiment_failed",
            action_id=action_id,
            artifact_ref=artifact_rel,
            reason_code=None if status == "ok" else status,
            details={"fit_attempts": fit_attempts, "fit_completed": fit_completed},
        )
        return result
