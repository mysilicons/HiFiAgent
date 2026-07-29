"""Bounded Stage 11 orchestration over real or explicitly synthetic metrics."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import ValidationError

from hifi_agent.agent.models import AssemblyConfig, PreQcMetrics
from hifi_agent.agent.planner import Planner
from hifi_agent.exceptions import InputValidationError, RuleEvaluationError, ToolExecutionError
from hifi_agent.executors.hifiasm_contract import validate_hifiasm_command_contract
from hifi_agent.optimization.comparator import METRIC_SPECS, CandidateComparator
from hifi_agent.optimization.engine import select_optimization_outcome
from hifi_agent.optimization.models import CandidateAssessment, OptimizationResult
from hifi_agent.optimization.synthetic import load_stage11_synthetic_scenario
from hifi_agent.rules import load_default_rule_engine, load_rule_context
from hifi_agent.rules.context import RuleContext
from hifi_agent.schemas.metrics import AssemblyMetrics
from hifi_agent.schemas.sample import SampleConfig

CandidateExecutor = Callable[[AssemblyConfig], AssemblyMetrics]


def run_stage11_optimization(
    run_dir: Path,
    *,
    scenario_path: Path | None = None,
    output_dir: Path | None = None,
    executor: CandidateExecutor | None = None,
    confirm_medium_high_risk: bool = False,
    generated_at: datetime | None = None,
) -> OptimizationResult:
    """Plan, evaluate, compare, and select at most two candidates in one bounded round."""
    resolved_run = run_dir.resolve()
    resolved_output = (output_dir or resolved_run / "05_agent/optimization").resolve()
    config = _load_config(resolved_run / "00_metadata/resolved_config.yaml")
    pre_qc = _load_pre_qc(resolved_run / "01_pre_qc/raw_metrics.json")
    planner = Planner()
    baseline_config = planner.plan_baseline(config, pre_qc)
    scenario = load_stage11_synthetic_scenario(scenario_path) if scenario_path else None
    if scenario is not None:
        _validate_scenario_sources(resolved_run, config, scenario.source_sha256)
        baseline_metrics = scenario.baseline_metrics
        baseline_source = "${SCENARIO}/baseline_metrics"
        timestamp = generated_at or scenario.generated_at
    else:
        baseline_path = resolved_run / "03_post_qc/baseline/assembly_metrics.json"
        baseline_metrics = _load_metrics(baseline_path, "baseline")
        baseline_source = "${RUN_DIR}/03_post_qc/baseline/assembly_metrics.json"
        timestamp = generated_at or datetime.now(UTC)

    context = _context_for_metrics(load_rule_context(resolved_run), baseline_metrics)
    decision = load_default_rule_engine().evaluate(context)
    optimization_round = 1 if decision.decision == "RETRY" else 0
    candidates = planner.propose_candidates(
        decision,
        baseline_config,
        optimization_round=max(optimization_round, 1),
        max_candidates=config.agent.max_candidates_per_round,
        seen_fingerprints={baseline_config.parameter_fingerprint()},
    )
    if len(candidates) > 2:
        raise RuleEvaluationError("Stage 11 candidate count exceeded the hard V1 maximum")

    resolved_output.mkdir(parents=True, exist_ok=True)
    config_dir = resolved_output / "candidate_configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    scenario_metrics = (
        {metrics.run_id: metrics for metrics in scenario.candidate_metrics}
        if scenario is not None
        else {}
    )
    assessments: list[CandidateAssessment] = []
    comparator = CandidateComparator()
    for candidate in candidates:
        (config_dir / f"{candidate.run_id}.json").write_text(
            json.dumps(
                _sanitize_paths(candidate.model_dump(mode="json"), resolved_run),
                indent=2,
            )
            + "\n"
        )
        metrics: AssemblyMetrics | None = None
        metrics_source = ""
        synthetic = scenario is not None
        if scenario is not None:
            metrics = scenario_metrics.get(candidate.run_id)
            metrics_source = f"${{SCENARIO}}/candidate_metrics/{candidate.run_id}"
            if metrics is None:
                raise RuleEvaluationError(
                    f"Synthetic Stage 11 scenario has no metrics for `{candidate.run_id}`"
                )
        elif candidate.requires_user_confirmation and not confirm_medium_high_risk:
            assessments.append(_not_run_assessment(candidate, "USER_CONFIRMATION_REQUIRED"))
            continue
        elif executor is not None:
            try:
                metrics = executor(candidate)
            except ToolExecutionError as exc:
                assessments.append(_failed_assessment(candidate, str(exc)))
                continue
            metrics_source = f"${{RUN_DIR}}/03_post_qc/{candidate.run_id}/assembly_metrics.json"
        else:
            path = resolved_run / f"03_post_qc/{candidate.run_id}/assembly_metrics.json"
            if path.is_file():
                command_path = (
                    resolved_run
                    / "02_assembly"
                    / candidate.run_id
                    / "metadata"
                    / "hifiasm_command.txt"
                )
                try:
                    validate_hifiasm_command_contract(candidate, command_path)
                except ToolExecutionError as exc:
                    assessments.append(_failed_assessment(candidate, str(exc)))
                    continue
                metrics = _load_metrics(path, candidate.run_id)
                metrics_source = f"${{RUN_DIR}}/03_post_qc/{candidate.run_id}/assembly_metrics.json"
            else:
                assessments.append(_not_run_assessment(candidate, "EXECUTION_NOT_REQUESTED"))
                continue
        if metrics.run_id != candidate.run_id:
            raise RuleEvaluationError(
                f"Candidate metrics run ID mismatch: {metrics.run_id} != {candidate.run_id}"
            )
        assessments.append(
            comparator.compare(
                baseline_config,
                baseline_metrics,
                candidate,
                metrics,
                metrics_source=metrics_source,
                synthetic=synthetic,
            )
        )

    result = select_optimization_outcome(
        sample_id=config.sample_id,
        run_dir=Path("${RUN_DIR}"),
        baseline_config=baseline_config,
        baseline_metrics=baseline_metrics,
        baseline_metrics_source=baseline_source,
        decision=decision,
        candidates=assessments,
        optimization_round=optimization_round,
        max_retry_rounds=config.agent.max_retry_rounds,
        max_candidates_per_round=config.agent.max_candidates_per_round,
        generated_at=timestamp,
        synthetic=scenario is not None,
        scenario_id=scenario.scenario_id if scenario else None,
        scenario_disclaimer=scenario.disclaimer if scenario else None,
        source_sha256=scenario.source_sha256 if scenario else {},
    )
    _write_outputs(
        result,
        resolved_output,
        run_dir=resolved_run,
        scenario_path=scenario_path,
    )
    return result


def _context_for_metrics(context: RuleContext, metrics: AssemblyMetrics) -> RuleContext:
    return context.model_copy(
        update={
            "assembly_size": metrics.assembly_size,
            "assembly_size_ratio": metrics.assembly_size_ratio,
            "contig_n50": metrics.contig_n50,
            "quast_misassemblies": metrics.quast_misassemblies,
            "busco_complete": metrics.busco_complete,
            "busco_duplicated": metrics.busco_duplicated,
            "kmer_completeness": metrics.kmer_completeness,
            "mapped_read_fraction": metrics.mapped_read_fraction,
            "coverage_cv": metrics.coverage_cv,
            "tool_failure_count": len(metrics.tool_failures),
        }
    )


def _load_config(path: Path) -> SampleConfig:
    try:
        data = yaml.safe_load(path.read_text())
        return SampleConfig.model_validate(data)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise InputValidationError(f"Stage 11 resolved config is invalid: {path}: {exc}") from exc


def _load_pre_qc(path: Path) -> PreQcMetrics:
    try:
        return PreQcMetrics.model_validate_json(path.read_text())
    except (OSError, ValidationError) as exc:
        raise ToolExecutionError(f"Stage 11 pre-QC metrics are invalid: {path}: {exc}") from exc


def _load_metrics(path: Path, expected_run_id: str) -> AssemblyMetrics:
    try:
        metrics = AssemblyMetrics.model_validate_json(path.read_text())
    except (OSError, ValidationError) as exc:
        raise ToolExecutionError(f"Stage 11 assembly metrics are invalid: {path}: {exc}") from exc
    if metrics.run_id != expected_run_id:
        raise ToolExecutionError(
            f"Stage 11 metrics run ID mismatch: {metrics.run_id} != {expected_run_id}"
        )
    return metrics


def _not_run_assessment(candidate: AssemblyConfig, reason: str) -> CandidateAssessment:
    return CandidateAssessment(
        run_id=candidate.run_id,
        status="NOT_RUN",
        config=candidate,
        metrics=None,
        metrics_source="NOT_RUN",
        parameter_differences=[],
        metric_differences=[],
        conflicts=[reason],
        tradeoffs=[f"candidate not run: {reason}"],
    )


def _failed_assessment(candidate: AssemblyConfig, error: str) -> CandidateAssessment:
    return CandidateAssessment(
        run_id=candidate.run_id,
        status="FAILED",
        config=candidate,
        metrics=None,
        metrics_source="FAILED",
        parameter_differences=[],
        metric_differences=[],
        hard_regressions=["CANDIDATE_EXECUTION_FAILED"],
        tradeoffs=[f"candidate execution failed: {error}"],
    )


def _validate_scenario_sources(
    run_dir: Path,
    config: SampleConfig,
    expected_hashes: dict[str, str],
) -> None:
    if config.sample_id != "Candida_albicans":
        raise RuleEvaluationError("Stage 11 retained scenario is only valid for Candida_albicans")
    paths = {
        "resolved_config.yaml": run_dir / "00_metadata/resolved_config.yaml",
        "assembly_metrics.json": run_dir / "03_post_qc/baseline/assembly_metrics.json",
        "agent_state.json": run_dir / "05_agent/agent_state.json",
    }
    observed = {name: _sha256(path) for name, path in paths.items()}
    if observed != expected_hashes:
        raise RuleEvaluationError(
            "Stage 11 synthetic scenario source hashes do not match the current Candida run"
        )


def _write_outputs(
    result: OptimizationResult,
    output_dir: Path,
    *,
    run_dir: Path,
    scenario_path: Path | None,
) -> None:
    (output_dir / "optimization_result.json").write_text(
        json.dumps(
            _sanitize_paths(result.model_dump(mode="json"), run_dir),
            indent=2,
        )
        + "\n"
    )
    _write_comparison(result, output_dir / "comparison.tsv")
    _write_parameter_diff(result, output_dir / "parameter_diff.tsv")
    _write_tradeoffs(result, output_dir / "selection_tradeoffs.md")
    provenance = output_dir / "provenance.tsv"
    with provenance.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["artifact", "path", "sha256", "synthetic"])
        artifact_paths = {
            "resolved_config.yaml": "${RUN_DIR}/00_metadata/resolved_config.yaml",
            "assembly_metrics.json": ("${RUN_DIR}/03_post_qc/baseline/assembly_metrics.json"),
            "agent_state.json": "${RUN_DIR}/05_agent/agent_state.json",
        }
        for name, digest in result.source_sha256.items():
            writer.writerow(
                [
                    name,
                    artifact_paths.get(name, f"${{RUN_DIR}}/{name}"),
                    digest,
                    str(result.synthetic).lower(),
                ]
            )
        if scenario_path is not None:
            writer.writerow(
                [
                    "stage11_scenario",
                    f"${{EXTERNAL}}/{scenario_path.name}",
                    _sha256(scenario_path),
                    "true",
                ]
            )


def _write_comparison(result: OptimizationResult, path: Path) -> None:
    metric_fields = [
        field
        for metric in METRIC_SPECS
        for field in (
            f"{metric}_baseline",
            f"{metric}_candidate",
            f"{metric}_delta",
            f"{metric}_assessment",
        )
    ]
    fields = [
        "run_id",
        "status",
        "synthetic",
        "parameter_diff",
        "dominated_by",
        "hard_regressions",
        "acceptance_failures",
        "conflicts",
        *metric_fields,
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        for candidate in result.candidates:
            row: dict[str, object] = {
                "run_id": candidate.run_id,
                "status": candidate.status,
                "synthetic": str(candidate.synthetic).lower(),
                "parameter_diff": json.dumps(
                    [item.model_dump(mode="json") for item in candidate.parameter_differences],
                    sort_keys=True,
                ),
                "dominated_by": ",".join(candidate.dominated_by),
                "hard_regressions": ",".join(candidate.hard_regressions),
                "acceptance_failures": ",".join(candidate.acceptance_failures),
                "conflicts": ",".join(candidate.conflicts),
            }
            for difference in candidate.metric_differences:
                row[f"{difference.metric}_baseline"] = _cell(difference.baseline_value)
                row[f"{difference.metric}_candidate"] = _cell(difference.candidate_value)
                row[f"{difference.metric}_delta"] = _cell(difference.delta)
                row[f"{difference.metric}_assessment"] = difference.assessment
            writer.writerow(row)


def _write_parameter_diff(result: OptimizationResult, path: Path) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(
            [
                "run_id",
                "parameter",
                "baseline_value",
                "candidate_value",
                "reason_codes",
                "risk_level",
                "result",
            ]
        )
        for candidate in result.candidates:
            for difference in candidate.parameter_differences:
                writer.writerow(
                    [
                        candidate.run_id,
                        difference.parameter,
                        _cell(difference.baseline_value),
                        _cell(difference.candidate_value),
                        ",".join(candidate.config.reason_codes),
                        candidate.config.risk_level,
                        candidate.status,
                    ]
                )


def _write_tradeoffs(result: OptimizationResult, path: Path) -> None:
    lines = [
        f"# Stage 11 selection — {result.sample_id}",
        "",
    ]
    if result.scenario_disclaimer:
        lines.extend(
            [
                "> **SYNTHETIC SCENARIO — NOT A SCIENTIFIC RESULT**",
                f"> {result.scenario_disclaimer}",
                "",
            ]
        )
    lines.extend(
        [
            f"- Outcome: **{result.outcome}**",
            f"- Selected run: **{result.selected_run_id or 'NONE'}**",
            f"- Reason: {result.selection_reason}",
            f"- Round: {result.optimization_round}/{result.max_retry_rounds}",
            f"- Candidate count: {len(result.candidates)}/{result.max_candidates_per_round}",
            "",
            "## Selection costs and tradeoffs",
            "",
            *[f"- {item}" for item in result.selection_tradeoffs],
            "",
            "N50 is never allowed to override protected completeness, k-mer, mapping, coverage, "
            "or structural-error regressions.",
        ]
    )
    path.write_text("\n".join(lines) + "\n")


def _cell(value: object) -> object:
    return "" if value is None else value


def _sanitize_paths(value: object, run_dir: Path) -> object:
    if isinstance(value, dict):
        return {str(key): _sanitize_paths(item, run_dir) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_paths(item, run_dir) for item in value]
    if isinstance(value, str) and value.startswith("/"):
        path = Path(value)
        if path.is_relative_to(run_dir):
            relative = path.relative_to(run_dir)
            return "${RUN_DIR}" if relative == Path(".") else f"${{RUN_DIR}}/{relative}"
        return f"${{EXTERNAL}}/{path.name}"
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
