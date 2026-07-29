import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from hifi_agent.cli import app
from hifi_agent.exceptions import AgentStateError
from hifi_agent.orchestration.history import AttemptHistoryStore, inspect_v1_migration
from hifi_agent.orchestration.models import (
    AttemptIdentity,
    attempt_id,
    candidate_id,
    candidate_run_id,
    round_id,
)
from hifi_agent.schemas.sample import OptimizationConfig, SampleConfig


def _config_file(tmp_path: Path, *, outdir: Path | None = None) -> Path:
    reads = tmp_path / "reads.fastq"
    reads.write_text("@read\nACGT\n+\nIIII\n")
    path = tmp_path / "sample.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "sample_id": "sample",
                "hifi_reads": [str(reads)],
                "outdir": str(outdir or tmp_path / "run"),
                "optimization": {"max_rounds": 3},
            }
        )
    )
    return path


def test_v2_optimization_schema_accepts_three_rounds_and_rejects_four() -> None:
    assert OptimizationConfig(max_rounds=3).max_rounds == 3
    with pytest.raises(ValidationError, match="max_rounds"):
        OptimizationConfig(max_rounds=4)


def test_require_llm_is_only_valid_in_hybrid_mode() -> None:
    assert OptimizationConfig(decision_mode="hybrid", require_llm=True).require_llm is True
    with pytest.raises(ValidationError, match="requires decision_mode=hybrid"):
        OptimizationConfig(decision_mode="rules_only", require_llm=True)


def test_sample_config_has_v2_optimization_defaults(tmp_path: Path) -> None:
    config = SampleConfig(
        sample_id="sample",
        hifi_reads=[tmp_path / "reads.fastq"],
        outdir=tmp_path / "run",
    )

    assert config.optimization.max_rounds == 3
    assert config.optimization.max_candidates_per_round == 1
    assert config.optimization.retain_all_attempts is True


def test_stable_round_candidate_and_attempt_identifiers() -> None:
    assert round_id(1) == "round_01"
    assert candidate_id(2) == "candidate_02"
    assert candidate_run_id(3, 2) == "candidate_r03_c02"
    assert attempt_id(7) == "attempt_007"


def test_attempt_identity_rejects_incoherent_coordinates() -> None:
    with pytest.raises(ValidationError, match="candidate identity"):
        AttemptIdentity(
            run_uuid="0" * 32,
            kind="candidate",
            round_index=2,
            candidate_index=1,
            attempt_index=1,
            run_id="candidate_r01_c01",
            attempt_id="attempt_001",
        )


def test_tool_retry_creates_attempt_002_without_overwriting_attempt_001(
    tmp_path: Path,
) -> None:
    config = _config_file(tmp_path)
    run_dir = tmp_path / "run"
    store = AttemptHistoryStore(run_dir)
    store.initialize("sample", config)
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("first\n")

    first = store.begin_attempt(kind="candidate", round_index=1, candidate_index=1)
    store.complete_attempt(first, artifacts={"post_qc_metrics": artifact})
    second = store.begin_attempt(kind="candidate", round_index=1, candidate_index=1, retry=True)

    assert first.attempt_id == "attempt_001"
    assert second.attempt_id == "attempt_002"
    assert (run_dir / "02_assembly/round_01/candidate_01/attempt_001").is_dir()
    assert (run_dir / "02_assembly/round_01/candidate_01/attempt_002").is_dir()


def test_completed_logical_run_is_idempotently_reused(tmp_path: Path) -> None:
    config = _config_file(tmp_path)
    store = AttemptHistoryStore(tmp_path / "run")
    store.initialize("sample", config)
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("complete\n")
    first = store.begin_attempt(kind="baseline", round_index=0)
    store.complete_attempt(first, artifacts={"post_qc_metrics": artifact})

    reused = store.begin_attempt(kind="baseline", round_index=0)

    assert reused == first
    assert len(store.load_history().attempts) == 1


def test_modified_artifact_fails_checksum_verification(tmp_path: Path) -> None:
    config = _config_file(tmp_path)
    store = AttemptHistoryStore(tmp_path / "run")
    store.initialize("sample", config)
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("original\n")
    attempt = store.begin_attempt(kind="baseline", round_index=0)
    store.complete_attempt(attempt, artifacts={"post_qc_metrics": artifact})

    artifact.write_text("tampered\n")

    with pytest.raises(AgentStateError, match="checksum mismatch"):
        store.verify_attempt(attempt)


def test_modified_manifest_fails_completion_checksum(tmp_path: Path) -> None:
    config = _config_file(tmp_path)
    run_dir = tmp_path / "run"
    store = AttemptHistoryStore(run_dir)
    store.initialize("sample", config)
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("original\n")
    attempt = store.begin_attempt(kind="baseline", round_index=0)
    store.complete_attempt(attempt, artifacts={"post_qc_metrics": artifact})
    manifest = run_dir / "02_assembly/baseline/attempt_001/artifact_manifest.json"
    data = json.loads(manifest.read_text())
    data["status"] = "FAILED"
    manifest.write_text(json.dumps(data))

    with pytest.raises(AgentStateError, match="manifest checksum mismatch"):
        store.verify_attempt(attempt)


def test_concurrent_run_identity_creation_has_exactly_one_winner(tmp_path: Path) -> None:
    config = _config_file(tmp_path)
    run_dir = tmp_path / "run"

    def initialize() -> str:
        try:
            AttemptHistoryStore(run_dir).initialize("sample", config)
        except (AgentStateError, FileExistsError):
            return "rejected"
        return "created"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: initialize(), range(2)))

    assert results.count("created") == 1
    assert results.count("rejected") == 1


def _create_v1_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "v1"
    paths = {
        "00_metadata/resolved_config.yaml": yaml.safe_dump(
            {"sample_id": "legacy", "hifi_reads": ["reads.fastq"], "outdir": str(run_dir)}
        ),
        "00_metadata/validation_receipt.json": "{}\n",
        "01_pre_qc/raw_metrics.json": "{}\n",
        "02_assembly/baseline/metadata/assembly_manifest.json": "{}\n",
        "03_post_qc/baseline/assembly_metrics.json": "{}\n",
    }
    for relative, content in paths.items():
        path = run_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return run_dir


def test_v1_inspection_is_read_only(tmp_path: Path) -> None:
    run_dir = _create_v1_run(tmp_path)
    before = sorted(path.relative_to(run_dir) for path in run_dir.rglob("*"))

    inspection = inspect_v1_migration(run_dir)

    after = sorted(path.relative_to(run_dir) for path in run_dir.rglob("*"))
    assert inspection.mode == "DRY_RUN_READ_ONLY"
    assert inspection.sample_id == "legacy"
    assert before == after
    assert not (run_dir / "05_agent/v2").exists()


def test_migrate_v1_cli_defaults_to_dry_run_and_writes_nothing(tmp_path: Path) -> None:
    run_dir = _create_v1_run(tmp_path)
    before = sorted(path.relative_to(run_dir) for path in run_dir.rglob("*"))

    result = CliRunner().invoke(app, ["migrate-v1", str(run_dir)])

    after = sorted(path.relative_to(run_dir) for path in run_dir.rglob("*"))
    assert result.exit_code == 0
    assert "no files were written" in result.stdout
    assert before == after


def test_migrate_v1_execute_is_explicitly_rejected(tmp_path: Path) -> None:
    run_dir = _create_v1_run(tmp_path)

    result = CliRunner().invoke(app, ["migrate-v1", str(run_dir), "--execute"])

    assert result.exit_code != 0
    assert "not implemented" in result.stderr
