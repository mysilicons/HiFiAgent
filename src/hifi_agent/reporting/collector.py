"""Fault-tolerant collection of Stage 1-10 artifacts for final reporting."""

from __future__ import annotations

import csv
import hashlib
import json
import platform
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import ValidationError

from hifi_agent.agent.models import AgentRunState, AssemblyParameters
from hifi_agent.optimization.models import OptimizationResult
from hifi_agent.rag.models import ExplanationBundle
from hifi_agent.reporting.models import (
    AssemblyRunRecord,
    FinalReportData,
    InputRecord,
    MetricRecord,
    ModuleRecord,
    ParameterChange,
    ProvenanceRecord,
    ReportStatus,
    SoftwareRecord,
    SyntheticReportScenario,
)
from hifi_agent.rules.models import RuleDecision
from hifi_agent.schemas.metrics import AssemblyMetrics
from hifi_agent.schemas.sample import SampleConfig

ASSEMBLY_METRICS = {
    "assembly_size": ("Assembly size", "bp"),
    "assembly_size_ratio": ("Assembly size ratio", "ratio"),
    "contig_count": ("Contig count", "count"),
    "contig_n50": ("Contig N50", "bp"),
    "longest_contig": ("Longest contig", "bp"),
    "busco_complete": ("BUSCO complete", "%"),
    "busco_single": ("BUSCO single-copy", "%"),
    "busco_duplicated": ("BUSCO duplicated", "%"),
    "busco_fragmented": ("BUSCO fragmented", "%"),
    "busco_missing": ("BUSCO missing", "%"),
    "kmer_qv": ("k-mer QV", "QV"),
    "kmer_completeness": ("k-mer completeness", "%"),
    "mapped_read_fraction": ("Mapped read fraction", "fraction"),
    "coverage_cv": ("Coverage CV", "CV"),
    "quast_misassemblies": ("QUAST misassemblies", "count"),
}
PRE_QC_METRICS = {
    "read_count": ("Read count", "count"),
    "total_bases": ("Total bases", "bp"),
    "mean_read_length": ("Mean read length", "bp"),
    "read_n50": ("Read N50", "bp"),
    "mean_qscore": ("Mean Q score", "Q"),
    "gc_percent": ("GC", "%"),
    "estimated_genome_size": ("Estimated genome size", "bp"),
    "estimated_coverage": ("Estimated coverage", "x"),
    "kmer_peak_depth": ("k-mer peak depth", "x"),
    "kmer_source": ("k-mer source", None),
}
FILTER_METRICS = {
    "input_read_count": ("Input reads", "count"),
    "retained_read_count": ("Retained reads", "count"),
    "retained_read_fraction": ("Retained read fraction", "fraction"),
    "filtered_short_read_count": ("Short reads filtered", "count"),
    "filtered_low_quality_read_count": ("Low-quality reads filtered", "count"),
    "min_read_length": ("Minimum retained length", "bp"),
    "min_mean_qscore": ("Minimum retained mean Q", "Q"),
}


