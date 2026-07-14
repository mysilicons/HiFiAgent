import csv
import json
from datetime import UTC, datetime
from pathlib import Path

import yaml
from typer.testing import CliRunner

from hifi_agent.agent.models import AssemblyParameters
from hifi_agent.cli import app
from hifi_agent.reporting.models import (
    SyntheticCandidate,
    SyntheticReportScenario,
    SyntheticTransformation,
)
from hifi_agent.reporting.renderer import render_final_report
from hifi_agent.schemas.metrics import AssemblyMetrics

runner = CliRunner()
FIXED_TIME = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def _make_report_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run"
    config = {
        "sample_id": "report_fixture",
        "hifi_reads": ["/sensitive/input/reads.fastq.gz"],
        "outdir": str(run_dir),
        "species_name": "Candida albicans",
        "expected_genome_size": 14_500_000,
        "ploidy": 2,
        "busco_lineage": "saccharomycetes_odb12",
        "reference_genome": "/sensitive/input/reference.fasta",
        "resources": {"max_threads": 8, "max_memory_gb": 32},
    }
    config_path = run_dir / "00_metadata/resolved_config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))
    _write_json(run_dir / "00_metadata/validation_receipt.json", {"status": "PASS"})
    (run_dir / "00_metadata/input_checksums.tsv").write_text(
        f"role\tpath\tsha256\tbytes\nhifi_reads\t/sensitive/input/reads.fastq.gz\t{'a' * 64}\t100\n"
    )
    _write_json(
        run_dir / "01_pre_qc/raw_metrics.json",
        {
            "input_status": "PASS",
            "read_count": 10,
            "total_bases": 150_000,
            "mean_read_length": 15_000.0,
            "read_n50": 16_000,
            "mean_qscore": 30.0,
            "gc_percent": 33.0,
            "estimated_genome_size": 14_500_000,
            "estimated_coverage": 10.34,
            "kmer_peak_depth": None,
            "kmer_source": "same_data_advisory",
            "warnings": [],
        },
    )
    _write_json(
        run_dir / "02_assembly/baseline/metadata/assembly_manifest.json",
        {
            "hifiasm_version": "0.25.0-r726",
            "command": "hifiasm -o report_fixture.baseline -t 8 /sensitive/input/reads.fastq.gz",
        },
    )
    metrics = AssemblyMetrics(
        run_id="baseline",
        assembly_size=14_600_000,
        contig_count=20,
        contig_n50=1_000_000,
        longest_contig=3_000_000,
        quast_misassemblies=0,
        busco_complete=98.0,
        busco_single=97.0,
        busco_duplicated=1.0,
        busco_fragmented=0.5,
        busco_missing=1.5,
        kmer_qv=None,
        kmer_completeness=95.0,
        mapped_read_fraction=1.0,
        coverage_cv=0.2,
        assembly_size_ratio=1.0069,
        tool_versions={"quast": "5.3.0"},
    )
    _write_json(
        run_dir / "03_post_qc/baseline/assembly_metrics.json",
        metrics.model_dump(mode="json"),
    )
    mapping = {
        "status": "success",
        "version": "2.30-r1287",
        "limitations": [],
        "filter": {
            "input_read_count": 10,
            "retained_read_count": 10,
            "retained_read_fraction": 1.0,
            "filtered_short_read_count": 0,
            "filtered_low_quality_read_count": 0,
            "min_read_length": 1000,
            "min_mean_qscore": 20.0,
        },
    }
    _write_json(run_dir / "03_post_qc/baseline/mapping/mapping_metrics.json", mapping)
    for module in ("quast", "busco", "merqury"):
        _write_json(
            run_dir / f"03_post_qc/baseline/{module}/{module}_metrics.json",
            {"status": "success", "version": "test", "limitations": []},
        )
    _write_json(
        run_dir / "04_decisions/baseline/rule_decision.json",
        {
            "decision_id": "D-REPORT",
            "rule_set_version": "test",
            "threshold_catalog_version": "test",
            "decision": "BASELINE",
            "action": "ACCEPT_DEFAULT_PARAMETERS",
            "matched_rule_ids": ["METRICS_NORMAL"],
            "controlling_rule_ids": ["METRICS_NORMAL"],
            "reason_codes": ["METRICS_NORMAL"],
            "evidence": {"assembly_size_ratio": 1.0069, "quast_misassemblies": 0},
            "candidates": [],
            "confidence": 0.95,
            "risk_level": "low",
            "conflicts": [],
            "human_readable_explanation": "All mandatory dimensions are acceptable.",
        },
    )
    figure = run_dir / "01_pre_qc/kmer/genomescope/linear_plot.png"
    figure.parent.mkdir(parents=True)
    figure.write_bytes(b"real-image-placeholder")
    return run_dir


