import gzip
from pathlib import Path

import pytest
import yaml

from hifi_agent.config import (
    validate_config_file,
    verify_recorded_input_checksums,
    verify_validation_receipt,
)
from hifi_agent.exceptions import InputValidationError
from hifi_agent.executors.nextflow import NextflowRunResult
from hifi_agent.schemas.sample import ResourceConfig


def write_fastq(path: Path) -> Path:
    path.write_text("@read1\nACGT\n+\nIIII\n")
    return path


def write_config(tmp_path: Path, data: dict[str, object]) -> Path:
    config_path = tmp_path / "sample.yaml"
    config_path.write_text(yaml.safe_dump(data, sort_keys=False))
    return config_path


def base_config(tmp_path: Path) -> dict[str, object]:
    reads = write_fastq(tmp_path / "reads.fastq")
    return {
        "sample_id": "sample_01",
        "hifi_reads": [str(reads)],
        "outdir": str(tmp_path / "results" / "sample_01"),
        "species_name": None,
        "expected_genome_size": None,
        "ploidy": 2,
        "inbred": None,
        "busco_lineage": None,
        "kmer_reads": None,
        "reference_genome": None,
        "resources": {"max_threads": 4, "max_memory_gb": 16},
        "agent": {"max_retry_rounds": 1, "max_candidates_per_round": 2, "objective": "balanced"},
    }


def assert_invalid(tmp_path: Path, data: dict[str, object], expected: str) -> None:
    with pytest.raises(InputValidationError, match=expected):
        validate_config_file(write_config(tmp_path, data))


def test_resource_defaults_leave_capacity_for_the_local_host() -> None:
    resources = ResourceConfig()

    assert resources.max_threads == 480
    assert resources.max_memory_gb == 960


def test_valid_config_writes_resolved_config_and_checksums(tmp_path: Path) -> None:
    result = validate_config_file(write_config(tmp_path, base_config(tmp_path)))

    assert result.resolved_config.is_file()
    assert result.input_checksums.is_file()
    assert result.validation_receipt.is_file()
    assert result.config.hifi_reads[0].is_absolute()
    assert "sha256" in result.input_checksums.read_text()
    assert '"status": "PASS"' in result.validation_receipt.read_text()


def test_single_hifi_read_path_is_accepted(tmp_path: Path) -> None:
    data = base_config(tmp_path)
    data["hifi_reads"] = str(tmp_path / "reads.fastq")

    result = validate_config_file(write_config(tmp_path, data), write_outputs=False)

    assert len(result.config.hifi_reads) == 1


def test_changed_metadata_is_rejected_by_validation_receipt(tmp_path: Path) -> None:
    result = validate_config_file(write_config(tmp_path, base_config(tmp_path)))
    result.resolved_config.write_text("changed: true\n")

    with pytest.raises(InputValidationError, match="missing or changed"):
        verify_validation_receipt(result.config, result.validation_receipt)


def test_changed_input_is_rejected_by_recorded_checksums(tmp_path: Path) -> None:
    result = validate_config_file(write_config(tmp_path, base_config(tmp_path)))
    result.config.hifi_reads[0].write_text("@changed\nAAAA\n+\nIIII\n")

    with pytest.raises(InputValidationError, match="missing or changed"):
        verify_recorded_input_checksums(result.input_checksums)


def test_missing_fastq_file_fails(tmp_path: Path) -> None:
    data = base_config(tmp_path)
    data["hifi_reads"] = [str(tmp_path / "missing.fastq")]

    assert_invalid(tmp_path, data, "missing file")


def test_corrupted_gzip_fails(tmp_path: Path) -> None:
    bad_gzip = tmp_path / "reads.fastq.gz"
    bad_gzip.write_bytes(b"not a gzip stream")
    data = base_config(tmp_path)
    data["hifi_reads"] = [str(bad_gzip)]

    assert_invalid(tmp_path, data, "corrupted gzip")


def test_valid_gzip_fastq_passes(tmp_path: Path) -> None:
    gz_path = tmp_path / "reads.fastq.gz"
    with gzip.open(gz_path, "wt") as handle:
        handle.write("@read1\nACGT\n+\nIIII\n")
    data = base_config(tmp_path)
    data["hifi_reads"] = [str(gz_path)]

    result = validate_config_file(write_config(tmp_path, data), write_outputs=False)

    assert result.config.hifi_reads == [gz_path.resolve()]


def test_incomplete_fastq_fails(tmp_path: Path) -> None:
    reads = tmp_path / "incomplete.fastq"
    reads.write_text("@read1\nACGT\n+\n")
    data = base_config(tmp_path)
    data["hifi_reads"] = [str(reads)]

    assert_invalid(tmp_path, data, "complete FASTQ record")


def test_invalid_fastq_header_fails(tmp_path: Path) -> None:
    reads = tmp_path / "bad_header.fastq"
    reads.write_text("read1\nACGT\n+\nIIII\n")
    data = base_config(tmp_path)
    data["hifi_reads"] = [str(reads)]

    assert_invalid(tmp_path, data, "invalid first FASTQ header")


def test_sample_id_with_space_fails(tmp_path: Path) -> None:
    data = base_config(tmp_path)
    data["sample_id"] = "bad sample"

    assert_invalid(tmp_path, data, "sample_id")


