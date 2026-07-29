import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from hifi_agent.qc import MetricEvidence, QcFeatureBundle, build_qc_feature_bundle
from hifi_agent.rules.context import RuleContext


def _run(
    tmp_path: Path,
    *,
    expected_genome_size: int | None = 100_000_000,
    kmer_source: str = "independent_high_confidence",
    model_status: str = "success",
    peak_depth: int | None = 30,
    warnings: list[str] | None = None,
    genomescope_size: int | None = 98_000_000,
    total_bases: int = 3_000_000_000,
    mean_qscore: float = 30.0,
) -> Path:
    run_dir = tmp_path / "sensitive_server_path" / "run"
    config = {
        "sample_id": "sample",
        "hifi_reads": [str(tmp_path / "secret" / "reads.fastq.gz")],
        "outdir": str(run_dir),
        "expected_genome_size": expected_genome_size,
        "ploidy": 2,
        "inbred": False,
        "reference_genome": str(tmp_path / "secret" / "reference.fa"),
    }
    raw = {
        "sample_id": "sample",
        "input_status": "PASS",
        "read_count": 200_000,
        "total_bases": total_bases,
        "mean_read_length": 15_000.0,
        "read_n50": 16_000,
        "mean_qscore": mean_qscore,
        "gc_percent": 42.5,
        "estimated_genome_size": expected_genome_size or genomescope_size,
        "estimated_genome_size_source": (
            "expected_genome_size" if expected_genome_size else "genomescope"
        ),
        "estimated_coverage": None,
        "kmer_source": kmer_source,
        "kmer_peak_depth": peak_depth,
        "genomescope_model_status": model_status,
        "warnings": warnings or [],
    }
    kmer = {
        "sample_id": "sample",
        "kmer_source": kmer_source,
        "peak_depth": peak_depth,
        "low_coverage_peak_threshold": 10.0,
        "genomescope_model_status": model_status,
        "genomescope_genome_size": genomescope_size,
        "genomescope_heterozygosity": 0.8,
        "genomescope_repeat_fraction": 0.2,
        "warnings": warnings or [],
    }
    files = {
        "00_metadata/resolved_config.yaml": yaml.safe_dump(config),
        "01_pre_qc/raw_metrics.json": json.dumps(raw),
        "01_pre_qc/kmer/kmer_metrics.json": json.dumps(kmer),
    }
    for relative, content in files.items():
        path = run_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content + "\n")
    return run_dir


def test_feature_bundle_is_byte_stable_and_every_metric_has_evidence(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)

    first = build_qc_feature_bundle(run_dir)
    first_bytes = (run_dir / "01_pre_qc/qc_feature_bundle.json").read_bytes()
    second = build_qc_feature_bundle(run_dir)
    second_bytes = (run_dir / "01_pre_qc/qc_feature_bundle.json").read_bytes()

    assert first == second
    assert first_bytes == second_bytes
    assert first.kmer_peak_authorizes_hom_cov is True
    for metric_id, evidence in first.features.items():
        assert evidence.metric_id == metric_id
        assert evidence.unit
        assert evidence.sources
        assert evidence.confidence in {"high", "medium", "low", "unavailable"}


def test_expected_genome_size_has_priority_and_coverage_is_recomputed(tmp_path: Path) -> None:
    run_dir = _run(tmp_path, expected_genome_size=100_000_000, genomescope_size=98_000_000)

    bundle = build_qc_feature_bundle(run_dir)

    assert bundle.features["selected_genome_size"].value == 100_000_000
    assert bundle.features["selected_genome_size"].confidence == "medium"
    assert bundle.features["estimated_coverage"].value == 30.0
    assert bundle.features["estimated_coverage"].unit == "x"


def test_conflicting_genome_sizes_lower_confidence_but_keep_declared_priority(
    tmp_path: Path,
) -> None:
    run_dir = _run(tmp_path, expected_genome_size=100_000_000, genomescope_size=160_000_000)

    bundle = build_qc_feature_bundle(run_dir)

    selected = bundle.features["selected_genome_size"]
    assert selected.value == 100_000_000
    assert selected.confidence == "low"
    assert "GENOME_SIZE_ESTIMATES_CONFLICT" in bundle.warnings


def test_unknown_genome_size_preserves_none_and_disables_coverage(tmp_path: Path) -> None:
    run_dir = _run(
        tmp_path,
        expected_genome_size=None,
        genomescope_size=None,
        model_status="failed",
        peak_depth=None,
    )

    bundle = build_qc_feature_bundle(run_dir)

    assert bundle.features["selected_genome_size"].value is None
    assert bundle.features["estimated_coverage"].value is None
    assert bundle.features["selected_genome_size"].confidence == "unavailable"
    assert "selected_genome_size" in bundle.missing_metrics
    assert "GENOME_SIZE_UNAVAILABLE" in bundle.warnings
    assert bundle.features["genomescope_genome_size"].value is None
    assert bundle.features["heterozygosity"].value is None
    assert bundle.features["repeat_fraction"].value is None


