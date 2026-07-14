"""Create a Stage 11 anomaly from genuine Candida albicans artifacts."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import ValidationError

from hifi_agent.exceptions import RuleEvaluationError
from hifi_agent.optimization.models import (
    Stage11SyntheticScenario,
    SyntheticMetricTransformation,
)
from hifi_agent.schemas.metrics import AssemblyMetrics

DEFAULT_STAGE11_SCENARIO = (
    Path(__file__).resolve().parents[3]
    / "benchmark"
    / "perturbations"
    / "candida_albicans_stage11_closed_loop.json"
)


def synthesize_candida_stage11_scenario(
    run_dir: Path,
    output: Path = DEFAULT_STAGE11_SCENARIO,
    *,
    generated_at: datetime | None = None,
) -> Stage11SyntheticScenario:
    """Derive a legal-retry/N50-trap scenario from the genuine Candida baseline."""
    config_path = run_dir / "00_metadata/resolved_config.yaml"
    metrics_path = run_dir / "03_post_qc/baseline/assembly_metrics.json"
    state_path = run_dir / "05_agent/agent_state.json"
    required = (config_path, metrics_path, state_path)
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuleEvaluationError(
            f"Cannot synthesize Stage 11 Candida scenario; missing: {', '.join(missing)}"
        )
    try:
        config = yaml.safe_load(config_path.read_text())
        source = AssemblyMetrics.model_validate_json(metrics_path.read_text())
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise RuleEvaluationError(f"Cannot read Stage 11 Candida source artifacts: {exc}") from exc
    if not isinstance(config, dict) or config.get("sample_id") != "Candida_albicans":
        raise RuleEvaluationError("Stage 11 synthetic scenario requires Candida_albicans data")
    source_values = _required_source_values(source)
    expected_size = config.get("expected_genome_size")
    if isinstance(expected_size, bool) or not isinstance(expected_size, int | float):
        raise RuleEvaluationError("Candida expected_genome_size is unavailable")

    baseline_updates: dict[str, int | float] = {
        "busco_complete": 98.2,
        "busco_single": 86.2,
        "busco_duplicated": 12.0,
        "busco_fragmented": 0.3,
        "busco_missing": 1.5,
    }
    candidate_updates: dict[str, int | float] = {
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
    sanitized_metadata = _redact_paths(source.tool_metadata)
    baseline = source.model_copy(
        update={
            **baseline_updates,
            "run_id": "baseline",
            "tool_metadata": sanitized_metadata,
            "metric_limitations": [
                *source.metric_limitations,
                "SYNTHETIC_STAGE11_TRIGGER_NOT_A_WORKFLOW_RESULT",
            ],
        }
    )
    candidate = source.model_copy(
        update={
            **candidate_updates,
            "run_id": "candidate_r01_c01",
            "tool_failures": [],
            "tool_metadata": sanitized_metadata,
            "metric_limitations": [
                *source.metric_limitations,
                "SYNTHETIC_STAGE11_CANDIDATE_NOT_A_WORKFLOW_RESULT",
                "N50_IMPROVED_WHILE_CORE_QUALITY_REGRESSED",
            ],
        }
    )
    transformations = [
        *_transformations("baseline", source_values, baseline_updates),
        *_transformations("candidate_r01_c01", source_values, candidate_updates),
    ]
    scenario = Stage11SyntheticScenario(
        scenario_id="candida_stage11_legal_retry_n50_quality_trap",
        generated_at=generated_at or datetime.now(UTC),
        disclaimer=(
            "SYNTHETIC_DO_NOT_USE_FOR_SCIENCE: Stage 11 baseline anomaly and candidate "
            "metrics are deterministic perturbations of genuine Candida data; neither was "
            "produced by a candidate hifiasm/post-QC run."
        ),
        source_sample_id="Candida_albicans",
        source_run_dir=Path("${RUN_DIR}"),
        source_artifacts={
            "resolved_config": "${RUN_DIR}/00_metadata/resolved_config.yaml",
            "assembly_metrics": "${RUN_DIR}/03_post_qc/baseline/assembly_metrics.json",
            "agent_state": "${RUN_DIR}/05_agent/agent_state.json",
        },
        source_sha256={path.name: _sha256(path) for path in required},
        baseline_metrics=baseline,
        candidate_metrics=[candidate],
        transformations=transformations,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(scenario.model_dump_json(indent=2) + "\n")
    return scenario


def load_stage11_synthetic_scenario(path: Path) -> Stage11SyntheticScenario:
    """Load a strictly labeled Stage 11 synthetic scenario."""
    try:
        scenario = Stage11SyntheticScenario.model_validate_json(path.read_text())
    except (OSError, ValidationError) as exc:
        raise RuleEvaluationError(f"Invalid Stage 11 synthetic scenario: {path}: {exc}") from exc
    if "SYNTHETIC_DO_NOT_USE_FOR_SCIENCE" not in scenario.disclaimer:
        raise RuleEvaluationError("Stage 11 synthetic scenario disclaimer is missing")
    return scenario


def _required_source_values(source: AssemblyMetrics) -> dict[str, int | float]:
    names = (
        "assembly_size",
        "assembly_size_ratio",
        "contig_n50",
        "busco_complete",
        "busco_single",
        "busco_duplicated",
        "busco_fragmented",
        "busco_missing",
        "kmer_qv",
        "kmer_completeness",
        "mapped_read_fraction",
        "coverage_cv",
        "quast_misassemblies",
    )
    values: dict[str, int | float] = {}
    for name in names:
        value = getattr(source, name)
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise RuleEvaluationError(f"Candida source metric `{name}` is unavailable")
        values[name] = value
    return values


def _transformations(
    run_id: str,
    source: dict[str, int | float],
    updates: dict[str, int | float],
) -> list[SyntheticMetricTransformation]:
    return [
        SyntheticMetricTransformation(
            run_id=run_id,
            metric=metric,
            operation=("multiply" if metric == "contig_n50" else "set"),
            source_value=source[metric],
            synthetic_value=value,
            rationale=_rationale(run_id, metric),
        )
        for metric, value in updates.items()
    ]


def _rationale(run_id: str, metric: str) -> str:
    if run_id == "baseline":
        return "Inject concordant high BUSCO duplication so expert rules authorize one retry."
    rationales = {
        "assembly_size": "Create an attractive size correction decoy.",
        "assembly_size_ratio": "Move the candidate size ratio near one.",
        "contig_n50": "Increase N50 by 50% to exercise the anti-N50-only safeguard.",
        "busco_complete": "Inject severe gene-space completeness loss.",
        "busco_single": "Keep synthetic BUSCO components internally coherent.",
        "busco_duplicated": "Make purge appear successful by duplication alone.",
        "busco_fragmented": "Increase fragmented genes.",
        "busco_missing": "Increase missing genes.",
        "kmer_qv": "Inject consensus quality regression.",
        "kmer_completeness": "Inject read-supported k-mer loss.",
        "mapped_read_fraction": "Inject read-support loss.",
        "coverage_cv": "Inject a coverage anomaly.",
        "quast_misassemblies": "Inject additional structural errors.",
    }
    return rationales[metric]


def _redact_paths(value: object) -> object:
    if isinstance(value, dict):
        return {key: _redact_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_paths(item) for item in value]
    if isinstance(value, str) and Path(value).is_absolute():
        return f"${{EXTERNAL}}/{Path(value).name}"
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
