"""Append-only current run budget ledger with idempotent reservations."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from hifi_agent.exceptions import AgentStateError
from hifi_agent.schemas.sample import ExecutionBudgetConfig


class BudgetResource(StrEnum):
    """Resources controlled by the run-level current ledger."""

    ASSEMBLY = "ASSEMBLY"
    TOOL_RETRY = "TOOL_RETRY"
    CPU_HOURS = "CPU_HOURS"
    WALLTIME_HOURS = "WALLTIME_HOURS"
    DISK_GIB = "DISK_GIB"
    LLM_CALL = "LLM_CALL"


class BudgetAction(StrEnum):
    """Allowed append-only budget mutations."""

    RESERVE = "RESERVE"
    COMMIT = "COMMIT"
    RELEASE = "RELEASE"
    ADJUST = "ADJUST"


_UNITS: dict[BudgetResource, str] = {
    BudgetResource.ASSEMBLY: "count",
    BudgetResource.TOOL_RETRY: "count",
    BudgetResource.CPU_HOURS: "cpu_hours",
    BudgetResource.WALLTIME_HOURS: "walltime_hours",
    BudgetResource.DISK_GIB: "GiB",
    BudgetResource.LLM_CALL: "count",
}


class BudgetLimits(BaseModel):
    """Immutable initial limits; ADJUST entries retain every later change."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    max_total_assemblies: int = Field(ge=1, le=7)
    max_tool_retries: int = Field(ge=0, le=3)
    max_cpu_hours: float = Field(ge=0.0)
    max_walltime_hours: float = Field(ge=0.0)
    min_free_disk_gib: float = Field(ge=0.0)
    max_llm_calls_per_round: int = Field(ge=0, le=1)
    max_total_llm_calls: int = Field(ge=0, le=3)

    @classmethod
    def from_config(cls, config: ExecutionBudgetConfig) -> BudgetLimits:
        """Project the executable budget fields into immutable ledger limits."""
        return cls(
            max_total_assemblies=config.max_total_assemblies,
            max_tool_retries=config.max_tool_retries,
            max_cpu_hours=config.max_cpu_hours,
            max_walltime_hours=config.max_walltime_hours,
            min_free_disk_gib=config.min_free_disk_gib,
            max_llm_calls_per_round=config.max_llm_calls_per_round,
            max_total_llm_calls=config.max_total_llm_calls,
        )

    def consumable_limits(self) -> dict[BudgetResource, float]:
        """Return scalar quotas; disk is checked against observed free capacity."""
        return {
            BudgetResource.ASSEMBLY: float(self.max_total_assemblies),
            BudgetResource.TOOL_RETRY: float(self.max_tool_retries),
            BudgetResource.CPU_HOURS: self.max_cpu_hours,
            BudgetResource.WALLTIME_HOURS: self.max_walltime_hours,
            BudgetResource.LLM_CALL: float(self.max_total_llm_calls),
        }


