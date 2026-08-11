"""Builders and immutable persistence for current decision contexts."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from hifi_agent.decision.models import DecisionContext, PreviousRoundOutcome
from hifi_agent.orchestration.budget import BudgetSnapshot
from hifi_agent.orchestration.runtime_models import sha256_file, sha256_json
from hifi_agent.qc import QcFeatureBundle
from hifi_agent.schemas.assembly import AssemblyConfig
from hifi_agent.schemas.metrics import AssemblyMetrics


def build_decision_context(
    *,
    run_uuid: str,
    read_technology: Literal["pacbio_hifi"],
    sample_facts: dict[str, bool | int | float | str | None],
    qc_feature_bundle: QcFeatureBundle,
    incumbent_attempt_manifest: Path,
    incumbent_attempt_ref: Path,
    incumbent_config: AssemblyConfig,
    incumbent_metrics: AssemblyMetrics,
    incumbent_metric_source_sha256: dict[str, str],
    round_index: int,
    seen_parameter_fingerprints: tuple[str, ...],
    comparison_policy_id: str,
    comparison_policy_sha256: str,
    budget: BudgetSnapshot,
    previous_round_outcomes: tuple[PreviousRoundOutcome, ...] = (),
) -> DecisionContext:
    """Build a complete context from the current incumbent, never a fixed baseline path."""
    return DecisionContext(
        run_uuid=run_uuid,
        read_technology=read_technology,
        sample_facts=sample_facts,
        qc_feature_bundle=qc_feature_bundle,
        incumbent_attempt_ref=incumbent_attempt_ref,
        incumbent_attempt_sha256=sha256_file(incumbent_attempt_manifest),
        incumbent_config=incumbent_config,
        incumbent_parameter_fingerprint=incumbent_config.parameter_fingerprint(),
        incumbent_metrics=incumbent_metrics,
        incumbent_metric_source_sha256=incumbent_metric_source_sha256,
        round_index=round_index,
        seen_parameter_fingerprints=seen_parameter_fingerprints,
        comparison_policy_id=comparison_policy_id,
        comparison_policy_sha256=comparison_policy_sha256,
        remaining_budget={resource.value: amount for resource, amount in budget.balance.items()},
        previous_round_outcomes=previous_round_outcomes,
        applicable_metric_ids=qc_feature_bundle.applicable_metric_ids(),
        known_limitations=qc_feature_bundle.known_limitations,
        tool_failures=qc_feature_bundle.tool_failures,
        created_at=datetime.now(UTC),
    )


class DecisionContextStore:
    """Persist one immutable context per round and return its canonical hash."""

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir.resolve()

    def write(self, context: DecisionContext) -> tuple[Path, str]:
        """Create or verify the round context without overwriting it."""
        path = (
            self.run_dir
            / "04_decisions"
            / f"round_{context.round_index:02d}"
            / "decision_context.json"
        )
        content = context.model_dump_json(indent=2) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = DecisionContext.model_validate_json(path.read_text())
            if existing != context:
                raise ValueError("Decision context is immutable and already differs on disk")
        else:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            with os.fdopen(descriptor, "w") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        context_hash = sha256_json(context.model_dump(mode="json"))
        hash_path = path.with_suffix(".sha256")
        hash_content = f"{context_hash}  {path.name}\n"
        if hash_path.exists() and hash_path.read_text() != hash_content:
            raise ValueError("Decision context checksum sidecar differs")
        if not hash_path.exists():
            hash_path.write_text(hash_content)
        return path, context_hash
