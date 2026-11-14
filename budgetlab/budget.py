from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from .ledger import EventLedger, atomic_write_json
from .schemas import BudgetLimits, ResourceVector

RESOURCE_FIELDS = (
    "llm_tokens",
    "llm_requests",
    "cost_usd",
    "experiments",
    "fits",
    "seconds",
)


def add_resources(*vectors: ResourceVector) -> ResourceVector:
    return ResourceVector(
        **{field: sum(getattr(vector, field) for vector in vectors) for field in RESOURCE_FIELDS}
    )


def subtract_resources(left: ResourceVector, right: ResourceVector) -> ResourceVector:
    return ResourceVector(
        **{field: max(0, getattr(left, field) - getattr(right, field)) for field in RESOURCE_FIELDS}
    )


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    def __init__(
        self,
        limits: BudgetLimits,
        state_path: Path,
        ledger: EventLedger,
        *,
        tail_reserve: ResourceVector | None = None,
    ) -> None:
        self.limits = limits
        self.state_path = state_path
        self.ledger = ledger
        self.tail_reserve = tail_reserve or ResourceVector()
        self.used = ResourceVector()
        self.reserved = ResourceVector()
        self.unknown = ResourceVector()
        self.reservations: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._persist()

    def _limit_for(self, field: str) -> float | int | None:
        return {
            "llm_tokens": self.limits.max_llm_tokens,
            "llm_requests": self.limits.max_llm_requests,
            "cost_usd": self.limits.max_cost_usd,
            "experiments": self.limits.max_experiments,
            "fits": self.limits.max_fits,
            "seconds": self.limits.max_total_seconds,
        }[field]

    def _persist(self) -> None:
        atomic_write_json(self.state_path, self.summary())

    def summary(self) -> dict[str, Any]:
        return {
            "limits": self.limits.model_dump(mode="json"),
            "used": self.used.model_dump(mode="json"),
            "reserved": self.reserved.model_dump(mode="json"),
            "unknown": self.unknown.model_dump(mode="json"),
            "tail_reserve": self.tail_reserve.model_dump(mode="json"),
            "reservations": self.reservations,
        }

    def set_tail_reserve(self, reserve: ResourceVector) -> None:
        with self._lock:
            self.tail_reserve = reserve
            self._persist()

    def reserve(self, action_id: str, planned: ResourceVector) -> dict[str, Any]:
        with self._lock:
            if action_id in self.reservations:
                raise ValueError(f"action already has a reservation: {action_id}")
            occupied = add_resources(self.used, self.reserved, self.unknown, self.tail_reserve)
            failures = []
            for field in RESOURCE_FIELDS:
                limit = self._limit_for(field)
                if limit is None:
                    continue
                if getattr(occupied, field) + getattr(planned, field) > limit + 1e-12:
                    failures.append(field)
            if failures:
                raise BudgetExceeded(f"insufficient budget for {action_id}: {', '.join(failures)}")
            self.reserved = add_resources(self.reserved, planned)
            record = {
                "action_id": action_id,
                "planned": planned.model_dump(mode="json"),
                "actual": ResourceVector().model_dump(mode="json"),
                "unknown": ResourceVector().model_dump(mode="json"),
                "status": "reserved",
            }
            self.reservations[action_id] = record
            self._persist()
            self.ledger.append(
                "budget_reserved", action_id=action_id, details={"planned": record["planned"]}
            )
            return record

    def settle(
        self,
        action_id: str,
        actual: ResourceVector,
        *,
        unknown: ResourceVector | None = None,
    ) -> None:
        unknown = unknown or ResourceVector()
        with self._lock:
            record = self.reservations.get(action_id)
            if record is None:
                raise ValueError(f"unknown reservation: {action_id}")
            if record["status"] != "reserved":
                raise ValueError(f"reservation already finalized: {action_id}")
            planned = ResourceVector.model_validate(record["planned"])
            self.reserved = subtract_resources(self.reserved, planned)
            self.used = add_resources(self.used, actual)
            self.unknown = add_resources(self.unknown, unknown)
            record["actual"] = actual.model_dump(mode="json")
            record["unknown"] = unknown.model_dump(mode="json")
            record["status"] = "settled" if unknown == ResourceVector() else "unknown"
            self._persist()
            self.ledger.append(
                "budget_settled",
                action_id=action_id,
                details={"actual": record["actual"], "unknown": record["unknown"]},
            )

    def release(self, action_id: str) -> None:
        with self._lock:
            record = self.reservations.get(action_id)
            if record is None or record["status"] != "reserved":
                raise ValueError(f"reservation cannot be released: {action_id}")
            planned = ResourceVector.model_validate(record["planned"])
            self.reserved = subtract_resources(self.reserved, planned)
            record["status"] = "released"
            self._persist()
            self.ledger.append("budget_released", action_id=action_id)

    def mark_interrupted_unknown(self, action_id: str) -> None:
        with self._lock:
            record = self.reservations.get(action_id)
            if record is None or record["status"] != "reserved":
                raise ValueError(f"reservation cannot be marked unknown: {action_id}")
            planned = ResourceVector.model_validate(record["planned"])
            self.reserved = subtract_resources(self.reserved, planned)
            self.unknown = add_resources(self.unknown, planned)
            record["unknown"] = planned.model_dump(mode="json")
            record["status"] = "unknown"
            self._persist()
            self.ledger.append(
                "budget_settled",
                action_id=action_id,
                reason_code="interrupted_unknown",
                details={"unknown": record["unknown"]},
            )
