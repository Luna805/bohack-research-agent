from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib

from .budget import Budget
from .contracts import (
    freeze_contract,
    stable_hash,
    validate_experiment_spec,
    validate_proposal_batch,
)
from .data import load_dataset, numeric_minima, split_manifest
from .evaluator import calibrate, evaluate_candidate, evaluate_confirmation
from .ledger import EventLedger, atomic_write_json, utc_now
from .pipeline import build_pipeline
from .reporting import write_report
from .runner import Runner
from .schemas import (
    BudgetLimits,
    Candidate,
    EvaluationRecord,
    ExperimentSpec,
    ForestSpec,
    HistBoostSpec,
    Hypothesis,
    LogisticSpec,
    PreprocessingSpec,
    ProposalBatch,
    ProtocolSpec,
    ResourceVector,
    TaskContract,
)
from .search import baseline_spec, sample_specs


def make_run_id(system: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{system}-{uuid.uuid4().hex[:6]}"


class ScriptedProposer:
    source = "scripted"

    def propose(
        self, round_index: int, baseline_id: str, evidence_refs: tuple[str, ...]
    ) -> ProposalBatch:
        if round_index == 0:
            specs = (
                ExperimentSpec(
                    model=LogisticSpec(family="logistic_regression", c=0.2, max_iter=500),
                    preprocessing=PreprocessingSpec(numeric_scaler="standard"),
                ),
                ExperimentSpec(
                    model=ForestSpec(family="random_forest", n_estimators=100, min_samples_leaf=2)
                ),
            )
            interpretation = "No previous candidate result; start with controlled alternatives."
        else:
            specs = (
                ExperimentSpec(
                    model=HistBoostSpec(
                        family="hist_gradient_boosting",
                        learning_rate=0.06,
                        max_iter=100,
                        min_samples_leaf=20,
                    )
                ),
                ExperimentSpec(
                    model=LogisticSpec(
                        family="logistic_regression",
                        c=2.0,
                        class_weight="balanced",
                        max_iter=500,
                    ),
                    preprocessing=PreprocessingSpec(numeric_scaler="standard"),
                ),
            )
            interpretation = (
                "The first-round program result is included in evidence_refs; "
                "test a nonlinear alternative without changing the protocol."
            )
        candidates = tuple(
            Candidate(
                candidate_id=f"scripted-r{round_index + 1}-c{index + 1}",
                hypothesis=Hypothesis(
                    statement="A controlled model change may improve the frozen metric.",
                    evidence_refs=evidence_refs,
                    comparator_experiment_id=baseline_id,
                    decision_policy_id="practical_gain_v2",
                    proposed_change=spec.model.family,
                ),
                experiment=spec,
            )
            for index, spec in enumerate(specs)
        )
        return ProposalBatch(
            previous_result_interpretation=interpretation,
            intent="explore" if round_index == 0 else "refine",
            direction=f"offline-round-{round_index + 1}",
            candidates=candidates,
        )


def build_protocol(
    config: dict[str, Any], dataset_hash: str, columns: tuple[str, ...]
) -> ProtocolSpec:
    limits = config["budget"]
    return ProtocolSpec(
        task_id="breast-cancer-offline-smoke",
        dataset_ref=config["dataset_ref"],
        dataset_hash=dataset_hash,
        scenario_card_hash=stable_hash(
            {"prediction_time": "diagnostic features available at classification time"}
        ),
        target_column="target",
        prediction_time="diagnostic features available at classification time",
        approved_feature_columns=columns,
        split_seed=config["split_seed"],
        calibration_split_seeds=tuple(config["calibration_split_seeds"]),
        confirmation_split_seeds=tuple(config["confirmation_split_seeds"]),
        cv_folds=config["cv_folds"],
        search_training_seed=config["training_seed"],
        allowed_model_families=("logistic_regression", "random_forest", "hist_gradient_boosting"),
        min_effect_floor=config["min_effect_floor"],
        budgets=BudgetLimits(
            max_llm_tokens=0,
            max_llm_requests=0,
            max_cost_usd=0,
            max_experiments=limits["max_experiments"],
            max_fits=limits["max_fits"],
            max_total_seconds=limits["max_total_seconds"],
            experiment_timeout_seconds=limits["experiment_timeout_seconds"],
        ),
    )


def provisional_contract(protocol: ProtocolSpec, manifest_hash: str) -> TaskContract:
    return TaskContract(
        parent_protocol_hash=stable_hash(protocol),
        task_id=protocol.task_id,
        dataset_ref=protocol.dataset_ref,
        dataset_hash=protocol.dataset_hash,
        scenario_card_hash=protocol.scenario_card_hash,
        target_column=protocol.target_column,
        primary_metric=protocol.primary_metric,
        prediction_time=protocol.prediction_time,
        approved_feature_columns=protocol.approved_feature_columns,
        text_columns=protocol.text_columns,
        split_seed=protocol.split_seed,
        split_manifest_hash=manifest_hash,
        cv_folds=protocol.cv_folds,
        search_training_seed=protocol.search_training_seed,
        allowed_model_families=protocol.allowed_model_families,
        decision_policy={
            "metric": protocol.primary_metric,
            "min_effect_floor": protocol.min_effect_floor,
            "noise_floor": 0.0,
            "min_effect": protocol.min_effect_floor,
            "calibration_split_seeds": protocol.calibration_split_seeds,
            "confirmation_split_seeds": protocol.confirmation_split_seeds,
        },
        budgets=protocol.budgets,
        memory_snapshot_hash=stable_hash([]),
    )


def run_research(
    config: dict[str, Any], system: str, runs_root: Path = Path("runs")
) -> dict[str, Any]:
    run_id = make_run_id(system)
    run_dir = runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    ledger = EventLedger(run_id, run_dir)
    ledger.append("run_created", details={"system": system, "proposal_source": system})
    bundle = load_dataset(config["dataset_ref"])
    protocol = build_protocol(config, bundle.dataset_hash, tuple(bundle.features.columns))
    atomic_write_json(run_dir / "protocol.json", protocol.model_dump(mode="json"))
    ledger.append("protocol_accepted", artifact_ref="protocol.json")
    all_seeds = (
        protocol.split_seed,
        *protocol.calibration_split_seeds,
        *protocol.confirmation_split_seeds,
    )
    manifest, manifest_hash = split_manifest(bundle, all_seeds, protocol.cv_folds)
    atomic_write_json(run_dir / "split_manifest.json", manifest)
    tail = ResourceVector(experiments=7, fits=6 * protocol.cv_folds + 1, seconds=300)
    budget = Budget(protocol.budgets, run_dir / "budget.json", ledger, tail_reserve=tail)
    provisional = provisional_contract(protocol, manifest_hash)
    runner = Runner(run_dir, ledger, budget)
    baseline = baseline_spec()
    minima = numeric_minima(bundle.features)
    validate_experiment_spec(baseline, provisional, numeric_minima=minima)
    baseline_result = runner.execute(
        baseline,
        provisional,
        purpose="initial_baseline",
        split_seed=protocol.split_seed,
        experiment_id="baseline",
    )
    if baseline_result.status != "ok":
        raise RuntimeError(f"baseline failed: {baseline_result.error}")
    ledger.append("baseline_completed", artifact_ref=baseline_result.artifact_ref)
    calibration_results = [
        runner.execute(
            baseline,
            provisional,
            purpose="calibration",
            split_seed=seed,
            experiment_id=f"calibration-{seed}",
        )
        for seed in protocol.calibration_split_seeds
    ]
    calibration = calibrate(stable_hash(protocol), calibration_results, protocol.min_effect_floor)
    atomic_write_json(run_dir / "calibration.json", calibration.model_dump(mode="json"))
    ledger.append("calibration_completed", artifact_ref="calibration.json")
    contract = freeze_contract(
        protocol,
        calibration,
        split_manifest_hash=manifest_hash,
        memory_snapshot_hash=stable_hash([]),
    )
    atomic_write_json(run_dir / "contract.json", contract.model_dump(mode="json"))
    ledger.append("contract_frozen", artifact_ref="contract.json")

    explored: list[tuple[ExperimentSpec, Any, EvaluationRecord]] = []
    evidence_refs = [baseline_result.artifact_ref, "calibration.json", "contract.json"]
    if system == "scripted_smoke":
        proposer = ScriptedProposer()
        for round_index in range(2):
            batch = proposer.propose(
                round_index, baseline_result.experiment_id, tuple(evidence_refs)
            )
            validate_proposal_batch(
                batch,
                allowed_evidence_refs=evidence_refs,
                known_experiment_ids=[baseline_result.experiment_id],
            )
            batch_ref = f"proposals/round-{round_index + 1}.json"
            atomic_write_json(run_dir / batch_ref, batch.model_dump(mode="json"))
            ledger.append(
                "proposal_received",
                artifact_ref=batch_ref,
                details={"proposal_source": "scripted"},
            )
            selected = batch.candidates[0]
            ledger.append(
                "candidate_selected",
                details={"candidate_id": selected.candidate_id, "round": round_index + 1},
            )
            ledger.append(
                "candidate_not_run",
                reason_code="smoke_single_candidate_policy",
                details={"candidate_id": batch.candidates[1].candidate_id},
            )
            validate_experiment_spec(selected.experiment, contract, numeric_minima=minima)
            result = runner.execute(
                selected.experiment,
                contract,
                purpose="exploration",
                split_seed=contract.split_seed,
                experiment_id=selected.candidate_id,
            )
            evaluation = evaluate_candidate(
                result, baseline_result, contract.decision_policy.min_effect
            )
            evaluation_ref = f"evaluations/{result.experiment_id}.json"
            atomic_write_json(run_dir / evaluation_ref, evaluation.model_dump(mode="json"))
            ledger.append("evaluation_recorded", artifact_ref=evaluation_ref)
            explored.append((selected.experiment, result, evaluation))
            evidence_refs.extend([result.artifact_ref, evaluation_ref])
    elif system == "random_search":
        specs = sample_specs(config["search_seed"], config["search_candidates"])
        for index, spec in enumerate(specs):
            validate_experiment_spec(spec, contract, numeric_minima=minima)
            result = runner.execute(
                spec,
                contract,
                purpose="exploration",
                split_seed=contract.split_seed,
                experiment_id=f"random-{index + 1}",
            )
            evaluation = evaluate_candidate(
                result, baseline_result, contract.decision_policy.min_effect
            )
            evaluation_ref = f"evaluations/{result.experiment_id}.json"
            atomic_write_json(run_dir / evaluation_ref, evaluation.model_dump(mode="json"))
            ledger.append("evaluation_recorded", artifact_ref=evaluation_ref)
            explored.append((spec, result, evaluation))
    else:
        raise ValueError(f"unsupported research system: {system}")

    passing = [item for item in explored if item[2].policy_status == "candidate_pass"]
    passing.sort(
        key=lambda item: (
            -(item[1].mean_score or -1),
            item[1].duration_seconds,
            stable_hash(item[0]),
        )
    )
    candidate = passing[0] if passing else None
    delivered_spec = baseline
    confirmation_status = "not_required_no_candidate"
    budget.set_tail_reserve(ResourceVector())
    if candidate is not None:
        candidate_spec, candidate_result, _ = candidate
        deltas: list[float] = []
        confirmation_refs: list[str] = []
        for seed in contract.decision_policy.confirmation_split_seeds:
            candidate_confirm = runner.execute(
                candidate_spec,
                contract,
                purpose="confirmation_candidate",
                split_seed=seed,
                experiment_id=f"confirm-candidate-{seed}",
            )
            baseline_confirm = runner.execute(
                baseline,
                contract,
                purpose="confirmation_baseline",
                split_seed=seed,
                experiment_id=f"confirm-baseline-{seed}",
            )
            confirmation_refs.extend(
                [candidate_confirm.artifact_ref, baseline_confirm.artifact_ref]
            )
            if (
                candidate_confirm.status == "ok"
                and baseline_confirm.status == "ok"
                and candidate_confirm.mean_score is not None
                and baseline_confirm.mean_score is not None
            ):
                deltas.append(candidate_confirm.mean_score - baseline_confirm.mean_score)
        confirmation = evaluate_confirmation(
            candidate_result.experiment_id,
            deltas,
            contract.decision_policy.min_effect,
            contract.decision_policy.min_positive_fraction,
            tuple(confirmation_refs),
        )
        atomic_write_json(run_dir / "confirmation.json", confirmation.model_dump(mode="json"))
        ledger.append("confirmation_completed", artifact_ref="confirmation.json")
        confirmation_status = confirmation.policy_status
        if confirmation.policy_status == "confirmed_pass":
            delivered_spec = candidate_spec

    refit = runner.execute(
        delivered_spec, contract, purpose="final_refit", experiment_id="final-refit"
    )
    if refit.status != "ok":
        ledger.append("refit_failed", artifact_ref=refit.artifact_ref)
        raise RuntimeError(f"final refit failed: {refit.error}")
    ledger.append("refit_completed", artifact_ref=refit.artifact_ref)
    model_path = run_dir / "delivery" / "model.joblib"
    delivery = {
        "run_id": run_id,
        "system": system,
        "contract_hash": stable_hash(contract),
        "dataset_hash": contract.dataset_hash,
        "delivered_spec": delivered_spec.model_dump(mode="json"),
        "delivered_spec_hash": stable_hash(delivered_spec),
        "model_ref": "delivery/model.joblib",
        "model_hash": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "confirmation_status": confirmation_status,
        "frozen_at": utc_now(),
    }
    atomic_write_json(run_dir / "delivery" / "frozen_delivery.json", delivery)
    ledger.append("delivery_frozen", artifact_ref="delivery/frozen_delivery.json")
    summary = {
        "run_id": run_id,
        "proposal_source": "scripted" if system == "scripted_smoke" else "random_search",
        "dataset_ref": contract.dataset_ref,
        "baseline_score": baseline_result.mean_score,
        "exploration_best_score": max(
            (result.mean_score for _, result, _ in explored if result.mean_score is not None),
            default=None,
        ),
        "confirmation_status": confirmation_status,
        "delivered_spec_hash": delivery["delivered_spec_hash"],
        "model_ref": delivery["model_ref"],
        "budget": budget.summary(),
    }
    write_report(run_dir, summary)
    ledger.append("run_terminal", artifact_ref="summary.json", reason_code="completed")
    return summary


def reproduce_run(run_id: str, runs_root: Path = Path("runs")) -> dict[str, Any]:
    run_dir = runs_root / run_id
    contract = TaskContract.model_validate_json(
        (run_dir / "contract.json").read_text(encoding="utf-8")
    )
    delivery = json.loads(
        (run_dir / "delivery" / "frozen_delivery.json").read_text(encoding="utf-8")
    )
    spec = ExperimentSpec.model_validate(delivery["delivered_spec"])
    bundle = load_dataset(contract.dataset_ref)
    if bundle.dataset_hash != contract.dataset_hash:
        raise ValueError("dataset hash changed; refusing reproduction")
    pipeline = build_pipeline(spec, bundle.features, contract.search_training_seed)
    pipeline.fit(bundle.features, bundle.target)
    destination = (
        run_dir
        / "reproductions"
        / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + f"-{uuid.uuid4().hex[:4]}")
    )
    destination.mkdir(parents=True, exist_ok=False)
    model_path = destination / "model.joblib"
    joblib.dump(pipeline, model_path)
    result = {
        "run_id": run_id,
        "status": "ok",
        "fit_attempts": 1,
        "dataset_hash": bundle.dataset_hash,
        "spec_hash": stable_hash(spec),
        "model_ref": str(model_path),
    }
    atomic_write_json(destination / "reproduction.json", result)
    return result


def replay_run(run_id: str, runs_root: Path = Path("runs")) -> dict[str, Any]:
    events = EventLedger(run_id, runs_root / run_id).read_events()
    return {
        "run_id": run_id,
        "mode": "replay",
        "event_count": len(events),
        "fit_attempts_started_by_replay": 0,
        "llm_requests_started_by_replay": 0,
        "terminal_event": events[-1]["event_type"] if events else None,
    }