class BudgetEntry(BaseModel):
    """One immutable ledger operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    entry_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    operation_id: str
    reservation_id: str | None = None
    sequence: int = Field(ge=1)
    timestamp: datetime
    resource_type: BudgetResource
    action: BudgetAction
    amount: float
    unit: str
    round_id: str | None = None
    attempt_id: str | None = None
    llm_call_id: str | None = None
    reason_code: str
    balance_after: float
    observed_capacity: float | None = None


class BudgetSnapshot(BaseModel):
    """Derived ledger balances; never edited independently."""

    model_config = ConfigDict(extra="forbid")

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    sequence: int
    limits: dict[BudgetResource, float]
    committed: dict[BudgetResource, float]
    reserved: dict[BudgetResource, float]
    balance: dict[BudgetResource, float]


class BudgetLedger:
    """Persist and derive all current compute/call/disk budget operations."""

    def __init__(self, run_dir: Path) -> None:
        self.directory = run_dir.resolve() / "05_agent"
        self.limits_path = self.directory / "budget_limits.json"
        self.ledger_path = self.directory / "budget_ledger.jsonl"

    def initialize(self, limits: BudgetLimits) -> None:
        """Write immutable initial limits without replacing an existing ledger."""
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.limits_path.exists() or self.ledger_path.exists():
            raise AgentStateError("current budget ledger already exists")
        _exclusive_json(self.limits_path, limits.model_dump(mode="json"))
        descriptor = os.open(
            self.ledger_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o644,
        )
        os.close(descriptor)

    def reserve(
        self,
        resource: BudgetResource,
        amount: float,
        *,
        reservation_id: str,
        reason_code: str,
        round_id: str | None = None,
        attempt_id: str | None = None,
        llm_call_id: str | None = None,
    ) -> BudgetEntry:
        """Atomically reserve scalar quota; repeated IDs are idempotent."""
        if resource == BudgetResource.DISK_GIB:
            raise AgentStateError("Use reserve_disk() for observed free-disk capacity")
        if amount <= 0:
            raise AgentStateError("Budget reservation amount must be positive")
        existing = self._reservation_operation(reservation_id, BudgetAction.RESERVE)
        if existing is not None:
            if existing.resource_type != resource or existing.amount != amount:
                raise AgentStateError("Budget reservation ID was reused with different values")
            return existing
        if resource == BudgetResource.LLM_CALL:
            if round_id is None:
                raise AgentStateError("LLM call reservations require a round_id")
            round_calls = sum(
                entry.amount
                for entry in self.load_entries()
                if entry.resource_type == BudgetResource.LLM_CALL
                and entry.round_id == round_id
                and entry.action in {BudgetAction.RESERVE, BudgetAction.COMMIT}
            )
            released_calls = sum(
                entry.amount
                for entry in self.load_entries()
                if entry.resource_type == BudgetResource.LLM_CALL
                and entry.round_id == round_id
                and entry.action == BudgetAction.RELEASE
            )
            if round_calls - released_calls + amount > self.load_limits().max_llm_calls_per_round:
                raise AgentStateError("current per-round LLM call budget is exhausted")
        state = self._derive()
        balance = state.balance[resource]
        if amount > balance + 1e-12:
            raise AgentStateError(
                f"Budget exhausted for {resource.value}: requested={amount}, remaining={balance}"
            )
        return self._append(
            operation_id=f"reserve:{reservation_id}",
            reservation_id=reservation_id,
            resource=resource,
            action=BudgetAction.RESERVE,
            amount=amount,
            reason_code=reason_code,
            balance_after=balance - amount,
            round_id=round_id,
            attempt_id=attempt_id,
            llm_call_id=llm_call_id,
        )

    def reserve_disk(
        self,
        estimated_gib: float,
        *,
        observed_free_gib: float,
        reservation_id: str,
        reason_code: str,
        round_id: str | None = None,
        attempt_id: str | None = None,
    ) -> BudgetEntry:
        """Reserve expected disk while preserving the configured free-space floor."""
        if estimated_gib <= 0 or observed_free_gib < 0:
            raise AgentStateError("Disk reservation values must be positive")
        existing = self._reservation_operation(reservation_id, BudgetAction.RESERVE)
        if existing is not None:
            if (
                existing.resource_type != BudgetResource.DISK_GIB
                or existing.amount != estimated_gib
            ):
                raise AgentStateError("Disk reservation ID was reused with different values")
            # Free capacity naturally changes while an interrupted attempt is idle. The
            # original observation remains frozen in the ledger; a same-ID/same-estimate
            # resume reuses that reservation instead of fabricating a second disk charge.
            return existing
        limits = self.load_limits()
        outstanding = self.snapshot().reserved.get(BudgetResource.DISK_GIB, 0.0)
        usable = observed_free_gib - limits.min_free_disk_gib - outstanding
        if estimated_gib > usable + 1e-12:
            raise AgentStateError(
                "disk budget exhausted: artifacts would cross the free-space floor"
            )
        return self._append(
            operation_id=f"reserve:{reservation_id}",
            reservation_id=reservation_id,
            resource=BudgetResource.DISK_GIB,
            action=BudgetAction.RESERVE,
            amount=estimated_gib,
            reason_code=reason_code,
            balance_after=usable - estimated_gib,
            observed_capacity=observed_free_gib,
            round_id=round_id,
            attempt_id=attempt_id,
        )

    def commit(
        self,
        reservation_id: str,
        actual_amount: float,
        *,
        reason_code: str,
    ) -> BudgetEntry:
        """Settle a scalar reservation against actual usage exactly once."""
        if actual_amount < 0:
            raise AgentStateError("Committed budget amount cannot be negative")
        existing = self._reservation_operation(reservation_id, BudgetAction.COMMIT)
        if existing is not None:
            if existing.amount != actual_amount:
                raise AgentStateError("Budget commit ID was reused with a different amount")
            return existing
        reserved = self._active_reservation(reservation_id)
        if reserved.resource_type == BudgetResource.DISK_GIB:
            raise AgentStateError("Disk reservations are released after filesystem accounting")
        state = self._derive()
        resulting = state.balance[reserved.resource_type] + reserved.amount - actual_amount
        if resulting < -1e-12:
            raise AgentStateError(
                f"Actual {reserved.resource_type.value} usage exceeds remaining current budget"
            )
        return self._append(
            operation_id=f"commit:{reservation_id}",
            reservation_id=reservation_id,
            resource=reserved.resource_type,
            action=BudgetAction.COMMIT,
            amount=actual_amount,
            reason_code=reason_code,
            balance_after=resulting,
            round_id=reserved.round_id,
            attempt_id=reserved.attempt_id,
            llm_call_id=reserved.llm_call_id,
        )

    def release(self, reservation_id: str, *, reason_code: str) -> BudgetEntry:
        """Release an uncommitted reservation exactly once."""
        existing = self._reservation_operation(reservation_id, BudgetAction.RELEASE)
        if existing is not None:
            return existing
        reserved = self._active_reservation(reservation_id)
        state = self._derive()
        balance = state.balance.get(reserved.resource_type, reserved.balance_after)
        return self._append(
            operation_id=f"release:{reservation_id}",
            reservation_id=reservation_id,
            resource=reserved.resource_type,
            action=BudgetAction.RELEASE,
            amount=reserved.amount,
            reason_code=reason_code,
            balance_after=balance + reserved.amount,
            observed_capacity=reserved.observed_capacity,
            round_id=reserved.round_id,
            attempt_id=reserved.attempt_id,
            llm_call_id=reserved.llm_call_id,
        )

    def adjust_limit(
        self,
        resource: BudgetResource,
        delta: float,
        *,
        operation_id: str,
        reason_code: str,
    ) -> BudgetEntry:
        """Audit an explicit scalar limit adjustment; disk floor is not editable here."""
        if resource == BudgetResource.DISK_GIB or delta == 0:
            raise AgentStateError("Disk floor and zero-value adjustments are not supported")
        prior = self._operation(operation_id)
        if prior is not None:
            if prior.resource_type != resource or prior.amount != delta:
                raise AgentStateError("Budget adjustment operation ID was reused")
            return prior
        state = self._derive()
        new_balance = state.balance[resource] + delta
        if new_balance < -1e-12:
            raise AgentStateError("Budget adjustment would make the available balance negative")
        return self._append(
            operation_id=operation_id,
            reservation_id=None,
            resource=resource,
            action=BudgetAction.ADJUST,
            amount=delta,
            reason_code=reason_code,
            balance_after=new_balance,
        )

    def load_limits(self) -> BudgetLimits:
        """Load immutable initial limits."""
        try:
            return BudgetLimits.model_validate_json(self.limits_path.read_text())
        except (OSError, ValidationError) as exc:
            raise AgentStateError(f"current budget limits are invalid: {exc}") from exc

    def load_entries(self) -> list[BudgetEntry]:
        """Load a contiguous, duplicate-free append-only ledger."""
        if not self.ledger_path.is_file():
            raise AgentStateError("current budget ledger is missing")
        entries: list[BudgetEntry] = []
        for line_number, line in enumerate(self.ledger_path.read_text().splitlines(), start=1):
            if not line:
                raise AgentStateError(f"current budget ledger has an empty line at {line_number}")
            try:
                entries.append(BudgetEntry.model_validate_json(line))
            except ValidationError as exc:
                raise AgentStateError(
                    f"current budget ledger line {line_number} is invalid: {exc}"
                ) from exc
        observed = [entry.sequence for entry in entries]
        if observed != list(range(1, len(entries) + 1)):
            raise AgentStateError("current budget ledger sequence is not contiguous")
        if len({entry.entry_id for entry in entries}) != len(entries):
            raise AgentStateError("current budget ledger contains duplicate entry IDs")
        if len({entry.operation_id for entry in entries}) != len(entries):
            raise AgentStateError("current budget ledger contains duplicate operation IDs")
        return entries

    def snapshot(self) -> BudgetSnapshot:
        """Return balances derived from the ledger, never from an editable cache."""
        return self._derive()

    def _derive(self) -> BudgetSnapshot:
        limit_model = self.load_limits()
        limits = limit_model.consumable_limits()
        committed = dict.fromkeys(BudgetResource, 0.0)
        active: dict[str, BudgetEntry] = {}
        adjustments = dict.fromkeys(BudgetResource, 0.0)
        running_balance = dict(limits)
        llm_committed_by_round: dict[str, float] = {}
        disk_balance = 0.0
        entries = self.load_entries()
        for entry in entries:
            if entry.unit != _UNITS[entry.resource_type]:
                raise AgentStateError("current budget ledger entry has the wrong resource unit")
            if entry.action == BudgetAction.RESERVE:
                if (
                    entry.amount <= 0
                    or entry.reservation_id is None
                    or entry.reservation_id in active
                    or entry.operation_id != f"reserve:{entry.reservation_id}"
                ):
                    raise AgentStateError("current budget ledger has an invalid reservation")
                if entry.resource_type == BudgetResource.DISK_GIB:
                    if entry.observed_capacity is None:
                        raise AgentStateError("current disk reservation lacks observed capacity")
                    outstanding_disk = sum(
                        item.amount
                        for item in active.values()
                        if item.resource_type == BudgetResource.DISK_GIB
                    )
                    expected_balance = (
                        entry.observed_capacity
                        - limit_model.min_free_disk_gib
                        - outstanding_disk
                        - entry.amount
                    )
                else:
                    if entry.resource_type == BudgetResource.LLM_CALL:
                        if entry.round_id is None or entry.llm_call_id is None:
                            raise AgentStateError(
                                "current LLM reservation lacks round/call identity"
                            )
                        active_round_calls = sum(
                            item.amount
                            for item in active.values()
                            if item.resource_type == BudgetResource.LLM_CALL
                            and item.round_id == entry.round_id
                        )
                        round_total = (
                            llm_committed_by_round.get(entry.round_id, 0.0)
                            + active_round_calls
                            + entry.amount
                        )
                        if round_total > limit_model.max_llm_calls_per_round:
                            raise AgentStateError(
                                "current budget ledger exceeds per-round LLM call limit"
                            )
                    expected_balance = running_balance[entry.resource_type] - entry.amount
                active[entry.reservation_id] = entry
            elif entry.action in {BudgetAction.COMMIT, BudgetAction.RELEASE}:
                if entry.reservation_id is None or entry.reservation_id not in active:
                    raise AgentStateError("current budget ledger settles an inactive reservation")
                reserved = active.pop(entry.reservation_id)
                if reserved.resource_type != entry.resource_type:
                    raise AgentStateError(
                        "current budget settlement resource does not match reservation"
                    )
                if entry.action == BudgetAction.COMMIT:
                    if (
                        entry.amount < 0
                        or entry.resource_type == BudgetResource.DISK_GIB
                        or entry.operation_id != f"commit:{entry.reservation_id}"
                    ):
                        raise AgentStateError("current budget ledger has an invalid commit")
                    committed[entry.resource_type] += entry.amount
                    if entry.resource_type == BudgetResource.LLM_CALL:
                        assert entry.round_id is not None
                        llm_committed_by_round[entry.round_id] = (
                            llm_committed_by_round.get(entry.round_id, 0.0) + entry.amount
                        )
                    expected_balance = (
                        running_balance[entry.resource_type] + reserved.amount - entry.amount
                    )
                else:
                    if (
                        entry.amount != reserved.amount
                        or entry.operation_id != f"release:{entry.reservation_id}"
                    ):
                        raise AgentStateError("current budget ledger has an invalid release")
                    expected_balance = (
                        disk_balance + reserved.amount
                        if entry.resource_type == BudgetResource.DISK_GIB
                        else running_balance[entry.resource_type] + reserved.amount
                    )
            elif entry.action == BudgetAction.ADJUST:
                if (
                    entry.reservation_id is not None
                    or entry.amount == 0
                    or entry.resource_type == BudgetResource.DISK_GIB
                ):
                    raise AgentStateError("current budget ledger has an invalid limit adjustment")
                adjustments[entry.resource_type] += entry.amount
                expected_balance = running_balance[entry.resource_type] + entry.amount
            else:  # pragma: no cover - enum validation makes this defensive only
                raise AgentStateError("current budget ledger has an unsupported action")
            if expected_balance < -1e-12:
                raise AgentStateError("current budget ledger derives a negative balance")
            if abs(entry.balance_after - expected_balance) > 1e-9:
                raise AgentStateError("current budget ledger balance_after is inconsistent")
            if entry.resource_type == BudgetResource.DISK_GIB:
                disk_balance = expected_balance
            else:
                running_balance[entry.resource_type] = expected_balance

        reserved_totals = dict.fromkeys(BudgetResource, 0.0)
        for reservation in active.values():
            reserved_totals[reservation.resource_type] += reservation.amount
        effective_limits = {
            resource: amount + adjustments[resource] for resource, amount in limits.items()
        }
        balance = {resource: running_balance[resource] for resource in effective_limits}
        balance[BudgetResource.DISK_GIB] = disk_balance
        effective_limits[BudgetResource.DISK_GIB] = 0.0
        return BudgetSnapshot(
            sequence=len(entries),
            limits=effective_limits,
            committed=committed,
            reserved=reserved_totals,
            balance=balance,
        )

    def _active_reservation(self, reservation_id: str) -> BudgetEntry:
        active: BudgetEntry | None = None
        for entry in self.load_entries():
            if entry.reservation_id != reservation_id:
                continue
            if entry.action == BudgetAction.RESERVE:
                active = entry
            elif entry.action in {BudgetAction.COMMIT, BudgetAction.RELEASE}:
                active = None
        if active is None:
            raise AgentStateError(f"No active current budget reservation: {reservation_id}")
        return active

    def _reservation_operation(
        self,
        reservation_id: str,
        action: BudgetAction,
    ) -> BudgetEntry | None:
        return next(
            (
                entry
                for entry in self.load_entries()
                if entry.reservation_id == reservation_id and entry.action == action
            ),
            None,
        )

    def _operation(self, operation_id: str) -> BudgetEntry | None:
        return next(
            (entry for entry in self.load_entries() if entry.operation_id == operation_id),
            None,
        )

    def _append(
        self,
        *,
        operation_id: str,
        reservation_id: str | None,
        resource: BudgetResource,
        action: BudgetAction,
        amount: float,
        reason_code: str,
        balance_after: float,
        observed_capacity: float | None = None,
        round_id: str | None = None,
        attempt_id: str | None = None,
        llm_call_id: str | None = None,
    ) -> BudgetEntry:
        entries = self.load_entries()
        entry = BudgetEntry(
            entry_id=uuid.uuid4().hex,
            operation_id=operation_id,
            reservation_id=reservation_id,
            sequence=len(entries) + 1,
            timestamp=datetime.now(UTC),
            resource_type=resource,
            action=action,
            amount=amount,
            unit=_UNITS[resource],
            round_id=round_id,
            attempt_id=attempt_id,
            llm_call_id=llm_call_id,
            reason_code=reason_code,
            balance_after=balance_after,
            observed_capacity=observed_capacity,
        )
        with self.ledger_path.open("a") as handle:
            handle.write(entry.model_dump_json())
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        return entry


def _exclusive_json(path: Path, payload: object) -> None:
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
