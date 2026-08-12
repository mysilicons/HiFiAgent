"""Single production coordinator and authoritative lifecycle state machine."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from hifi_agent.config import verify_recorded_input_checksums
from hifi_agent.constants import __version__
from hifi_agent.data import COMPARISON_POLICY, KNOWLEDGE_INDEX
from hifi_agent.decision.client import RecordedLLMClient, StructuredLLMClient
from hifi_agent.decision.retrieval import LocalGovernedRetriever
from hifi_agent.decision.rules import build_rule_directive
from hifi_agent.decision.service import ProposalProvider, ProposalService
from hifi_agent.exceptions import (
    AgentStateError,
    InterruptedExecutionError,
    RuleEvaluationError,
    ToolExecutionError,
)
from hifi_agent.executors.assembly import AssemblyExecutor, AssemblyWorkflowRunner
from hifi_agent.executors.models import (
    AssemblyInputManifest,
    AttemptCoordinate,
    ExecutionEstimate,
)
from hifi_agent.executors.nextflow import (
    NextflowAssemblyRunner,
    assembly_inputs_from_run,
    run_pre_qc_workflow,
)
from hifi_agent.orchestration.budget import BudgetLedger, BudgetLimits
from hifi_agent.orchestration.busco_cache import prepare_busco_lineage
from hifi_agent.orchestration.comparison import (
    RoundComparator,
)
from hifi_agent.orchestration.coordinator_models import (
    CoordinatorFaultInjector,
    CoordinatorResult,
    DirectiveProvider,
    EstimateProvider,
    PreQcRunner,
    ProposalServiceFactory,
)
from hifi_agent.orchestration.coordinator_rounds import CoordinatorRounds
from hifi_agent.orchestration.coordinator_support import (
    append_unique as _append_unique,
)
from hifi_agent.orchestration.coordinator_support import (
    attempt_manifest_ref as _attempt_manifest_ref,
)
from hifi_agent.orchestration.coordinator_support import (
    build_or_verify_qc as _build_or_verify_qc,
)
from hifi_agent.orchestration.coordinator_support import (
    code_commit as _code_commit,
)
from hifi_agent.orchestration.coordinator_support import (
    exclusive_copy as _exclusive_copy,
)
from hifi_agent.orchestration.coordinator_support import (
    latest_attempt as _latest_attempt,
)
from hifi_agent.orchestration.coordinator_support import (
    load_context as _load_context,
)
from hifi_agent.orchestration.coordinator_support import (
    load_proposal_decision as _load_proposal_decision,
)
from hifi_agent.orchestration.coordinator_support import (
    partial_attempt_exists as _partial_attempt_exists,
)
from hifi_agent.orchestration.coordinator_support import (
    pre_qc_exists as _pre_qc_exists,
)
from hifi_agent.orchestration.coordinator_support import (
    proposal_path as _proposal_path,
)
from hifi_agent.orchestration.coordinator_support import (
    required_attempt as _required_attempt,
)
from hifi_agent.orchestration.coordinator_support import (
    write_or_verify_json as _write_or_verify_json,
)
from hifi_agent.orchestration.coordinator_terminal import CoordinatorTerminal
from hifi_agent.orchestration.environment import (
    EnvironmentManifest,
    materialize_environment_manifest,
    require_environment_preflight,
    run_environment_preflight,
)
from hifi_agent.orchestration.identity import IdentityStore
from hifi_agent.orchestration.journal import StateStore
from hifi_agent.orchestration.lock import RunLock
from hifi_agent.orchestration.manifests import (
    AssemblyAttemptRecord,
    ManifestStore,
)
from hifi_agent.orchestration.retention import apply_retention
from hifi_agent.orchestration.runtime_config import (
    DecisionMode,
    EffectiveRuntimeConfig,
    RuntimeConfigResult,
    resolve_runtime_config,
)
from hifi_agent.orchestration.runtime_models import RunIdentity, RunPhase, RunState, sha256_file
from hifi_agent.schemas.assembly import (
    AssemblyConfig,
    RiskLevel,
    baseline_assembly_config,
)

__all__ = ["CoordinatorResult", "ProposalServiceFactory", "RunCoordinator"]


class RunCoordinator:
    """Own validation, execution, proposals, comparison, reporting, and recovery."""

    def __init__(
        self,
        config_path: Path,
        *,
        decision_mode_override: DecisionMode | None = None,
        confirm_medium_high_risk: bool = False,
        workflow_runner: AssemblyWorkflowRunner | None = None,
        pre_qc_runner: PreQcRunner = run_pre_qc_workflow,
        directive_provider: DirectiveProvider = build_rule_directive,
        proposal_service_factory: ProposalServiceFactory | None = None,
        llm_client: StructuredLLMClient | None = None,
        fault_injector: CoordinatorFaultInjector | None = None,
        estimate_provider: EstimateProvider | None = None,
    ) -> None:
        self.config_path = config_path.resolve()
        self.decision_mode_override = decision_mode_override
        self.confirm_medium_high_risk = confirm_medium_high_risk
        self.workflow_runner = workflow_runner or NextflowAssemblyRunner()
        self.pre_qc_runner = pre_qc_runner
        self.directive_provider = directive_provider
        self.proposal_service_factory = proposal_service_factory
        self.llm_client = llm_client
        self.fault_injector = fault_injector
        self.estimate_provider = estimate_provider

    def run(self, *, resume: bool = False) -> CoordinatorResult:
        """Advance or recover the single current control plane to a terminal report."""
        preview = resolve_runtime_config(
            self.config_path,
            decision_mode_override=self.decision_mode_override,
            write_outputs=False,
        )
        run_dir = preview.effective.sample.outdir.resolve()
        identity_store = IdentityStore(run_dir)
        effective_resume = resume or (
            preview.effective.sample.runtime.resume_mode == "auto"
            and identity_store.identity_path.is_file()
        )
        if effective_resume:
            if not identity_store.identity_path.is_file():
                raise AgentStateError("current resume requires an existing immutable identity")
            runtime, identity, state = self._resume(preview, identity_store)
        else:
            if (
                identity_store.identity_path.exists()
                or (run_dir / "05_agent/run_state.json").exists()
            ):
                raise AgentStateError("current run already exists; use --resume")
            runtime, identity, state = self._bootstrap()

        lock = RunLock(
            run_dir,
            run_uuid=identity.run_uuid,
            command=["hifi-agent", "assemble", str(self.config_path)],
        )
        lock.acquire(takeover_stale=effective_resume)
        try:
            try:
                result = self._advance(runtime, identity, state)
            except InterruptedExecutionError:
                raise
            except ToolExecutionError as exc:
                current = StateStore(run_dir).load()
                result = self._enter_reporting(
                    current,
                    outcome="FAILED_TOOL",
                    outcome_class="FAILED",
                    reason_codes=["TOOL_EXECUTION_FAILED"],
                    last_error=str(exc),
                )
            except RuleEvaluationError as exc:
                current = StateStore(run_dir).load()
                required = runtime.effective.optimization.require_llm
                result = self._enter_reporting(
                    current,
                    outcome=("FAILED_REQUIRED_LLM" if required else "STOP_INSUFFICIENT_EVIDENCE"),
                    outcome_class=("FAILED" if required else "SCIENTIFIC"),
                    reason_codes=[
                        "REQUIRED_DECISION_SERVICE_FAILED"
                        if required
                        else "OPTIONAL_DECISION_EVIDENCE_FAILED"
                    ],
                    last_error=str(exc),
                )
            except AgentStateError as exc:
                if "budget exhausted" not in str(exc).lower():
                    raise
                current = StateStore(run_dir).load()
                result = self._enter_reporting(
                    current,
                    outcome="STOP_BUDGET",
                    outcome_class="ACTION_REQUIRED",
                    reason_codes=["PRELAUNCH_BUDGET_EXHAUSTED"],
                    last_error=str(exc),
                )
            apply_retention(
                result.run_dir,
                policy=runtime.effective.sample.runtime.retention,
                state=result.state.state,
            )
            return result
        finally:
            lock.release()

    def _bootstrap(self) -> tuple[RuntimeConfigResult, RunIdentity, RunState]:
        runtime = resolve_runtime_config(
            self.config_path,
            decision_mode_override=self.decision_mode_override,
            write_outputs=True,
        )
        sample = runtime.effective.sample
        prepare_busco_lineage(sample)
        environment = run_environment_preflight(sample)
        require_environment_preflight(environment)
        environment_path = materialize_environment_manifest(
            environment,
            sample.outdir / "00_metadata/environment_manifest.json",
        )
        policy_path = sample.outdir / "04_decisions/comparison_policy_snapshot.yaml"
        rag_path = sample.outdir / "04_decisions/rag_index_snapshot.json"
        _exclusive_copy(COMPARISON_POLICY, policy_path)
        _exclusive_copy(KNOWLEDGE_INDEX, rag_path)
        identity = RunIdentity.create(
            sample_id=sample.sample_id,
            run_dir=sample.outdir,
            code_commit=_code_commit(),
            package_version=__version__,
            config=runtime.validation.resolved_config,
            effective_config=runtime.effective_config_path,
            input_manifest=runtime.validation.input_manifest,
            environment_manifest=environment_path,
            comparison_policy=policy_path,
            rag_index=rag_path,
            sample_config=runtime.validation.sample_config_snapshot,
            runtime_config=runtime.validation.runtime_config_snapshot,
        )
        IdentityStore(sample.outdir).initialize(identity)
        state = StateStore(sample.outdir).initialize(identity)
        BudgetLedger(sample.outdir).initialize(
            BudgetLimits.from_config(runtime.effective.execution_budget)
        )
        ManifestStore(sample.outdir).initialize_history()
        return runtime, identity, state

    def _resume(
        self,
        preview: RuntimeConfigResult,
        identity_store: IdentityStore,
    ) -> tuple[RuntimeConfigResult, RunIdentity, RunState]:
        identity = identity_store.verify_snapshots(write_drift_receipt=True)
        if (
            identity.sample_config_sha256 is not None
            and sha256_file(preview.validation.source_config) != identity.sample_config_sha256
        ):
            raise AgentStateError("Sample configuration differs from the immutable run snapshot")
        if identity.runtime_config_sha256 is not None:
            runtime_source = preview.validation.runtime_source_config
            if (
                runtime_source is None
                or sha256_file(runtime_source) != identity.runtime_config_sha256
            ):
                raise AgentStateError(
                    "Runtime configuration differs from the immutable run snapshot"
                )
        try:
            persisted = EffectiveRuntimeConfig.model_validate_json(
                preview.effective_config_path.read_text()
            )
        except (OSError, ValueError) as exc:
            raise AgentStateError(f"Persisted effective current config is invalid: {exc}") from exc
        if persisted != preview.effective:
            raise AgentStateError(
                "Resume config or CLI override differs from immutable current config"
            )
        verify_recorded_input_checksums(identity.run_dir / "00_metadata/input_checksums.tsv")
        state = StateStore(identity.run_dir).load()
        BudgetLedger(identity.run_dir).snapshot()
        ManifestStore(identity.run_dir).verify()
        return preview, identity, state

    def _advance(
        self,
        runtime: RuntimeConfigResult,
        identity: RunIdentity,
        state: RunState,
    ) -> CoordinatorResult:
        run_dir = identity.run_dir
        state_store = StateStore(run_dir)
        budget = BudgetLedger(run_dir)
        manifests = ManifestStore(run_dir)
        comparator = RoundComparator(run_dir / "04_decisions/comparison_policy_snapshot.yaml")
        inputs: AssemblyInputManifest | None = None
        executor: AssemblyExecutor | None = None

        while True:
            if state.state == RunPhase.TERMINAL:
                return self._terminal_result(state)
            if state.state in {RunPhase.REPORTING, RunPhase.VERIFYING}:
                return self._finish_reporting(state)
            if state.state == RunPhase.INITIALIZING:
                state = state_store.transition(
                    state,
                    RunPhase.INPUT_VALIDATION,
                    action="ACCEPT_VALIDATED_INPUT",
                    reason_codes=["INPUT_RECEIPT_VERIFIED"],
                )
                continue
            if state.state == RunPhase.INPUT_VALIDATION:
                state = state_store.transition(
                    state,
                    RunPhase.ENVIRONMENT_PREFLIGHT,
                    action="ACCEPT_ENVIRONMENT_PREFLIGHT",
                    reason_codes=["ENVIRONMENT_MANIFEST_BOUND"],
                )
                continue
            if state.state == RunPhase.ENVIRONMENT_PREFLIGHT:
                state = state_store.transition(
                    state,
                    RunPhase.PRE_QC,
                    action="START_PRE_QC",
                    reason_codes=["PRE_QC_START"],
                )
                continue
            if state.state == RunPhase.PRE_QC:
                self._fault("before_pre_qc", state)
                inputs = self.pre_qc_runner(
                    runtime.effective.sample,
                    resume=_pre_qc_exists(run_dir),
                )
                self._fault("after_pre_qc", state)
                state = state_store.transition(
                    state,
                    RunPhase.BASELINE_PLAN,
                    action="COMPLETE_PRE_QC",
                    reason_codes=["PRE_QC_INVENTORY_VERIFIED"],
                )
                continue
            inputs = inputs or assembly_inputs_from_run(run_dir)
            executor = executor or AssemblyExecutor(
                run_dir,
                sample=runtime.effective.sample,
                inputs=inputs,
                environment_manifest_sha256=identity.environment_manifest_sha256,
                budget=budget,
                manifests=manifests,
                runner=self.workflow_runner,
            )
            baseline_config = baseline_assembly_config(
                reads=runtime.effective.sample.hifi_reads,
                threads=runtime.effective.sample.resources.max_threads,
            )
            if state.state == RunPhase.BASELINE_PLAN:
                state = state_store.transition(
                    state,
                    RunPhase.BASELINE_ASSEMBLY,
                    action="APPROVE_BASELINE_CONFIG",
                    reason_codes=["BASELINE_FULL_CONFIG_APPROVED"],
                    updates={"active_attempt_id": "baseline.attempt_001"},
                )
                continue
            if state.state == RunPhase.BASELINE_ASSEMBLY:
                record = _latest_attempt(run_dir, AttemptCoordinate(round_index=0))
                if record is None:
                    self._fault("before_baseline_attempt", state)
                    record = executor.execute(
                        coordinate=AttemptCoordinate(round_index=0),
                        requested_config=baseline_config.model_dump(mode="json"),
                        approved_config=baseline_config,
                        resume=_partial_attempt_exists(
                            run_dir,
                            AttemptCoordinate(round_index=0),
                        ),
                        estimate=self._estimate(AttemptCoordinate(round_index=0), run_dir),
                    )
                    if record is None:
                        raise InterruptedExecutionError(
                            "Baseline attempt was interrupted; rerun with --resume"
                        )
                    self._fault("after_baseline_attempt", state)
                if not record.comparison_eligible:
                    outcome = (
                        "FAILED_PARAMETER_CONTRACT"
                        if record.status == "CONTRACT_VIOLATION"
                        else "FAILED_TOOL"
                    )
                    return self._enter_reporting(
                        state,
                        outcome=outcome,
                        outcome_class="FAILED",
                        reason_codes=list(record.ineligible_reason_codes),
                        last_error=record.error,
                    )
                executor.verify_completed_attempt(record)
                manifest_ref = _attempt_manifest_ref(run_dir, record)
                state = state_store.transition(
                    state,
                    RunPhase.BASELINE_POST_QC,
                    action="COMPLETE_BASELINE_ATTEMPT",
                    reason_codes=["BASELINE_ATTEMPT_COMPLETE"],
                    updates={
                        "baseline_run_ref": manifest_ref,
                        "incumbent_run_ref": manifest_ref,
                        "seen_parameter_fingerprints": [baseline_config.parameter_fingerprint()],
                        "active_attempt_id": None,
                    },
                )
                continue
            if state.state == RunPhase.BASELINE_POST_QC:
                baseline_record = _required_attempt(run_dir, state.baseline_run_ref)
                qc_path = run_dir / "04_decisions/round_00/qc_feature_bundle.json"
                _build_or_verify_qc(
                    qc_path,
                    run_dir,
                    baseline_record,
                    runtime.effective.sample,
                )
                state = state_store.transition(
                    state,
                    RunPhase.BASELINE_REVIEW,
                    action="BUILD_BASELINE_QC_FEATURES",
                    reason_codes=["BASELINE_REVIEW_READY"],
                    updates={"latest_decision_ref": qc_path.relative_to(run_dir)},
                )
                continue
            if state.state == RunPhase.BASELINE_REVIEW:
                state = self._rounds().review_baseline(
                    state,
                    runtime=runtime,
                    comparator=comparator,
                    manifests=manifests,
                )
                if state.state == RunPhase.REPORTING:
                    return self._finish_reporting(state)
                continue
            if state.state == RunPhase.ROUND_CONTEXT:
                context = self._rounds().round_context(state, runtime, identity, comparator, budget)
                context_path = (
                    run_dir
                    / "04_decisions"
                    / f"round_{state.round_index:02d}"
                    / "decision_context.json"
                )
                state = state_store.transition(
                    state,
                    RunPhase.RAG_RETRIEVAL,
                    action="FREEZE_ROUND_CONTEXT",
                    reason_codes=["CURRENT_INCUMBENT_CONTEXT_HASHED"],
                    updates={"latest_decision_ref": context_path.relative_to(run_dir)},
                )
                continue
            if state.state == RunPhase.RAG_RETRIEVAL:
                context = _load_context(run_dir, state.round_index)
                directive = self.directive_provider(context)
                provider = self._proposal_provider(run_dir, budget, runtime)
                self._fault("before_proposal", state)
                provider.propose_run(
                    context,
                    directive,
                    decision_mode=runtime.effective.optimization.decision_mode,
                    require_llm=runtime.effective.optimization.require_llm,
                    max_candidates=runtime.effective.optimization.max_candidates_per_round,
                    confirm_medium_high_risk=self.confirm_medium_high_risk,
                    client=self._configured_llm_client(runtime),
                )
                self._fault("after_proposal", state)
                state = state_store.transition(
                    state,
                    RunPhase.LLM_PROPOSAL,
                    action="COMPLETE_GOVERNED_RETRIEVAL",
                    reason_codes=["RAG_TRACE_FROZEN"],
                )
                continue
            if state.state == RunPhase.LLM_PROPOSAL:
                decision = _load_proposal_decision(run_dir, state.round_index)
                reason = (
                    "LLM_PROPOSAL_RECORDED"
                    if decision.llm_receipt.status != "NOT_CALLED"
                    else "LLM_PROPOSAL_EXPLICITLY_SKIPPED"
                )
                state = state_store.transition(
                    state,
                    RunPhase.SAFETY_REVIEW,
                    action="COMPLETE_PROPOSAL_PROVIDER",
                    reason_codes=[reason],
                )
                continue
            if state.state == RunPhase.SAFETY_REVIEW:
                decision = _load_proposal_decision(run_dir, state.round_index)
                seen = list(state.seen_parameter_fingerprints)
                for approved in decision.approved:
                    if approved.parameter_fingerprint not in seen:
                        seen.append(approved.parameter_fingerprint)
                if decision.approved:
                    state = state_store.transition(
                        state,
                        RunPhase.BUDGET_RESERVATION,
                        action="ACCEPT_SAFETY_APPROVED_CANDIDATES",
                        reason_codes=list(decision.reason_codes),
                        updates={
                            "candidate_index": 1,
                            "seen_parameter_fingerprints": seen,
                            "latest_decision_ref": _proposal_path(
                                run_dir, state.round_index
                            ).relative_to(run_dir),
                        },
                    )
                else:
                    state = state_store.transition(
                        state,
                        RunPhase.ROUND_COMPARISON,
                        action="NO_EXECUTABLE_CANDIDATE",
                        reason_codes=list(decision.reason_codes),
                        updates={
                            "candidate_index": None,
                            "seen_parameter_fingerprints": seen,
                            "latest_decision_ref": _proposal_path(
                                run_dir, state.round_index
                            ).relative_to(run_dir),
                        },
                    )
                continue
            if state.state == RunPhase.BUDGET_RESERVATION:
                decision = _load_proposal_decision(run_dir, state.round_index)
                candidate_index = state.candidate_index or 1
                approved = decision.approved[candidate_index - 1]
                attempt_id = (
                    f"round_{state.round_index:02d}_candidate_{candidate_index:02d}.attempt_001"
                )
                state = state_store.transition(
                    state,
                    RunPhase.CANDIDATE_ASSEMBLY,
                    action="RESERVE_CANDIDATE_LAUNCH",
                    reason_codes=["CANDIDATE_PRELAUNCH_BUDGET_CHECK"],
                    updates={"active_attempt_id": attempt_id},
                )
                del approved
                continue
            if state.state == RunPhase.CANDIDATE_ASSEMBLY:
                decision = _load_proposal_decision(run_dir, state.round_index)
                active_candidate_index = state.candidate_index
                if active_candidate_index is None or active_candidate_index > len(
                    decision.approved
                ):
                    raise AgentStateError(
                        "Candidate state does not match the approved proposal set"
                    )
                approved = decision.approved[active_candidate_index - 1]
                coordinate = AttemptCoordinate(
                    round_index=state.round_index,
                    candidate_index=active_candidate_index,
                )
                record = self._execute_candidate(
                    executor,
                    coordinate,
                    approved.full_config,
                    requested=cast(Mapping[str, object], approved.approved_diff),
                    max_retries=runtime.effective.execution_budget.max_tool_retries,
                    state=state,
                    run_dir=run_dir,
                )
                if record.status == "CONTRACT_VIOLATION":
                    return self._enter_reporting(
                        state,
                        outcome="FAILED_PARAMETER_CONTRACT",
                        outcome_class="FAILED",
                        reason_codes=list(record.ineligible_reason_codes),
                        last_error=record.error,
                    )
                state = state_store.transition(
                    state,
                    RunPhase.CANDIDATE_POST_QC,
                    action=(
                        "COMPLETE_CANDIDATE_ATTEMPT"
                        if record.comparison_eligible
                        else "FINALIZE_FAILED_CANDIDATE"
                    ),
                    reason_codes=(
                        ["CANDIDATE_ATTEMPT_COMPLETE"]
                        if record.comparison_eligible
                        else list(record.ineligible_reason_codes)
                    ),
                    updates={"active_attempt_id": None},
                )
                continue
            if state.state == RunPhase.CANDIDATE_POST_QC:
                decision = _load_proposal_decision(run_dir, state.round_index)
                post_qc_candidate_index = state.candidate_index
                if post_qc_candidate_index is None:
                    raise AgentStateError("Candidate post-QC state lacks candidate_index")
                record = _latest_attempt(
                    run_dir,
                    AttemptCoordinate(
                        round_index=state.round_index,
                        candidate_index=post_qc_candidate_index,
                    ),
                )
                if record is None:
                    raise AgentStateError("Candidate post-QC lacks a finalized attempt")
                if record.comparison_eligible:
                    qc_path = (
                        run_dir
                        / "04_decisions"
                        / f"round_{state.round_index:02d}"
                        / f"candidate_{post_qc_candidate_index:02d}"
                        / "qc_feature_bundle.json"
                    )
                    _build_or_verify_qc(
                        qc_path,
                        run_dir,
                        record,
                        runtime.effective.sample,
                    )
                if post_qc_candidate_index < len(decision.approved):
                    next_index = post_qc_candidate_index + 1
                    state = state_store.transition(
                        state,
                        RunPhase.CANDIDATE_ASSEMBLY,
                        action="RESERVE_NEXT_CANDIDATE_LAUNCH",
                        reason_codes=["NEXT_CANDIDATE_PRELAUNCH_BUDGET_CHECK"],
                        updates={
                            "candidate_index": next_index,
                            "active_attempt_id": (
                                f"round_{state.round_index:02d}_candidate_{next_index:02d}.attempt_001"
                            ),
                        },
                    )
                else:
                    state = state_store.transition(
                        state,
                        RunPhase.ROUND_COMPARISON,
                        action="COMPLETE_ROUND_CANDIDATE_SET",
                        reason_codes=["ALL_APPROVED_CANDIDATES_FINALIZED"],
                        updates={"candidate_index": None, "active_attempt_id": None},
                    )
                continue
            if state.state == RunPhase.ROUND_COMPARISON:
                state = self._rounds().compare_round(
                    state,
                    runtime=runtime,
                    comparator=comparator,
                    manifests=manifests,
                )
                if state.state == RunPhase.REPORTING:
                    return self._finish_reporting(state)
                continue
            if state.state == RunPhase.INCUMBENT_UPDATE:
                state = self._rounds().after_incumbent_update(state, runtime)
                if state.state == RunPhase.REPORTING:
                    return self._finish_reporting(state)
                continue
            raise AgentStateError(f"Unsupported current coordinator phase: {state.state.value}")

    def _proposal_provider(
        self,
        run_dir: Path,
        budget: BudgetLedger,
        runtime: RuntimeConfigResult,
    ) -> ProposalProvider:
        levels = {
            cast(RiskLevel, item)
            for item in runtime.effective.optimization_policy().confirmation_risk_levels
        }
        if self.proposal_service_factory is not None:
            return self.proposal_service_factory(run_dir, budget, levels)
        environment = EnvironmentManifest.model_validate_json(
            (run_dir / "00_metadata/environment_manifest.json").read_text()
        )
        hifiasm = next(item for item in environment.tools if item.name == "hifiasm")
        version = hifiasm.version or "UNKNOWN"
        return ProposalService(
            run_dir,
            budget=budget,
            retriever=LocalGovernedRetriever(
                run_dir / "04_decisions/rag_index_snapshot.json",
                actual_hifiasm_version=version,
            ),
            confirmation_risk_levels=levels,
        )

    def _configured_llm_client(
        self,
        runtime: RuntimeConfigResult,
    ) -> StructuredLLMClient | None:
        """Select an injected client, an immutable recorded replay, or the live default."""
        if self.llm_client is not None:
            return self.llm_client
        transcript = runtime.effective.optimization.llm_replay_transcript
        return RecordedLLMClient(transcript) if transcript is not None else None

    def _execute_candidate(
        self,
        executor: AssemblyExecutor,
        coordinate: AttemptCoordinate,
        config: AssemblyConfig,
        *,
        requested: Mapping[str, object],
        max_retries: int,
        state: RunState,
        run_dir: Path,
    ) -> AssemblyAttemptRecord:
        record = _latest_attempt(run_dir, coordinate)
        while True:
            if record is not None and record.comparison_eligible:
                executor.verify_completed_attempt(record)
                return record
            if record is not None and record.status == "CONTRACT_VIOLATION":
                return record
            retry = record is not None
            if record is not None and record.attempt_index - 1 >= max_retries:
                return record
            partial = record is None and _partial_attempt_exists(run_dir, coordinate)
            self._fault("before_candidate_attempt", state)
            result = executor.execute(
                coordinate=coordinate,
                requested_config=requested,
                approved_config=config,
                resume=partial,
                retry=retry,
                estimate=self._estimate(coordinate, run_dir),
            )
            if result is None:
                raise InterruptedExecutionError(
                    f"{coordinate.logical_run_id} interrupted; rerun with --resume"
                )
            record = result
            self._fault("after_candidate_attempt", state)

    def _transition_to_reporting(
        self,
        state: RunState,
        *,
        outcome: str,
        outcome_class: str,
        reason_codes: list[str],
        last_error: str | None = None,
        updates: dict[str, object] | None = None,
    ) -> RunState:
        payload = {
            "terminal_outcome": outcome,
            "outcome_class": outcome_class,
            "terminal_reason_codes": reason_codes,
            "last_error": last_error,
            "candidate_index": None,
            "active_attempt_id": None,
            **(updates or {}),
        }
        return StateStore(state.identity.run_dir).transition(
            state,
            RunPhase.REPORTING,
            action="ENTER_TERMINAL_REPORTING",
            reason_codes=reason_codes,
            updates=payload,
        )

    def _enter_reporting(
        self,
        state: RunState,
        *,
        outcome: str,
        outcome_class: str,
        reason_codes: list[str],
        last_error: str | None = None,
    ) -> CoordinatorResult:
        if state.state not in {RunPhase.REPORTING, RunPhase.VERIFYING, RunPhase.TERMINAL}:
            updates: dict[str, object] | None = None
            proposal_path = _proposal_path(state.identity.run_dir, state.round_index)
            round_manifest_path = (
                state.identity.run_dir
                / "04_decisions"
                / f"round_{state.round_index:02d}"
                / "round_manifest.json"
            )
            if (
                state.round_index > 0
                and proposal_path.is_file()
                and not round_manifest_path.exists()
            ):
                decision = _load_proposal_decision(state.identity.run_dir, state.round_index)
                stop_path = round_manifest_path.parent / "terminal_stop.json"
                _write_or_verify_json(
                    stop_path,
                    {
                        "schema_id": "hifi-agent",
                        "terminal_outcome": outcome,
                        "outcome_class": outcome_class,
                        "reason_codes": reason_codes,
                    },
                )
                round_path = self._rounds().round_manifest(
                    state,
                    decision,
                    manifests=ManifestStore(state.identity.run_dir),
                    comparison_path=stop_path,
                    incumbent_after=cast(Path, state.incumbent_run_ref),
                    round_outcome=outcome,
                    reasons=reason_codes,
                )
                updates = {
                    "completed_round_refs": _append_unique(
                        state.completed_round_refs,
                        round_path.relative_to(state.identity.run_dir),
                    )
                }
            state = self._transition_to_reporting(
                state,
                outcome=outcome,
                outcome_class=outcome_class,
                reason_codes=reason_codes,
                last_error=last_error,
                updates=updates,
            )
        return self._finish_reporting(state)

    def _finish_reporting(self, state: RunState) -> CoordinatorResult:
        return CoordinatorTerminal(self._fault).finish(state)

    def _rounds(self) -> CoordinatorRounds:
        return CoordinatorRounds(
            transition_to_reporting=self._transition_to_reporting,
            fault=self._fault,
        )

    def _terminal_result(self, state: RunState) -> CoordinatorResult:
        return CoordinatorTerminal(self._fault).result(state)

    def _estimate(self, coordinate: AttemptCoordinate, run_dir: Path) -> ExecutionEstimate:
        if self.estimate_provider is not None:
            return self.estimate_provider(coordinate)
        free_gib = shutil.disk_usage(run_dir).free / (1024**3)
        return ExecutionEstimate(observed_free_gib=free_gib)

    def _fault(self, hook: str, state: RunState) -> None:
        if self.fault_injector is not None:
            self.fault_injector(hook, state)