def test_sample_id_with_slash_fails(tmp_path: Path) -> None:
    data = base_config(tmp_path)
    data["sample_id"] = "bad/sample"

    assert_invalid(tmp_path, data, "sample_id")


def test_ploidy_zero_fails(tmp_path: Path) -> None:
    data = base_config(tmp_path)
    data["ploidy"] = 0

    assert_invalid(tmp_path, data, "ploidy")


def test_negative_threads_fail(tmp_path: Path) -> None:
    data = base_config(tmp_path)
    data["resources"] = {"max_threads": -1, "max_memory_gb": 16}

    assert_invalid(tmp_path, data, "resources.max_threads")


def test_zero_memory_fails(tmp_path: Path) -> None:
    data = base_config(tmp_path)
    data["resources"] = {"max_threads": 4, "max_memory_gb": 0}

    assert_invalid(tmp_path, data, "resources.max_memory_gb")


def test_retry_budget_above_v1_limit_fails(tmp_path: Path) -> None:
    data = base_config(tmp_path)
    data["agent"] = {"max_retry_rounds": 3, "max_candidates_per_round": 2, "objective": "balanced"}

    assert_invalid(tmp_path, data, "agent.max_retry_rounds")


def test_candidate_budget_above_v1_limit_fails(tmp_path: Path) -> None:
    data = base_config(tmp_path)
    data["agent"] = {"max_retry_rounds": 1, "max_candidates_per_round": 3, "objective": "balanced"}

    assert_invalid(tmp_path, data, "agent.max_candidates_per_round")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_tool_retries", 4),
        ("max_cpu_hours", -1),
        ("max_walltime_hours", -1),
    ],
)
def test_agent_compute_and_tool_budgets_are_bounded(
    tmp_path: Path,
    field: str,
    value: int,
) -> None:
    data = base_config(tmp_path)
    agent = data["agent"]
    assert isinstance(agent, dict)
    agent[field] = value

    assert_invalid(tmp_path, data, f"agent.{field}")


def test_kmer_low_coverage_threshold_out_of_range_fails(tmp_path: Path) -> None:
    data = base_config(tmp_path)
    data["kmer"] = {"k": 21, "low_coverage_peak_threshold": 0}

    assert_invalid(tmp_path, data, "kmer.low_coverage_peak_threshold")


def test_mapping_filter_qscore_out_of_range_fails(tmp_path: Path) -> None:
    data = base_config(tmp_path)
    data["mapping_qc"] = {
        "min_read_length": 1000,
        "min_mean_qscore": 61,
        "coverage_window_size": 10_000,
    }

    assert_invalid(tmp_path, data, "mapping_qc.min_mean_qscore")


def test_outdir_containing_input_fails(tmp_path: Path) -> None:
    reads_dir = tmp_path / "input"
    reads_dir.mkdir()
    reads = write_fastq(reads_dir / "reads.fastq")
    data = base_config(tmp_path)
    data["hifi_reads"] = [str(reads)]
    data["outdir"] = str(tmp_path)

    assert_invalid(tmp_path, data, "would contain input file")


def test_hi_c_field_is_rejected_as_out_of_scope(tmp_path: Path) -> None:
    data = base_config(tmp_path)
    data["hi_c_reads"] = ["hic_R1.fastq.gz", "hic_R2.fastq.gz"]

    assert_invalid(tmp_path, data, "Unsupported V1 field")


def test_ont_field_is_rejected_as_out_of_scope(tmp_path: Path) -> None:
    data = base_config(tmp_path)
    data["ont_reads"] = ["ont.fastq.gz"]

    assert_invalid(tmp_path, data, "Unsupported V1 field")


def test_unknown_extra_field_fails(tmp_path: Path) -> None:
    data = base_config(tmp_path)
    data["unexpected"] = "value"

    assert_invalid(tmp_path, data, "unexpected")


def test_invalid_independent_kmer_reads_fail_fast(tmp_path: Path) -> None:
    invalid = tmp_path / "independent.txt"
    invalid.write_text("not fastq\n")
    data = base_config(tmp_path)
    data["kmer_reads"] = [str(invalid)]

    assert_invalid(tmp_path, data, "kmer_reads")


def test_cli_run_validates_before_workflow_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from typer.testing import CliRunner

    import hifi_agent.cli

    calls: list[Path] = []
    base_data = base_config(tmp_path)
    outdir = Path(str(base_data["outdir"]))

    def fake_run(config: object, *, resume: bool = False) -> NextflowRunResult:
        del config, resume
        reads_manifest = outdir / "00_metadata" / "hifi_reads.list"
        calls.append(reads_manifest)
        return NextflowRunResult(
            command=("nextflow",),
            outdir=outdir,
            reads_manifest=reads_manifest,
        )

    config_path = write_config(tmp_path, base_data)
    monkeypatch.setattr(hifi_agent.cli, "run_phase3_workflow", fake_run)

    result = CliRunner().invoke(hifi_agent.cli.app, ["run", str(config_path)])

    assert result.exit_code == 0
    assert calls == [outdir / "00_metadata" / "hifi_reads.list"]
    assert (outdir / "00_metadata" / "resolved_config.yaml").is_file()
    assert (outdir / "00_metadata" / "input_checksums.tsv").is_file()