class ReportCollector:
    """Collect available artifacts without hiding failures or inventing missing values."""

    def __init__(self, run_dir: Path, *, redact_paths: bool = True) -> None:
        self.run_dir = run_dir.resolve()
        self.redact_paths = redact_paths
        self.modules: list[ModuleRecord] = []
        self.provenance: list[ProvenanceRecord] = []
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.limitations: list[str] = []

    def collect(
        self,
        *,
        scenario: SyntheticReportScenario | None = None,
        scenario_source: Path | None = None,
        figures: list[str] | None = None,
        generated_at: datetime | None = None,
    ) -> FinalReportData:
        """Return a complete report model from all readable run artifacts."""
        config = self._load_config()
        sample_id = config.sample_id if config is not None else self.run_dir.name
        inputs = self._load_inputs()
        raw = self._load_json(
            "pre_qc",
            self.run_dir / "01_pre_qc" / "raw_metrics.json",
            required=True,
        )
        pre_qc = self._metric_records(
            raw or {},
            PRE_QC_METRICS,
            self.run_dir / "01_pre_qc" / "raw_metrics.json",
        )
        if raw is not None:
            self.modules.append(
                ModuleRecord(
                    module="pre_qc",
                    status="SUCCESS" if raw.get("input_status") == "PASS" else "WARNING",
                    source_file=self._display_path(self.run_dir / "01_pre_qc" / "raw_metrics.json"),
                    message=f"Pre-QC input status: {raw.get('input_status', 'unknown')}",
                )
            )
            self.warnings.extend(_string_list(raw.get("warnings")))
        mapping = self._load_json(
            "mapping",
            self.run_dir / "03_post_qc" / "baseline" / "mapping" / "mapping_metrics.json",
            required=False,
        )
        filtering = self._metric_records(
            mapping.get("filter", {}) if mapping else {},
            FILTER_METRICS,
            self.run_dir / "03_post_qc" / "baseline" / "mapping" / "mapping_metrics.json",
            pointer_prefix="/filter",
        )
        manifest = self._load_json(
            "baseline_assembly",
            self.run_dir / "02_assembly" / "baseline" / "metadata" / "assembly_manifest.json",
            required=True,
        )
        if manifest is not None:
            self.modules.append(
                ModuleRecord(
                    module="baseline_assembly",
                    status="SUCCESS",
                    source_file=self._display_path(
                        self.run_dir / "02_assembly/baseline/metadata/assembly_manifest.json"
                    ),
                    message="Baseline hifiasm manifest is available.",
                )
            )
        assembly_metrics = self._load_assembly_metrics(
            self.run_dir / "03_post_qc" / "baseline" / "assembly_metrics.json",
            required=True,
        )
        state = self._load_agent_state()
        optimization = self._load_optimization_result()
        baseline_parameters = (
            optimization.baseline_config.parameters.model_dump()
            if optimization is not None
            else state.baseline_config.parameters.model_dump()
            if state is not None and state.baseline_config is not None
            else AssemblyParameters().model_dump()
        )
        assembly_runs: list[AssemblyRunRecord] = []
        if assembly_metrics is not None:
            assembly_runs.append(
                self._assembly_record(
                    assembly_metrics,
                    kind="baseline",
                    parameters=baseline_parameters,
                    source=self.run_dir / "03_post_qc" / "baseline" / "assembly_metrics.json",
                    result="OBSERVED_BASELINE",
                )
            )
            self.limitations.extend(assembly_metrics.metric_limitations)
            if assembly_metrics.tool_failures:
                self.errors.extend(assembly_metrics.tool_failures)
        if optimization is not None and optimization.synthetic:
            assembly_runs.append(self._optimization_baseline_record(optimization))
        actual_candidates = self._load_actual_candidates(baseline_parameters)
        if optimization is not None:
            actual_candidates = self._merge_optimization_candidates(
                actual_candidates,
                optimization,
            )
        assembly_runs.extend(actual_candidates)
        parameter_changes = self._parameter_changes(
            baseline_parameters,
            actual_candidates,
            scenario=None,
            optimization=optimization,
        )
        if scenario is not None:
            synthetic_source = scenario_source or Path("synthetic_scenario")
            if scenario_source is not None:
                self._record_artifact(
                    "synthetic_scenario",
                    "explicitly synthetic report acceptance scenario",
                    scenario_source,
                )
            synthetic_record = self._synthetic_record(scenario, synthetic_source)
            assembly_runs.append(synthetic_record)
            parameter_changes.extend(
                self._parameter_changes(
                    baseline_parameters,
                    [synthetic_record],
                    scenario=scenario,
                    optimization=None,
                )
            )
            self.warnings.append(scenario.disclaimer)
            self.limitations.extend(scenario.candidate.metrics.metric_limitations)
            self.modules.append(
                ModuleRecord(
                    module="synthetic_anomaly",
                    status="WARNING",
                    source_file=self._display_path(synthetic_source),
                    message="Report-only anomaly included and explicitly labeled synthetic.",
                    limitations=["NOT_A_REAL_WORKFLOW_RESULT"],
                )
            )
        if len(assembly_runs) == 1:
            self.modules.append(
                ModuleRecord(
                    module="candidate_assemblies",
                    status="NOT_RUN",
                    message="No candidate assembly was executed.",
                )
            )
        rule_decision = self._load_rule_decision()
        explanation = self._load_explanation()
        tool_documents = self._load_tool_modules()
        software = self._software_versions(manifest, assembly_metrics, tool_documents)
        final_selection, final_reason = self._final_selection(state, scenario, optimization)
        commands = self._reproducible_commands(config, manifest)
        sample_config = self._sanitize(config.model_dump(mode="json")) if config is not None else {}
        status = self._report_status()
        return FinalReportData(
            generated_at=generated_at or datetime.now(UTC),
            report_status=status,
            sample_id=sample_id,
            run_dir=self._display_path(self.run_dir),
            paths_redacted=self.redact_paths,
            scenario_id=(
                scenario.scenario_id
                if scenario
                else optimization.scenario_id
                if optimization
                else None
            ),
            scenario_disclaimer=(
                scenario.disclaimer
                if scenario
                else optimization.scenario_disclaimer
                if optimization
                else None
            ),
            sample_config=sample_config,
            inputs=inputs,
            pre_qc_metrics=pre_qc,
            filtering_metrics=filtering,
            software_versions=software,
            assembly_runs=assembly_runs,
            parameter_changes=parameter_changes,
            rule_facts=(rule_decision.model_dump(mode="json") if rule_decision else {}),
            agent_summary=(self._sanitize(state.model_dump(mode="json")) if state else {}),
            optimization_summary=(
                self._sanitize(optimization.model_dump(mode="json")) if optimization else {}
            ),
            rag_explanation=self._explanation_summary(explanation),
            final_selection=final_selection,
            final_selection_reason=final_reason,
            warnings=_deduplicate(self.warnings),
            limitations=_deduplicate(self.limitations),
            errors=_deduplicate(self.errors),
            modules=self.modules,
            provenance=self.provenance,
            figures=figures or [],
            reproducible_commands=commands,
        )

    def _load_config(self) -> SampleConfig | None:
        path = self.run_dir / "00_metadata" / "resolved_config.yaml"
        self._record_artifact("resolved_config", "sample configuration", path)
        if not path.is_file():
            self._module_failure("input_validation", path, "Resolved configuration is missing.")
            return None
        try:
            data = yaml.safe_load(path.read_text())
            config = SampleConfig.model_validate(data)
        except (OSError, yaml.YAMLError, ValidationError) as exc:
            self._module_failure(
                "input_validation", path, f"Resolved configuration is invalid: {exc}"
            )
            return None
        receipt = self._load_json(
            "input_validation_receipt",
            self.run_dir / "00_metadata" / "validation_receipt.json",
            required=False,
        )
        receipt_passed = receipt is not None and receipt.get("status") == "PASS"
        self.modules.append(
            ModuleRecord(
                module="input_validation",
                status="SUCCESS" if receipt_passed else "WARNING",
                source_file=self._display_path(path),
                message=(
                    "Validated configuration and PASS receipt available."
                    if receipt_passed
                    else "Configuration available but PASS validation receipt was not confirmed."
                ),
            )
        )
        return config

    def _load_inputs(self) -> list[InputRecord]:
        path = self.run_dir / "00_metadata" / "input_checksums.tsv"
        self._record_artifact("input_checksums", "input provenance", path)
        if not path.is_file():
            self.errors.append(f"Missing input checksum manifest: {self._display_path(path)}")
            return []
        records: list[InputRecord] = []
        try:
            with path.open(newline="") as handle:
                for row in csv.DictReader(handle, delimiter="\t"):
                    records.append(
                        InputRecord(
                            role=row["role"],
                            path=self._display_path(Path(row["path"])),
                            sha256=row["sha256"],
                            byte_size=int(row["bytes"]),
                        )
                    )
        except (OSError, KeyError, ValueError) as exc:
            self.errors.append(f"Invalid input checksum manifest: {exc}")
        return records

    def _load_json(self, module: str, path: Path, *, required: bool) -> dict[str, Any] | None:
        self._record_artifact(module, module.replace("_", " "), path)
        if not path.is_file():
            if required:
                self._module_failure(module, path, f"Required artifact is missing: {path.name}")
            return None
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            self._module_failure(module, path, f"Artifact is invalid JSON: {exc}")
            self._mark_invalid(module)
            return None
        if not isinstance(data, dict):
            self._module_failure(module, path, "Artifact must contain a JSON object.")
            self._mark_invalid(module)
            return None
        return data

    def _load_assembly_metrics(self, path: Path, *, required: bool) -> AssemblyMetrics | None:
        data = self._load_json("post_qc_aggregate", path, required=required)
        if data is None:
            return None
        try:
            metrics = AssemblyMetrics.model_validate(data)
        except ValidationError as exc:
            self._module_failure("post_qc_aggregate", path, f"Assembly metrics are invalid: {exc}")
            return None
        self.modules.append(
            ModuleRecord(
                module="post_qc_aggregate",
                status="WARNING" if metrics.tool_failures else "SUCCESS",
                source_file=self._display_path(path),
                message="Normalized assembly metrics available.",
                limitations=metrics.metric_limitations,
            )
        )
        return metrics

    def _load_agent_state(self) -> AgentRunState | None:
        path = self.run_dir / "05_agent" / "agent_state.json"
        data = self._load_json("agent", path, required=False)
        if data is None:
            self.modules.append(
                ModuleRecord(
                    module="agent",
                    status="NOT_RUN",
                    message="Agent state is unavailable.",
                )
            )
            return None
        try:
            state = AgentRunState.model_validate(data)
        except ValidationError as exc:
            self._module_failure("agent", path, f"Agent state is invalid: {exc}")
            return None
        self.modules.append(
            ModuleRecord(
                module="agent",
                status="SUCCESS",
                source_file=self._display_path(path),
                message=f"Agent terminal outcome: {state.terminal_outcome}",
            )
        )
        if state.terminal_outcome and state.terminal_outcome != "ACCEPTED":
            self.warnings.append(f"Agent terminated with {state.terminal_outcome}.")
        return state

    def _load_optimization_result(self) -> OptimizationResult | None:
        path = self.run_dir / "05_agent/optimization/optimization_result.json"
        data = self._load_json("stage11_optimization", path, required=False)
        if data is None:
            self.modules.append(
                ModuleRecord(
                    module="stage11_optimization",
                    status="NOT_RUN",
                    message="Stage 11 bounded optimization result is unavailable.",
                )
            )
            return None
        try:
            result = OptimizationResult.model_validate(data)
        except ValidationError as exc:
            self._module_failure(
                "stage11_optimization", path, f"Optimization result is invalid: {exc}"
            )
            return None
        successful = result.outcome in {"ACCEPTED_CANDIDATE", "BASELINE_RETAINED"}
        self.modules.append(
            ModuleRecord(
                module="stage11_optimization",
                status="SUCCESS" if successful else "WARNING",
                source_file=self._display_path(path),
                message=f"Stage 11 outcome: {result.outcome}",
                limitations=(
                    ["SYNTHETIC_OPTIMIZATION_NOT_A_WORKFLOW_RESULT"] if result.synthetic else []
                ),
            )
        )
        if result.synthetic and result.scenario_disclaimer:
            self.warnings.append(result.scenario_disclaimer)
        if not successful:
            self.warnings.append(f"Stage 11 terminated with {result.outcome}.")
        return result

    def _load_rule_decision(self) -> RuleDecision | None:
        path = self.run_dir / "04_decisions" / "baseline" / "rule_decision.json"
        data = self._load_json("rule_decision", path, required=True)
        if data is None:
            return None
        try:
            decision = RuleDecision.model_validate(data)
        except ValidationError as exc:
            self._module_failure("rule_decision", path, f"Rule decision is invalid: {exc}")
            return None
        self.modules.append(
            ModuleRecord(
                module="rule_decision",
                status="SUCCESS",
                source_file=self._display_path(path),
                message=f"Deterministic decision: {decision.decision} / {decision.action}",
            )
        )
        return decision

    def _load_explanation(self) -> ExplanationBundle | None:
        path = self.run_dir / "04_decisions" / "baseline" / "explanation.json"
        data = self._load_json("rag_llm", path, required=False)
        if data is None:
            self.modules.append(
                ModuleRecord(
                    module="rag_llm",
                    status="NOT_RUN",
                    message="Optional RAG/LLM explanation is unavailable.",
                )
            )
            return None
        try:
            explanation = ExplanationBundle.model_validate(data)
        except ValidationError as exc:
            self._module_failure("rag_llm", path, f"Explanation artifact is invalid: {exc}")
            return None
        self.modules.append(
            ModuleRecord(
                module="rag_llm",
                status="SUCCESS" if explanation.llm_status == "SUCCESS" else "WARNING",
                source_file=self._display_path(path),
                message=f"RAG/LLM status: {explanation.llm_status}",
            )
        )
        self.limitations.extend(explanation.explanation.uncertainties)
        return explanation

    def _load_tool_modules(self) -> dict[str, dict[str, Any]]:
        paths = {
            "quast": self.run_dir / "03_post_qc" / "baseline" / "quast" / "quast_metrics.json",
            "busco": self.run_dir / "03_post_qc" / "baseline" / "busco" / "busco_metrics.json",
            "merqury": self.run_dir
            / "03_post_qc"
            / "baseline"
            / "merqury"
            / "merqury_metrics.json",
            "mapping": self.run_dir
            / "03_post_qc"
            / "baseline"
            / "mapping"
            / "mapping_metrics.json",
        }
        documents: dict[str, dict[str, Any]] = {}
        for module, path in paths.items():
            data = self._load_json(module, path, required=False)
            if data is None:
                self.modules.append(
                    ModuleRecord(
                        module=module,
                        status="NOT_RUN",
                        message=f"{module} output is unavailable.",
                    )
                )
                continue
            status: ReportStatus = "SUCCESS" if data.get("status") == "success" else "FAILED"
            limitations = _string_list(data.get("limitations"))
            self.limitations.extend(limitations)
            self.modules.append(
                ModuleRecord(
                    module=module,
                    status=status,
                    source_file=self._display_path(path),
                    message=f"{module} status: {data.get('status', 'unknown')}",
                    limitations=limitations,
                )
            )
            if status == "FAILED":
                self.errors.append(f"{module} reported failure.")
            documents[module] = data
        return documents

    def _assembly_record(
        self,
        metrics: AssemblyMetrics,
        *,
        kind: Literal["baseline", "candidate", "synthetic_candidate"],
        parameters: dict[str, Any],
        source: Path,
        result: str,
    ) -> AssemblyRunRecord:
        return AssemblyRunRecord(
            run_id=metrics.run_id,
            kind=kind,
            status="WARNING" if metrics.tool_failures else "SUCCESS",
            parameters=parameters,
            metrics=self._metric_records(
                metrics.model_dump(),
                ASSEMBLY_METRICS,
                source,
            ),
            risk_level="low",
            result=result,
            synthetic=kind == "synthetic_candidate",
        )

    def _optimization_baseline_record(
        self,
        optimization: OptimizationResult,
    ) -> AssemblyRunRecord:
        metrics = optimization.baseline_metrics
        return AssemblyRunRecord(
            run_id="stage11_synthetic_baseline",
            kind="synthetic_baseline",
            status="WARNING",
            parameters=optimization.baseline_config.parameters.model_dump(),
            metrics=self._metric_records(
                metrics.model_dump(),
                ASSEMBLY_METRICS,
                Path(optimization.baseline_metrics_source),
                synthetic=True,
            ),
            reason_codes=["SYNTHETIC_STAGE11_TRIGGER_BASELINE"],
            risk_level="medium_high",
            result="SYNTHETIC_TRIGGER_NOT_A_WORKFLOW_RESULT",
            synthetic=True,
        )

    def _load_actual_candidates(
        self, baseline_parameters: dict[str, Any]
    ) -> list[AssemblyRunRecord]:
        records: list[AssemblyRunRecord] = []
        pattern = self.run_dir / "03_post_qc"
        for path in sorted(pattern.glob("candidate*/assembly_metrics.json")):
            metrics = self._load_assembly_metrics(path, required=False)
            if metrics is None:
                continue
            records.append(
                self._assembly_record(
                    metrics,
                    kind="candidate",
                    parameters=baseline_parameters,
                    source=path,
                    result="CANDIDATE_RESULT_AVAILABLE",
                )
            )
        return records

    def _merge_optimization_candidates(
        self,
        records: list[AssemblyRunRecord],
        optimization: OptimizationResult,
    ) -> list[AssemblyRunRecord]:
        by_run_id = {record.run_id: record for record in records}
        for assessment in optimization.candidates:
            if assessment.metrics is None:
                continue
            existing = by_run_id.get(assessment.run_id)
            if existing is not None:
                existing.parameters = assessment.config.parameters.model_dump()
                existing.reason_codes = assessment.config.reason_codes
                existing.risk_level = assessment.config.risk_level
                existing.result = assessment.status
                continue
            kind: Literal["candidate", "synthetic_candidate"] = (
                "synthetic_candidate" if assessment.synthetic else "candidate"
            )
            record = AssemblyRunRecord(
                run_id=assessment.run_id,
                kind=kind,
                status="SUCCESS" if assessment.status == "ACCEPTED" else "WARNING",
                parameters=assessment.config.parameters.model_dump(),
                metrics=self._metric_records(
                    assessment.metrics.model_dump(),
                    ASSEMBLY_METRICS,
                    Path(assessment.metrics_source),
                    synthetic=assessment.synthetic,
                ),
                reason_codes=assessment.config.reason_codes,
                risk_level=assessment.config.risk_level,
                result=assessment.status,
                synthetic=assessment.synthetic,
            )
            records.append(record)
            by_run_id[record.run_id] = record
        return records

    def _synthetic_record(
        self,
        scenario: SyntheticReportScenario,
        source: Path,
    ) -> AssemblyRunRecord:
        transformations = {
            item.metric: f"{item.operation}: {item.source_value} -> {item.synthetic_value}"
            for item in scenario.transformations
        }
        metrics = scenario.candidate.metrics
        records = self._metric_records(
            metrics.model_dump(),
            ASSEMBLY_METRICS,
            source,
            synthetic=True,
            transformations=transformations,
        )
        return AssemblyRunRecord(
            run_id=scenario.candidate.run_id,
            kind="synthetic_candidate",
            status="WARNING",
            parameters=scenario.candidate.parameters.model_dump(),
            metrics=records,
            reason_codes=scenario.candidate.reason_codes,
            risk_level=scenario.candidate.risk_level,
            result=scenario.candidate.result,
            synthetic=True,
        )

    def _parameter_changes(
        self,
        baseline: dict[str, Any],
        candidates: list[AssemblyRunRecord],
        *,
        scenario: SyntheticReportScenario | None,
        optimization: OptimizationResult | None,
    ) -> list[ParameterChange]:
        changes: list[ParameterChange] = []
        for candidate in candidates:
            for parameter, value in candidate.parameters.items():
                if baseline.get(parameter) == value:
                    continue
                evidence = (
                    scenario.candidate.evidence
                    if scenario and candidate.synthetic
                    else _optimization_evidence(optimization)
                )
                changes.append(
                    ParameterChange(
                        run_id=candidate.run_id,
                        parameter=parameter,
                        baseline_value=baseline.get(parameter),
                        candidate_value=value,
                        reason_codes=candidate.reason_codes or ["CANDIDATE_CONFIGURATION"],
                        evidence=evidence,
                        risk_level=candidate.risk_level,
                        result=candidate.result,
                        synthetic=candidate.synthetic,
                    )
                )
        return changes

    def _metric_records(
        self,
        values: dict[str, Any],
        definitions: Mapping[str, tuple[str, str | None]],
        source: Path,
        *,
        pointer_prefix: str = "",
        synthetic: bool = False,
        transformations: dict[str, str] | None = None,
    ) -> dict[str, MetricRecord]:
        return {
            metric: MetricRecord(
                metric=metric,
                label=label,
                value=_scalar(values.get(metric)),
                unit=unit,
                source_file=self._display_path(source),
                json_pointer=f"{pointer_prefix}/{metric}",
                synthetic=synthetic,
                transformation=(transformations or {}).get(metric),
            )
            for metric, (label, unit) in definitions.items()
        }

    def _software_versions(
        self,
        manifest: dict[str, Any] | None,
        metrics: AssemblyMetrics | None,
        tools: dict[str, dict[str, Any]],
    ) -> list[SoftwareRecord]:
        records = [
            SoftwareRecord(
                tool="python",
                version=platform.python_version(),
                source_file="report_runtime",
            ),
            SoftwareRecord(
                tool="report_platform",
                version=f"{platform.system()} {platform.release()} ({platform.machine()})",
                source_file="report_runtime",
            ),
        ]
        if manifest is not None:
            records.append(
                SoftwareRecord(
                    tool="hifiasm",
                    version=_optional_string(manifest.get("hifiasm_version")),
                    source_file=self._display_path(
                        self.run_dir / "02_assembly/baseline/metadata/assembly_manifest.json"
                    ),
                )
            )
        if metrics is not None:
            for tool, version in sorted(metrics.tool_versions.items()):
                records.append(
                    SoftwareRecord(
                        tool=tool,
                        version=version,
                        source_file=self._display_path(
                            self.run_dir / "03_post_qc/baseline/assembly_metrics.json"
                        ),
                    )
                )
        for tool, data in sorted(tools.items()):
            version = data.get("version")
            if isinstance(version, str):
                records.append(
                    SoftwareRecord(
                        tool=tool,
                        version=version,
                        source_file=self._display_path(
                            self.run_dir / f"03_post_qc/baseline/{tool}/{tool}_metrics.json"
                        ),
                    )
                )
        return _deduplicate_software(records)

    def _reproducible_commands(
        self,
        config: SampleConfig | None,
        manifest: dict[str, Any] | None,
    ) -> list[str]:
        config_path = self._display_path(self.run_dir / "00_metadata/resolved_config.yaml")
        commands = [
            f"hifi-agent validate {config_path}",
            f"hifi-agent run {config_path} --resume",
            f"hifi-agent decide {self._display_path(self.run_dir)}",
            f"hifi-agent agent {self._display_path(self.run_dir)} --resume",
            f"hifi-agent optimize {self._display_path(self.run_dir)}",
            "hifi-agent rag-index",
            f"hifi-agent explain {self._display_path(self.run_dir)} --llm",
            f"hifi-agent report {self._display_path(self.run_dir)}",
        ]
        command = manifest.get("command") if manifest else None
        if isinstance(command, str) and command:
            commands.insert(2, self._redact_command(command, config))
        return commands

    def _final_selection(
        self,
        state: AgentRunState | None,
        scenario: SyntheticReportScenario | None,
        optimization: OptimizationResult | None,
    ) -> tuple[str, str]:
        if scenario is not None:
            return (
                "NO_AUTOMATIC_SELECTION",
                "Synthetic candidate rejected for multi-metric quality regression; original "
                "STOP_UNCERTAIN outcome remains authoritative.",
            )
        if optimization is not None:
            return (
                optimization.selected_run_id or "NONE",
                f"Stage 11 outcome {optimization.outcome}: {optimization.selection_reason}",
            )
        if state is None:
            return "UNKNOWN", "Agent state is unavailable; no final selection can be claimed."
        if state.terminal_outcome == "ACCEPTED":
            return "baseline", "Agent accepted the deterministic baseline."
        return (
            "NONE",
            f"Agent terminal outcome {state.terminal_outcome}; "
            "no assembly was automatically selected.",
        )

    def _explanation_summary(self, explanation: ExplanationBundle | None) -> dict[str, object]:
        if explanation is None:
            return {}
        return {
            "llm_enabled": explanation.llm_enabled,
            "llm_status": explanation.llm_status,
            "provider": explanation.provider,
            "model": explanation.model,
            "recommended_action": explanation.explanation.recommended_action,
            "explanation": explanation.explanation.explanation,
            "uncertainties": explanation.explanation.uncertainties,
            "confidence": explanation.explanation.confidence,
            "source_ids": explanation.explanation.source_ids,
            "safety_checks": explanation.safety_checks,
        }

    def _report_status(self) -> ReportStatus:
        critical = {"input_validation", "pre_qc", "baseline_assembly", "post_qc_aggregate"}
        if self.errors or any(
            module.status == "FAILED" and module.module in critical for module in self.modules
        ):
            return "FAILED"
        if (
            self.warnings
            or self.limitations
            or any(module.status in {"WARNING", "NOT_RUN"} for module in self.modules)
        ):
            return "WARNING"
        return "SUCCESS"

    def _record_artifact(self, artifact_id: str, role: str, path: Path) -> None:
        display_path = self._display_path(path)
        if any(
            record.artifact_id == artifact_id and record.path == display_path
            for record in self.provenance
        ):
            return
        status: Literal["AVAILABLE", "MISSING", "INVALID"] = (
            "AVAILABLE" if path.is_file() else "MISSING"
        )
        self.provenance.append(
            ProvenanceRecord(
                artifact_id=artifact_id,
                role=role,
                path=display_path,
                status=status,
                sha256=_sha256(path) if path.is_file() else None,
                byte_size=path.stat().st_size if path.is_file() else None,
            )
        )

    def _mark_invalid(self, artifact_id: str) -> None:
        for record in reversed(self.provenance):
            if record.artifact_id == artifact_id:
                record.status = "INVALID"
                return

    def _module_failure(self, module: str, path: Path, message: str) -> None:
        self.modules.append(
            ModuleRecord(
                module=module,
                status="FAILED",
                source_file=self._display_path(path),
                message=message,
            )
        )
        self.errors.append(f"{module}: {message}")

    def _display_path(self, path: Path) -> str:
        if str(path) == "synthetic_scenario":
            return "synthetic_scenario"
        if not self.redact_paths:
            return str(path.resolve()) if path.is_absolute() or path.exists() else str(path)
        resolved = path.resolve() if path.is_absolute() or path.exists() else path
        if (
            isinstance(resolved, Path)
            and resolved.is_absolute()
            and resolved.is_relative_to(self.run_dir)
        ):
            relative = resolved.relative_to(self.run_dir)
            return "${RUN_DIR}" if relative == Path(".") else f"${{RUN_DIR}}/{relative}"
        if isinstance(resolved, Path) and resolved.is_absolute():
            return f"${{EXTERNAL}}/{resolved.name}"
        return str(resolved)

    def _sanitize(self, value: object) -> Any:
        if isinstance(value, dict):
            return {str(key): self._sanitize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._sanitize(item) for item in value]
        if isinstance(value, str) and value.startswith("/"):
            return self._display_path(Path(value))
        return value

    def _redact_command(self, command: str, config: SampleConfig | None) -> str:
        if not self.redact_paths or config is None:
            return command
        redacted = command
        for path in [*config.hifi_reads, *(config.kmer_reads or [])]:
            redacted = redacted.replace(str(path), self._display_path(path))
            redacted = redacted.replace(path.name, f"${{INPUT}}/{path.name}")
        return redacted


def _scalar(value: object) -> bool | int | float | str | None:
    return value if isinstance(value, bool | int | float | str) else None


def _string_list(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _deduplicate_software(records: list[SoftwareRecord]) -> list[SoftwareRecord]:
    output: list[SoftwareRecord] = []
    seen: set[tuple[str, str | None]] = set()
    for record in records:
        key = (record.tool, record.version)
        if key not in seen:
            seen.add(key)
            output.append(record)
    return output


def _optimization_evidence(
    optimization: OptimizationResult | None,
) -> dict[str, bool | int | float | str | None]:
    if optimization is None:
        return {}
    evidence = optimization.triggering_decision.get("evidence")
    if not isinstance(evidence, dict):
        return {}
    return {
        str(key): value
        for key, value in evidence.items()
        if value is None or isinstance(value, bool | int | float | str)
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