def _synthetic_scenario(path: Path) -> Path:
    metrics = AssemblyMetrics(
        run_id="synthetic_bad",
        assembly_size=15_950_000,
        contig_count=20,
        contig_n50=1_500_000,
        longest_contig=3_000_000,
        quast_misassemblies=50,
        busco_complete=80.0,
        busco_single=79.0,
        busco_duplicated=1.0,
        busco_fragmented=5.0,
        busco_missing=15.0,
        kmer_qv=12.0,
        kmer_completeness=45.0,
        mapped_read_fraction=0.75,
        coverage_cv=1.2,
        assembly_size_ratio=1.1,
        metric_limitations=["SYNTHETIC_REPORT_ONLY_NOT_A_WORKFLOW_RESULT"],
    )
    scenario = SyntheticReportScenario(
        scenario_id="test_n50_trap",
        generated_at=FIXED_TIME,
        disclaimer="SYNTHETIC_DO_NOT_USE_FOR_SCIENCE: unit-test scenario.",
        source_sample_id="report_fixture",
        source_run_dir=Path("${RUN_DIR}"),
        source_artifacts={"assembly_metrics": "${RUN_DIR}/assembly_metrics.json"},
        source_sha256={"assembly_metrics.json": "b" * 64},
        transformations=[
            SyntheticTransformation(
                metric="contig_n50",
                operation="multiply",
                source_value=1_000_000,
                synthetic_value=1_500_000,
                rationale="Acceptance trap.",
            )
        ],
        candidate=SyntheticCandidate(
            run_id="synthetic_bad",
            parameters=AssemblyParameters(purge_similarity=0.5),
            reason_codes=["N50_GAIN_WITH_CORE_QUALITY_REGRESSION"],
            evidence={"baseline_contig_n50": 1_000_000, "baseline_busco_complete": 98.0},
            risk_level="medium_high",
            result="REJECTED_SYNTHETIC_QUALITY_REGRESSION",
            metrics=metrics,
        ),
    )
    path.write_text(scenario.model_dump_json(indent=2) + "\n")
    return path


def test_stage12_renders_all_artifacts_and_preserves_missing_and_zero(tmp_path: Path) -> None:
    run_dir = _make_report_run(tmp_path)

    outputs = render_final_report(run_dir, generated_at=FIXED_TIME)
    summary = json.loads(outputs.summary_json.read_text())
    markdown = outputs.markdown.read_text()

    for section in range(1, 15):
        assert f"## {section}." in markdown
    assert summary["pre_qc_metrics"]["kmer_peak_depth"]["value"] is None
    assert "k-mer peak depth | NA (not available)" in markdown
    assert summary["filtering_metrics"]["filtered_low_quality_read_count"]["value"] == 0
    assert "Low-quality reads filtered | 0" in markdown
    assert summary["assembly_runs"][0]["metrics"]["quast_misassemblies"]["value"] == 0
    assert "/sensitive/input" not in markdown
    assert "/sensitive/input" not in outputs.summary_json.read_text()
    assert (outputs.figures_dir / "genomescope_linear_plot.png").read_bytes() == (
        b"real-image-placeholder"
    )
    assert (outputs.output_dir / "reproducible_commands.txt").is_file()
    assert (outputs.output_dir / "software_versions.tsv").is_file()


