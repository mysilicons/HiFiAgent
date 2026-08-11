"""Release-only live provider smoke bound to a completed real decision context."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from hifi_agent.decision import (
    DecisionContext,
    LocalGovernedRetriever,
    ProposalDecision,
    ProposalDirective,
    ProposalService,
)
from hifi_agent.exceptions import LLMProviderError
from hifi_agent.orchestration.budget import BudgetLedger, BudgetLimits
from hifi_agent.orchestration.environment import EnvironmentManifest
from hifi_agent.orchestration.identity import IdentityStore
from hifi_agent.orchestration.runtime_models import sha256_file, sha256_json


class LiveSmokeManifest(BaseModel):
    """Secret-free evidence that a live response passed Schema and the arbiter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_id: Literal["hifi-agent"] = "hifi-agent"
    status: Literal["PASS"] = "PASS"
    created_at: datetime
    run_uuid: str = Field(pattern=r"^[0-9a-f]{32}$")
    code_commit: str
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    directive_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rag_index_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str
    model: str
    call_id: str
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    schema_validation: Literal["PASS"] = "PASS"
    safety_arbiter: Literal["PASS"] = "PASS"
    secret_scan: Literal["PASS"] = "PASS"


def run_live_smoke(run_dir: Path, output_dir: Path) -> Path:
    """Call the live provider once using a real run context and frozen retrieval index."""
    root = run_dir.resolve()
    target = output_dir.resolve()
    if target.exists() and any(target.iterdir()):
        raise LLMProviderError(f"Live smoke output directory is not empty: {target}")
    identity = IdentityStore(root).verify_snapshots()
    context_path = root / "04_decisions/round_01/decision_context.json"
    directive_path = root / "04_decisions/round_01/rule_directive.json"
    index_path = root / "04_decisions/rag_index_snapshot.json"
    environment_path = root / "00_metadata/environment_manifest.json"
    try:
        context = DecisionContext.model_validate_json(context_path.read_text())
        directive = ProposalDirective.model_validate_json(directive_path.read_text())
        environment = EnvironmentManifest.model_validate_json(environment_path.read_text())
    except (OSError, ValueError) as exc:
        raise LLMProviderError(f"Real run smoke inputs are invalid: {exc}") from exc
    if directive.action != "PROPOSE":
        raise LLMProviderError("Live smoke requires a real round with a governed PROPOSE directive")
    hifiasm = next((item for item in environment.tools if item.name == "hifiasm"), None)
    if hifiasm is None or not hifiasm.version:
        raise LLMProviderError("Real run environment lacks hifiasm version evidence")

    ledger = BudgetLedger(target)
    ledger.initialize(
        BudgetLimits(
            max_total_assemblies=1,
            max_tool_retries=0,
            max_cpu_hours=0,
            max_walltime_hours=0,
            min_free_disk_gib=0,
            max_llm_calls_per_round=1,
            max_total_llm_calls=1,
        )
    )
    service = ProposalService(
        target,
        budget=ledger,
        retriever=LocalGovernedRetriever(
            index_path,
            actual_hifiasm_version=hifiasm.version,
        ),
    )
    decision = service.propose_run(
        context,
        directive,
        decision_mode="hybrid",
        require_llm=True,
        max_candidates=1,
        confirm_medium_high_risk=False,
    )
    receipt = decision.llm_receipt
    required = (
        receipt.status == "SUCCESS",
        receipt.provider == "deepseek",
        receipt.model is not None,
        receipt.prompt_sha256 is not None,
        receipt.schema_sha256 is not None,
        receipt.output_sha256 is not None,
        decision.status != "FAILED_REQUIRED_LLM",
    )
    if not all(required):
        raise LLMProviderError(
            f"Live provider smoke did not pass: status={receipt.status}, "
            f"provider={receipt.provider}, decision={decision.status}"
        )
    assert receipt.provider is not None
    assert receipt.model is not None
    assert receipt.prompt_sha256 is not None
    assert receipt.schema_sha256 is not None
    assert receipt.output_sha256 is not None
    receipt_path = target / "04_decisions/round_01/llm_call_receipt.json"
    decision_path = target / "04_decisions/round_01/proposal_decision.json"
    _require_secret_free(target)
    manifest = LiveSmokeManifest(
        created_at=datetime.now(UTC),
        run_uuid=identity.run_uuid,
        code_commit=identity.code_commit,
        context_sha256=sha256_json(context.model_dump(mode="json")),
        directive_sha256=sha256_json(directive.model_dump(mode="json")),
        rag_index_sha256=sha256_file(index_path),
        provider=receipt.provider,
        model=receipt.model,
        call_id=receipt.call_id,
        prompt_sha256=receipt.prompt_sha256,
        schema_sha256=receipt.schema_sha256,
        output_sha256=receipt.output_sha256,
        receipt_sha256=sha256_file(receipt_path),
        decision_sha256=sha256_file(decision_path),
        approved_count=len(decision.approved),
        rejected_count=len(decision.rejected),
    )
    manifest_path = target / "live_smoke_manifest.json"
    _exclusive_json(manifest_path, manifest)
    return manifest_path


def verify_live_smoke(run_dir: Path, manifest_path: Path) -> LiveSmokeManifest:
    """Verify a smoke manifest remains bound to its real run and persisted decisions."""
    root = run_dir.resolve()
    manifest = LiveSmokeManifest.model_validate_json(manifest_path.read_text())
    identity = IdentityStore(root).verify_snapshots()
    if manifest.run_uuid != identity.run_uuid or manifest.code_commit != identity.code_commit:
        raise LLMProviderError("Live smoke manifest belongs to another real run or commit")
    smoke_root = manifest_path.resolve().parent
    receipt = smoke_root / "04_decisions/round_01/llm_call_receipt.json"
    decision = smoke_root / "04_decisions/round_01/proposal_decision.json"
    if sha256_file(receipt) != manifest.receipt_sha256:
        raise LLMProviderError("Live smoke receipt checksum changed")
    if sha256_file(decision) != manifest.decision_sha256:
        raise LLMProviderError("Live smoke decision checksum changed")
    parsed = ProposalDecision.model_validate_json(decision.read_text())
    if parsed.llm_receipt.status != "SUCCESS" or parsed.llm_receipt.provider != "deepseek":
        raise LLMProviderError("Live smoke decision no longer records a successful provider call")
    _require_secret_free(smoke_root)
    return manifest


def _require_secret_free(root: Path) -> None:
    secret = os.environ.get("DEEPSEEK_API_KEY", "")
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        content = path.read_bytes()
        lowered = content.lower()
        if (secret and secret.encode() in content) or any(
            marker in lowered for marker in (b"deepseek_api_key", b'"authorization"', b"bearer sk-")
        ):
            raise LLMProviderError(f"Live smoke artifact contains provider credentials: {path}")


def _exclusive_json(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(model.model_dump_json(indent=2) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
