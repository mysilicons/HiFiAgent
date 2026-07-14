"""Generate an auditable report-only anomaly from genuine Candida metrics."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import ValidationError

from hifi_agent.agent.models import AgentRunState, AssemblyParameters
from hifi_agent.exceptions import RuleEvaluationError
from hifi_agent.reporting.models import (
    SyntheticCandidate,
    SyntheticReportScenario,
    SyntheticTransformation,
)
from hifi_agent.schemas.metrics import AssemblyMetrics

DEFAULT_SYNTHETIC_SCENARIO = (
    Path(__file__).resolve().parents[3]
    / "benchmark"
    / "perturbations"
    / "candida_albicans_quality_regression.json"
)


def synthesize_candida_quality_regression(
    run_dir: Path,
    output: Path = DEFAULT_SYNTHETIC_SCENARIO,
    *,
    generated_at: datetime | None = None,
) -> SyntheticReportScenario:
    """Derive a clearly labeled bad candidate from real Candida baseline metrics."""
    config_path = run_dir / "00_metadata" / "resolved_config.yaml"
    metrics_path = run_dir / "03_post_qc" / "baseline" / "assembly_metrics.json"
    state_path = run_dir / "05_agent" / "agent_state.json"
    required = (config_path, metrics_path, state_path)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuleEvaluationError(
            f"Cannot synthesize Candida anomaly; source artifact(s) missing: {', '.join(missing)}"
        )
    try:
        config = yaml.safe_load(config_path.read_text())
        metrics = AssemblyMetrics.model_validate_json(metrics_path.read_text())
        state = AgentRunState.model_validate_json(state_path.read_text())
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise RuleEvaluationError(f"Cannot read Candida source artifacts: {exc}") from exc
    if not isinstance(config, dict) or config.get("sample_id") != "Candida_albicans":
        raise RuleEvaluationError(
            "Synthetic Stage 12 scenario requires Candida_albicans source data"
        )
    if state.baseline_config is None:
        raise RuleEvaluationError("Candida Agent state has no baseline assembly configuration")
    required_metrics = {
        "assembly_size": metrics.assembly_size,
        "assembly_size_ratio": metrics.assembly_size_ratio,
        "contig_n50": metrics.contig_n50,
        "busco_complete": metrics.busco_complete,
        "busco_single": metrics.busco_single,
        "busco_duplicated": metrics.busco_duplicated,
        "busco_fragmented": metrics.busco_fragmented,
        "busco_missing": metrics.busco_missing,
        "kmer_qv": metrics.kmer_qv,
        "kmer_completeness": metrics.kmer_completeness,
        "mapped_read_fraction": metrics.mapped_read_fraction,
        "coverage_cv": metrics.coverage_cv,
        "quast_misassemblies": metrics.quast_misassemblies,
    }
    absent = [name for name, value in required_metrics.items() if value is None]
    if absent:
        raise RuleEvaluationError(
            f"Candida source metrics required for synthesis are missing: {', '.join(absent)}"
        )
    source_values = {name: _number(value, name) for name, value in required_metrics.items()}
    expected_size = config.get("expected_genome_size")
    if isinstance(expected_size, bool) or not isinstance(expected_size, int | float):
        raise RuleEvaluationError("Candida expected_genome_size is unavailable")
    synthetic_values: dict[str, int | float] = {
        "assembly_size": round(expected_size * 1.10),
        "assembly_size_ratio": 1.10,
        "contig_n50": round(source_values["contig_n50"] * 1.50),
        "busco_complete": 82.0,
        "busco_single": 81.6,
        "busco_duplicated": 0.4,
        "busco_fragmented": 5.0,
        "busco_missing": 13.0,
        "kmer_qv": 12.0,
        "kmer_completeness": 45.0,
        "mapped_read_fraction": 0.75,
        "coverage_cv": 1.20,
        "quast_misassemblies": 250,
    }
    transformations = [
        SyntheticTransformation(
            metric=name,
            operation=(
                "derive_ratio"
                if name == "assembly_size_ratio"
                else "multiply"
                if name == "contig_n50"
                else "set"
            ),
            source_value=source_values[name],
            synthetic_value=value,
            rationale=_rationale(name),
        )
        for name, value in synthetic_values.items()
    ]
    candidate_metrics = metrics.model_copy(
        update={
            **synthetic_values,
            "run_id": "synthetic_candidate_n50_trap",
            "tool_failures": [],
            "tool_metadata": _redact_metadata_paths(metrics.tool_metadata),
            "metric_limitations": [
                *metrics.metric_limitations,
                "SYNTHETIC_REPORT_ONLY_NOT_A_WORKFLOW_RESULT",
                "N50_IMPROVED_WHILE_COMPLETENESS_AND_MAPPING_REGRESSED",
            ],
        }
    )
    parameters = state.baseline_config.parameters.model_copy(update={"purge_similarity": 0.50})
    scenario = SyntheticReportScenario(
        scenario_id="candida_n50_improves_but_quality_regresses",
        generated_at=generated_at or datetime.now(UTC),
        disclaimer=(
            "SYNTHETIC_DO_NOT_USE_FOR_SCIENCE: values are deterministic perturbations of the "
            "real Candida baseline and were never produced by hifiasm or post-QC tools."
        ),
        source_sample_id="Candida_albicans",
        source_run_dir=Path("${RUN_DIR}"),
        source_artifacts={
            "resolved_config": "${RUN_DIR}/00_metadata/resolved_config.yaml",
            "assembly_metrics": "${RUN_DIR}/03_post_qc/baseline/assembly_metrics.json",
            "agent_state": "${RUN_DIR}/05_agent/agent_state.json",
        },
        source_sha256={path.name: _sha256(path) for path in required},
        transformations=transformations,
        candidate=SyntheticCandidate(
            run_id="synthetic_candidate_n50_trap",
            parameters=AssemblyParameters.model_validate(parameters.model_dump()),
            reason_codes=[
                "SYNTHETIC_REPORT_ACCEPTANCE_FIXTURE",
                "N50_GAIN_WITH_CORE_QUALITY_REGRESSION",
            ],
            evidence={
                "baseline_contig_n50": metrics.contig_n50,
                "baseline_busco_complete": metrics.busco_complete,
                "baseline_kmer_completeness": metrics.kmer_completeness,
                "baseline_mapped_read_fraction": metrics.mapped_read_fraction,
            },
            risk_level="medium_high",
            result="REJECTED_SYNTHETIC_QUALITY_REGRESSION",
            metrics=candidate_metrics,
        ),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(scenario.model_dump_json(indent=2) + "\n")
    return scenario


def load_synthetic_scenario(path: Path) -> SyntheticReportScenario:
    """Load and validate an explicitly synthetic Stage 12 scenario."""
    try:
        scenario = SyntheticReportScenario.model_validate_json(path.read_text())
    except (OSError, ValidationError) as exc:
        raise RuleEvaluationError(f"Synthetic report scenario is invalid: {path}: {exc}") from exc
    if "SYNTHETIC_DO_NOT_USE_FOR_SCIENCE" not in scenario.disclaimer:
        raise RuleEvaluationError("Synthetic scenario disclaimer is missing")
    return scenario


def _number(value: object, name: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise RuleEvaluationError(f"Metric `{name}` is not numeric")
    return value


def _rationale(metric: str) -> str:
    rationales = {
        "assembly_size": (
            "Move size close to the expected genome size to create an attractive decoy."
        ),
        "assembly_size_ratio": "Derived from synthetic assembly size and real expected size.",
        "contig_n50": "Increase N50 by 50% to verify it cannot override correctness regressions.",
        "busco_complete": "Inject a severe gene-space completeness regression.",
        "busco_single": "Keep BUSCO single-copy consistent with synthetic complete and duplicated.",
        "busco_duplicated": "Lower duplication so that one superficial metric appears improved.",
        "busco_fragmented": "Increase fragmented BUSCOs while maintaining a valid percentage sum.",
        "busco_missing": "Increase missing BUSCOs while maintaining a valid percentage sum.",
        "kmer_qv": "Inject a severe consensus quality regression.",
        "kmer_completeness": "Inject loss of read-supported k-mers.",
        "mapped_read_fraction": "Inject a large read-support regression.",
        "coverage_cv": "Inject unstable coverage across the synthetic assembly.",
        "quast_misassemblies": "Inject additional reference-supported structural errors.",
    }
    return rationales[metric]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _redact_metadata_paths(value: object) -> object:
    """Keep source metadata useful while preventing machine-specific paths in fixtures."""
    if isinstance(value, dict):
        return {key: _redact_metadata_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_metadata_paths(item) for item in value]
    if isinstance(value, str) and Path(value).is_absolute():
        return f"${{EXTERNAL}}/{Path(value).name}"
    return value