def test_every_displayed_metric_has_exact_source_and_pointer(tmp_path: Path) -> None:
    run_dir = _make_report_run(tmp_path)
    outputs = render_final_report(run_dir, generated_at=FIXED_TIME)
    summary = json.loads(outputs.summary_json.read_text())
    records = [
        *summary["pre_qc_metrics"].values(),
        *summary["filtering_metrics"].values(),
        *summary["assembly_runs"][0]["metrics"].values(),
    ]

    assert records
    assert all(record["source_file"] for record in records)
    assert all(record["json_pointer"].startswith("/") for record in records)
    provenance = summary["provenance"]
    identities = [(record["artifact_id"], record["path"]) for record in provenance]
    assert len(identities) == len(set(identities))


def test_absolute_paths_are_available_only_by_explicit_opt_in(tmp_path: Path) -> None:
    run_dir = _make_report_run(tmp_path)
    output = tmp_path / "absolute-report"

    outputs = render_final_report(
        run_dir,
        output_dir=output,
        redact_paths=False,
        generated_at=FIXED_TIME,
    )

    assert "/sensitive/input/reads.fastq.gz" in outputs.markdown.read_text()
    assert json.loads(outputs.summary_json.read_text())["paths_redacted"] is False


def test_failed_or_incomplete_run_still_renders_an_honest_report(tmp_path: Path) -> None:
    run_dir = tmp_path / "failed-run"
    run_dir.mkdir()

    outputs = render_final_report(run_dir, generated_at=FIXED_TIME)
    summary = json.loads(outputs.summary_json.read_text())
    markdown = outputs.markdown.read_text()

    assert summary["report_status"] == "FAILED"
    assert summary["errors"]
    assert any(module["status"] == "FAILED" for module in summary["modules"])
    assert "NA (not available)" in markdown
    assert "## 14. Errors and modules not run" in markdown


def test_synthetic_candidate_records_parameter_reason_evidence_risk_and_result(
    tmp_path: Path,
) -> None:
    run_dir = _make_report_run(tmp_path)
    scenario = _synthetic_scenario(tmp_path / "scenario.json")

    outputs = render_final_report(
        run_dir,
        output_dir=tmp_path / "synthetic-report",
        scenario_path=scenario,
        generated_at=FIXED_TIME,
    )
    summary = json.loads(outputs.summary_json.read_text())
    change = summary["parameter_changes"][0]
    runs = {run["run_id"]: run for run in summary["assembly_runs"]}

    assert summary["final_selection"] == "NO_AUTOMATIC_SELECTION"
    assert change["reason_codes"]
    assert change["evidence"]
    assert change["risk_level"] == "medium_high"
    assert change["result"] == "REJECTED_SYNTHETIC_QUALITY_REGRESSION"
    assert runs["synthetic_bad"]["metrics"]["contig_n50"]["value"] > 1_000_000
    assert runs["synthetic_bad"]["metrics"]["busco_complete"]["value"] < 98.0
    assert runs["synthetic_bad"]["metrics"]["contig_n50"]["source_file"].endswith("/scenario.json")
    assert any(
        record["artifact_id"] == "synthetic_scenario"
        and record["status"] == "AVAILABLE"
        and record["sha256"]
        for record in summary["provenance"]
    )
    assert "SYNTHETIC SCENARIO" in outputs.markdown.read_text()
    with outputs.parameter_diff_tsv.open(newline="") as handle:
        row = next(csv.DictReader(handle, delimiter="\t"))
    assert row["reason_codes"]
    assert row["evidence"]
    assert row["risk_level"]
    assert row["result"]


def test_report_cli_is_implemented(tmp_path: Path) -> None:
    run_dir = _make_report_run(tmp_path)

    result = runner.invoke(app, ["report", str(run_dir)])

    assert result.exit_code == 0
    assert "Final report rendered" in result.output
    assert (run_dir / "05_report/final_report.md").is_file()
