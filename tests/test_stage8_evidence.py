import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from hifi_agent.agent.models import AssemblyConfig, AssemblyParameters
from hifi_agent.exceptions import InputValidationError
from hifi_agent.executors.candidate import CandidateExecutionReceipt
from hifi_agent.optimization.evidence import (
    load_baseline_comparable,
    load_stage7_comparable,
)
from hifi_agent.orchestration.models import AttemptIdentity
from hifi_agent.schemas.metrics import AssemblyMetrics


def _metrics(run_id: str) -> AssemblyMetrics:
    return AssemblyMetrics(
        run_id=run_id,
        contig_n50=1_000_000,
        busco_complete=98.0,
        kmer_completeness=95.0,
        kmer_qv=30.0,
        mapped_read_fraction=0.99,
        coverage_cv=0.3,
    )


def test_load_baseline_and_stage7_comparable_evidence(tmp_path: Path) -> None:
    source = tmp_path / "source"
    reads = tmp_path / "reads.fastq"
    reads.write_text("@r\nAC\n+\nII\n")
    config = {
        "sample_id": "sample",
        "hifi_reads": [str(reads)],
        "outdir": str(source),
        "resources": {"max_threads": 8, "max_memory_gb": 32},
    }
    config_path = source / "00_metadata/resolved_config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(yaml.safe_dump(config))
    baseline_metrics = source / "03_post_qc/baseline/assembly_metrics.json"
    baseline_manifest = source / "02_assembly/baseline/metadata/assembly_manifest.json"
    baseline_metrics.parent.mkdir(parents=True)
    baseline_manifest.parent.mkdir(parents=True)
    baseline_metrics.write_text(_metrics("baseline").model_dump_json())
    baseline_manifest.write_text(json.dumps({"cpu_seconds": 3600, "real_time_seconds": 1800}))

    baseline = load_baseline_comparable(source)

    assert baseline.run_id == "baseline"
    assert baseline.cpu_hours == 1.0
    assert baseline.walltime_hours == 0.5
    assert baseline.parameter_contract_status == "PASS"

    attempt_dir = tmp_path / "attempt_001"
    workflow = attempt_dir / "workflow"
    run_id = "candidate_r01_c01"
    assembly = workflow / f"02_assembly/{run_id}/metadata"
    post_qc = workflow / f"03_post_qc/{run_id}"
    assembly.mkdir(parents=True)
    post_qc.mkdir(parents=True)
    candidate_config = AssemblyConfig(
        run_id=run_id,
        input_reads=[reads],
        threads=8,
        parameters=AssemblyParameters(disable_post_join=True),
        reason_codes=["TEST"],
        risk_level="medium",
        retry_kind="PARAMETER_OPTIMIZATION",
        optimization_round=1,
    )
    (assembly / "approved_config.json").write_text(candidate_config.model_dump_json())
    (assembly / "parameter_contract_check.json").write_text('{"status": "PASS"}')
    (assembly / "assembly_manifest.json").write_text(
        '{"cpu_seconds": 7200, "real_time_seconds": 3600}'
    )
    (post_qc / "assembly_metrics.json").write_text(_metrics(run_id).model_dump_json())
    receipt = CandidateExecutionReceipt(
        status="COMPLETED",
        attempt=AttemptIdentity(
            run_uuid="a" * 32,
            kind="candidate",
            round_index=1,
            candidate_index=1,
            attempt_index=1,
            run_id=run_id,
            attempt_id="attempt_001",
        ),
        source_run_dir=source,
        workflow_run_dir=workflow,
        approved_candidate_id="candidate",
        parameter_fingerprint="b" * 64,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        resume_requested=False,
    )
    (attempt_dir / "stage7_execution.json").write_text(receipt.model_dump_json())

    candidate = load_stage7_comparable(attempt_dir)

    assert candidate.run_id == run_id
    assert candidate.attempt_id == "attempt_001"
    assert candidate.config.parameters.disable_post_join is True
    assert candidate.cpu_hours == 2.0
    assert candidate.walltime_hours == 1.0


def test_invalid_manifest_resource_usage_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    config_path = source / "00_metadata/resolved_config.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        yaml.safe_dump(
            {
                "sample_id": "sample",
                "hifi_reads": [str(tmp_path / "reads.fastq")],
                "outdir": str(source),
            }
        )
    )
    metrics = source / "03_post_qc/baseline/assembly_metrics.json"
    manifest = source / "02_assembly/baseline/metadata/assembly_manifest.json"
    metrics.parent.mkdir(parents=True)
    manifest.parent.mkdir(parents=True)
    metrics.write_text(_metrics("baseline").model_dump_json())
    manifest.write_text('{"cpu_seconds": true, "real_time_seconds": 1}')

    with pytest.raises(InputValidationError, match="cpu_seconds"):
        load_baseline_comparable(source)
