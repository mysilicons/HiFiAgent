import json
from pathlib import Path

import pytest

from hifi_agent.agent.models import AssemblyConfig, AssemblyParameters
from hifi_agent.exceptions import ToolExecutionError
from hifi_agent.executors.hifiasm_contract import (
    parse_hifiasm_command,
    parse_hifiasm_parameter_argv,
    render_hifiasm_parameter_argv,
    validate_hifiasm_command_contract,
    write_hifiasm_contract_artifacts,
)
from hifi_agent.executors.nextflow import _append_optional_nextflow_param


def _candidate(**parameter_updates: object) -> AssemblyConfig:
    return AssemblyConfig(
        run_id="candidate_r01_c01",
        input_reads=[Path("reads.fastq.gz")],
        threads=8,
        parameters=AssemblyParameters.model_validate(parameter_updates),
        reason_codes=["TEST_CONTRACT"],
        risk_level="medium",
        retry_kind="PARAMETER_OPTIMIZATION",
        optimization_round=1,
    )


def test_none_hom_cov_is_completely_omitted() -> None:
    argv = render_hifiasm_parameter_argv(AssemblyParameters(hom_cov=None))

    assert "--hom-cov" not in argv
    assert parse_hifiasm_parameter_argv(argv).hom_cov is None


def test_numeric_hom_cov_round_trips_exactly() -> None:
    parameters = AssemblyParameters(hom_cov=37)
    argv = render_hifiasm_parameter_argv(parameters)

    assert argv[argv.index("--hom-cov") + 1] == "37"
    assert parse_hifiasm_parameter_argv(argv) == parameters


@pytest.mark.parametrize(
    ("disabled", "expected"),
    [(False, False), (True, True)],
)
def test_disable_post_join_boolean_has_one_canonical_encoding(
    disabled: bool,
    expected: bool,
) -> None:
    argv = render_hifiasm_parameter_argv(AssemblyParameters(disable_post_join=disabled))

    assert ("-u0" in argv) is expected
    assert parse_hifiasm_parameter_argv(argv).disable_post_join is expected


@pytest.mark.parametrize("value", [None, "", "   "])
def test_optional_nextflow_values_are_omitted(value: object | None) -> None:
    command = ["nextflow", "run", "workflow/main.nf"]

    _append_optional_nextflow_param(command, "--optional", value)

    assert "--optional" not in command


def test_optional_nextflow_real_value_is_preserved() -> None:
    command = ["nextflow"]

    _append_optional_nextflow_param(command, "--expected_genome_size", 10_000_000)

    assert command == ["nextflow", "--expected_genome_size", "10000000"]


@pytest.mark.parametrize(
    "argv",
    [
        ["--hom-cov", "true"],
        ["--hom-cov"],
        ["--unknown", "1"],
        ["-s", "0.5", "-s", "0.4"],
        ["-l", "4"],
    ],
)
def test_illegal_parameter_argv_is_rejected(argv: list[str]) -> None:
    with pytest.raises(ToolExecutionError):
        parse_hifiasm_parameter_argv(argv)


def test_recorded_command_parses_only_whitelisted_parameters() -> None:
    parameters, argv, reads = parse_hifiasm_command(
        "hifiasm -o sample.candidate -t 8 -l 3 -s 0.5 --hom-cov 37 -u0 reads.fastq.gz\n"
    )

    assert parameters == AssemblyParameters(
        purge_level=3,
        purge_similarity=0.5,
        hom_cov=37,
        disable_post_join=True,
    )
    assert argv[0] == "hifiasm"
    assert reads == ("reads.fastq.gz",)


def test_approved_and_realized_contract_writes_all_audit_artifacts(tmp_path: Path) -> None:
    candidate = _candidate(purge_similarity=0.5, disable_post_join=True)
    metadata = tmp_path / "metadata"
    command = metadata / "hifiasm_command.txt"
    metadata.mkdir()
    command.write_text("hifiasm -o sample.candidate_r01_c01 -t 8 -l 3 -s 0.5 -u0 reads.fastq.gz\n")

    result = write_hifiasm_contract_artifacts(candidate, metadata, command_path=command)

    assert result is not None
    assert result.status == "PASS"
    assert result.threads == 8
    assert result.output_prefix == "sample.candidate_r01_c01"
    for name in (
        "requested_config.json",
        "approved_config.json",
        "rendered_argv.json",
        "realized_parameters.json",
        "parameter_contract_check.json",
    ):
        assert (metadata / name).is_file()
    check = json.loads((metadata / "parameter_contract_check.json").read_text())
    assert check["status"] == "PASS"
    assert check["differences"] == []


def test_historical_candida_true_hom_cov_is_detected_and_isolated(tmp_path: Path) -> None:
    candidate = _candidate(disable_post_join=True)
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    command = metadata / "hifiasm_command.txt"
    command.write_text(
        "hifiasm -o Candida_albicans.candidate_r01_c01 -t 480 "
        "-l 3 -s 0.55 --hom-cov true -u0 reads.fastq\n"
    )

    with pytest.raises(ToolExecutionError, match="Invalid value `true`"):
        write_hifiasm_contract_artifacts(candidate, metadata, command_path=command)

    check = json.loads((metadata / "parameter_contract_check.json").read_text())
    assert check["status"] == "FAIL"
    assert check["reason_code"] == "PARAMETER_CONTRACT_VIOLATION"


def test_parameter_drift_is_rejected_even_when_values_are_individually_valid(
    tmp_path: Path,
) -> None:
    candidate = _candidate(purge_similarity=0.5)
    command = tmp_path / "hifiasm_command.txt"
    command.write_text("hifiasm -o candidate -t 8 -l 3 -s 0.45 reads.fastq.gz\n")

    with pytest.raises(ToolExecutionError, match="PARAMETER_CONTRACT_VIOLATION"):
        validate_hifiasm_command_contract(candidate, command)


@pytest.mark.parametrize(
    "command_text",
    [
        "hifiasm -o sample.candidate_r01_c01 -t 4 -l 3 -s 0.55 reads.fastq.gz\n",
        "hifiasm -o sample.wrong_run -t 8 -l 3 -s 0.55 reads.fastq.gz\n",
        "hifiasm -o sample.candidate_r01_c01 -t 8 -l 3 -s 0.55 other.fastq.gz\n",
    ],
)
def test_runtime_threads_prefix_and_reads_are_part_of_contract(
    tmp_path: Path,
    command_text: str,
) -> None:
    candidate = _candidate()
    command = tmp_path / "hifiasm_command.txt"
    command.write_text(command_text)

    with pytest.raises(ToolExecutionError, match="PARAMETER_CONTRACT_VIOLATION"):
        validate_hifiasm_command_contract(candidate, command)
