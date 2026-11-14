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
        started = time.monotonic()
        status = "failed"
        raw: dict[str, object] = {}
        unknown = ResourceVector()
        try:
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
            (self.run_dir / "logs" / f"{experiment_id}.stdout.log").write_text(
                completed.stdout, encoding="utf-8"
            )
            (self.run_dir / "logs" / f"{experiment_id}.stderr.log").write_text(
                completed.stderr, encoding="utf-8"
            )
            if result_path.exists():
                raw = json.loads(result_path.read_text(encoding="utf-8"))
                status = str(raw.get("status", "failed"))
            else:
                raw = {"error": f"worker exited {completed.returncode} without a result"}
                unknown = ResourceVector(fits=planned_fits)
        except subprocess.TimeoutExpired as exc:
            status = "timeout"
            raw = {"error": f"worker timeout after {timeout}s: {exc}"}
            unknown = ResourceVector(fits=planned_fits)
        duration = time.monotonic() - started
        fit_attempts = int(raw.get("fit_attempts", 0))
        fit_completed = int(raw.get("fit_completed", 0))
        self.budget.settle(
            action_id,
            ResourceVector(experiments=1, fits=fit_attempts, seconds=duration),
            unknown=unknown,
        )
        fold_scores = tuple(float(value) for value in raw.get("fold_scores", []))
        mean_score = raw.get("mean_score")
        error = raw.get("error")
        if not all(math.isfinite(value) for value in fold_scores) or (
            mean_score is not None and not math.isfinite(float(mean_score))
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