@pytest.mark.parametrize(
    ("source", "warnings", "model_status", "peak", "expected_limitation"),
    [
        (
            "same_data_advisory",
            [],
            "success",
            30,
            "KMER_SOURCE_SAME_HIFI_READS_NOT_INDEPENDENT",
        ),
        (
            "independent_high_confidence",
            ["KMER_LOW_COVERAGE_PEAK"],
            "success",
            5,
            "KMER_PEAK_BELOW_TRUST_THRESHOLD",
        ),
        (
            "independent_high_confidence",
            ["KMER_MULTIPLE_COMPARABLE_PEAKS"],
            "success",
            30,
            "KMER_MULTIPLE_COMPARABLE_PEAKS",
        ),
        (
            "independent_high_confidence",
            [],
            "failed",
            30,
            "GENOMESCOPE_MODEL_NOT_SUCCESSFUL",
        ),
    ],
)
def test_untrusted_kmer_evidence_never_authorizes_hom_cov(
    tmp_path: Path,
    source: str,
    warnings: list[str],
    model_status: str,
    peak: int,
    expected_limitation: str,
) -> None:
    run_dir = _run(
        tmp_path,
        kmer_source=source,
        warnings=warnings,
        model_status=model_status,
        peak_depth=peak,
    )

    bundle = build_qc_feature_bundle(run_dir)
    peak_evidence = bundle.features["kmer_peak_depth"]

    assert bundle.kmer_peak_authorizes_hom_cov is False
    assert peak_evidence.confidence == "low"
    assert expected_limitation in peak_evidence.limitations


def test_extreme_coverage_and_low_read_quality_are_explicit_warnings(tmp_path: Path) -> None:
    run_dir = _run(
        tmp_path,
        expected_genome_size=1_000_000,
        genomescope_size=1_000_000,
        total_bases=1_000_000_000,
        mean_qscore=15.0,
    )

    bundle = build_qc_feature_bundle(run_dir)

    assert bundle.features["estimated_coverage"].value == 1000.0
    assert bundle.features["estimated_coverage"].confidence == "low"
    assert "COVERAGE_EXTREME_HIGH" in bundle.warnings
    assert "READ_MEAN_QSCORE_BELOW_20" in bundle.warnings


def test_user_metadata_has_explicit_source_and_no_reference_path(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)

    bundle = build_qc_feature_bundle(run_dir)
    summary_text = (run_dir / "01_pre_qc/qc_llm_summary.json").read_text()

    assert bundle.features["ploidy"].sources == ["00_metadata/resolved_config.yaml"]
    assert bundle.features["inbred"].limitations == ["USER_DECLARED_METADATA"]
    assert bundle.features["reference_available"].value is True
    assert str(tmp_path) not in summary_text
    assert "reads.fastq" not in summary_text
    assert "reference.fa" not in summary_text


def test_percentage_evidence_is_not_rescaled() -> None:
    busco = MetricEvidence(
        metric_id="busco_duplicated",
        value=0.8,
        unit="percent",
        sources=["03_post_qc/baseline/busco/busco_metrics.json"],
        confidence="high",
    )

    assert busco.value == 0.8
    assert busco.model_dump(mode="json")["value"] == 0.8


def test_missing_metric_cannot_claim_non_unavailable_confidence() -> None:
    with pytest.raises(ValidationError, match="missing QC metric"):
        MetricEvidence(
            metric_id="missing",
            value=None,
            unit="bp",
            sources=["source.json"],
            confidence="high",
        )


def test_unknown_genome_size_does_not_make_assembly_ratio_a_core_requirement() -> None:
    context = RuleContext(
        assembly_size=100,
        assembly_size_ratio=None,
        contig_n50=50,
        busco_complete=98.0,
        busco_duplicated=1.0,
        mapped_read_fraction=0.99,
    )

    assert context.metric_values()["core_metrics_complete"] is True


def test_rule_context_requires_explicit_independent_kmer_authorization() -> None:
    advisory = RuleContext(
        kmer_source="same_data_advisory",
        kmer_peak_depth=30,
        genomescope_model_status="success",
        kmer_peak_authorizes_hom_cov=True,
    )
    independent = RuleContext(
        kmer_source="independent_high_confidence",
        kmer_peak_depth=30,
        genomescope_model_status="success",
        kmer_peak_authorizes_hom_cov=True,
    )

    assert advisory.metric_values()["trusted_kmer_peak"] is False
    assert independent.metric_values()["trusted_kmer_peak"] is True


def test_written_bundle_round_trips_through_schema(tmp_path: Path) -> None:
    run_dir = _run(tmp_path)
    build_qc_feature_bundle(run_dir)

    loaded = QcFeatureBundle.model_validate_json(
        (run_dir / "01_pre_qc/qc_feature_bundle.json").read_text()
    )

    assert loaded.sample_id == "sample"
    assert loaded.features["heterozygosity"].unit == "percent"
