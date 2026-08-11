"""Ports and terminal result owned by the single production coordinator."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from hifi_agent.decision.client import StructuredLLMClient
from hifi_agent.decision.models import DecisionContext, ProposalDirective
from hifi_agent.decision.service import ProposalProvider
from hifi_agent.executors.models import (
    AssemblyInputManifest,
    AttemptCoordinate,
    ExecutionEstimate,
)
from hifi_agent.orchestration.budget import BudgetLedger
from hifi_agent.orchestration.manifests import AssemblyAttemptRecord
from hifi_agent.orchestration.runtime_models import RunState
from hifi_agent.reporting.service import ReportBundle
from hifi_agent.schemas.assembly import RiskLevel
from hifi_agent.schemas.sample import SampleConfig


class PreQcRunner(Protocol):
    """Run-level pre-QC port used before the common assembly executor."""

    def __call__(self, sample: SampleConfig, *, resume: bool) -> AssemblyInputManifest:
        """Return checksummed inputs for the common assembly executor."""


class ProposalServiceFactory(Protocol):
    """Create the one governed proposal provider for a bootstrapped run."""

    def __call__(
        self,
        run_dir: Path,
        budget: BudgetLedger,
        confirmation_risk_levels: set[RiskLevel],
    ) -> ProposalProvider:
        """Return a provider with no execution capability."""


CoordinatorFaultInjector = Callable[[str, RunState], None]
DirectiveProvider = Callable[[DecisionContext], ProposalDirective]
EstimateProvider = Callable[[AttemptCoordinate], ExecutionEstimate]


class CoordinatorResult(BaseModel):
    """Terminal result of the only public current production coordinator."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    run_dir: Path
    state: RunState
    baseline_attempt: AssemblyAttemptRecord | None
    report_bundle: ReportBundle


__all__ = [
    "CoordinatorFaultInjector",
    "CoordinatorResult",
    "DirectiveProvider",
    "EstimateProvider",
    "PreQcRunner",
    "ProposalServiceFactory",
    "StructuredLLMClient",
]
