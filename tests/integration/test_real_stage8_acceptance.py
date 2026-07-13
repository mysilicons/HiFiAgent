import os
from pathlib import Path

import pytest

from hifi_agent.rules import load_default_rule_engine, load_rule_context
from hifi_agent.rules.models import WHITELISTED_PARAMETERS

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REAL_ACCEPTANCE = os.environ.get("HIFI_AGENT_REAL_ACCEPTANCE") == "1"

pytestmark = pytest.mark.skipif(
    not REAL_ACCEPTANCE,
    reason="set HIFI_AGENT_REAL_ACCEPTANCE=1 to verify retained real-data artifacts",
)


def test_real_candida_stage8_decision_is_safe_and_deterministic() -> None:
    run_dir = PROJECT_ROOT / "results" / "Candida_albicans_phase6"
    context = load_rule_context(run_dir)
    engine = load_default_rule_engine()

    first = engine.evaluate(context)
    second = engine.evaluate(context)

    assert first == second
    assert first.decision == "STOP"
    assert first.action == "REVIEW_GENOME_SIZE_ESTIMATE"
    assert first.candidates == []
    assert "ASM_SIZE_LARGE_DUPLICATION_LOW_REVIEW" in first.matched_rule_ids
    size_ratio = first.evidence["assembly_size_ratio"]
    duplicated = first.evidence["busco_duplicated"]
    assert isinstance(size_ratio, int | float)
    assert not isinstance(size_ratio, bool)
    assert isinstance(duplicated, int | float)
    assert not isinstance(duplicated, bool)
    assert size_ratio > 1.25
    assert duplicated <= 5.0
    for candidate in first.candidates:
        assert set(candidate.parameters.model_dump(exclude_none=True)) <= WHITELISTED_PARAMETERS
