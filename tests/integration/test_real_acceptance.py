"""Release-only real data and provider gates; no mocks or fixture executables."""

import os
from pathlib import Path

import pytest

from hifi_agent.acceptance import ResolvedDataset, resolve_dataset, verify_real_run
from hifi_agent.live_smoke import verify_live_smoke

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET_ID = "drosophila_melanogaster_srr33554835"
ENABLED = os.environ.get("HIFI_AGENT_REAL_ACCEPTANCE") == "1"

pytestmark = [
    pytest.mark.real_acceptance,
    pytest.mark.skipif(not ENABLED, reason="release-only real acceptance is not enabled"),
]


def _required_path(name: str) -> Path:
    value = os.environ.get(name)
    assert value, f"{name} must be set when real acceptance is enabled"
    path = Path(value).resolve()
    assert path.exists(), f"{name} does not exist: {path}"
    return path


@pytest.fixture(scope="module")
def real_dataset() -> ResolvedDataset:
    return resolve_dataset(PROJECT_ROOT / "benchmark/datasets.yaml", DATASET_ID)


def test_frozen_real_dataset_matches_local_bytes(real_dataset: ResolvedDataset) -> None:
    dataset = real_dataset

    assert dataset.observed_sha256 == dataset.record.sha256
    assert dataset.observed_bytes == dataset.record.bytes


def test_real_baseline_candidate_comparison_and_deep_verification(
    real_dataset: ResolvedDataset,
) -> None:
    result = verify_real_run(_required_path("HIFI_AGENT_REAL_RUN"), real_dataset)

    assert result.status == "PASS"
    assert result.changed_parameter
    assert result.comparison_outcome in {"ACCEPT_CANDIDATE", "KEEP_INCUMBENT"}


def test_live_provider_schema_and_safety_arbiter_receipt() -> None:
    manifest = verify_live_smoke(
        _required_path("HIFI_AGENT_REAL_RUN"),
        _required_path("HIFI_AGENT_LIVE_SMOKE_MANIFEST"),
    )

    assert manifest.status == "PASS"
    assert manifest.provider == "deepseek"
    assert manifest.schema_validation == "PASS"
    assert manifest.safety_arbiter == "PASS"
