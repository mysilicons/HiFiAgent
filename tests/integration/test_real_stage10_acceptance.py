import os
from pathlib import Path

import pytest

from hifi_agent.rag import build_knowledge_index, explain_run
from hifi_agent.rag.client import DeepSeekClient
from hifi_agent.rag.indexer import DEFAULT_INDEX_PATH
from hifi_agent.rag.models import ExplanationBundle, RagComparison, RagTraceEvent
from hifi_agent.rag.safety import validate_llm_explanation
from hifi_agent.rules.models import RuleDecision

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REAL_ACCEPTANCE = os.environ.get("HIFI_AGENT_REAL_ACCEPTANCE") == "1"
REAL_LLM_ACCEPTANCE = os.environ.get("HIFI_AGENT_REAL_LLM_ACCEPTANCE") == "1"
VERIFY_RETAINED_LLM = os.environ.get("HIFI_AGENT_VERIFY_RETAINED_LLM") == "1"


@pytest.mark.skipif(
    not REAL_ACCEPTANCE,
    reason="set HIFI_AGENT_REAL_ACCEPTANCE=1 to verify retained real-data artifacts",
)
def test_real_document_index_and_candida_rules_only_rag() -> None:
    index = build_knowledge_index(output_path=DEFAULT_INDEX_PATH)
    run_dir = PROJECT_ROOT / "results" / "Candida_albicans_phase6"

    bundle = explain_run(run_dir, index_path=DEFAULT_INDEX_PATH, enable_llm=False)

    assert len(index.sources) == 16
    assert len(index.chunks) >= 300
    assert bundle.llm_status == "DISABLED"
    assert bundle.rule_facts.decision == "STOP"
    assert bundle.rule_facts.action == "REVIEW_GENOME_SIZE_ESTIMATE"
    assert bundle.explanation.recommended_action == "STOP_AND_REVIEW"
    assert "hifiasm_faq" in {hit.source_id for hit in bundle.retrieval_evidence}
    assert "quast_manual" in {hit.source_id for hit in bundle.retrieval_evidence}
    comparison = RagComparison.model_validate_json(
        (run_dir / "04_decisions/baseline/rag_comparison.json").read_text()
    )
    assert comparison.safety_status == "PASS"
    assert comparison.decision_changed is False


@pytest.mark.skipif(
    not REAL_LLM_ACCEPTANCE or not os.environ.get("DEEPSEEK_API_KEY"),
    reason="set HIFI_AGENT_REAL_LLM_ACCEPTANCE=1 and DEEPSEEK_API_KEY for real API acceptance",
)
def test_real_deepseek_structured_explanation_is_safe_and_sourced() -> None:
    run_dir = PROJECT_ROOT / "results" / "Candida_albicans_phase6"
    if not DEFAULT_INDEX_PATH.is_file():
        build_knowledge_index(output_path=DEFAULT_INDEX_PATH)

    bundle = explain_run(
        run_dir,
        index_path=DEFAULT_INDEX_PATH,
        enable_llm=True,
        client=DeepSeekClient.from_environment(),
    )

    assert bundle.llm_status == "SUCCESS"
    assert bundle.provider == "deepseek"
    assert bundle.model == "deepseek-v4-pro"
    assert bundle.explanation.recommended_action == "STOP_AND_REVIEW"
    assert bundle.explanation.parameter_explanations == []
    assert bundle.explanation.confidence <= bundle.rule_facts.confidence
    assert "80%" not in bundle.explanation.explanation
    assert "NUMERIC_UNITS_AND_REASON_SEMANTICS_GROUNDED" in bundle.safety_checks
    cited_tools = {
        hit.tool
        for hit in bundle.retrieval_evidence
        if hit.source_id in bundle.explanation.source_ids
    }
    assert cited_tools - {"HiFiAgent"}
    assert set(bundle.explanation.source_ids) <= {
        hit.source_id for hit in bundle.retrieval_evidence
    }
    trace_path = run_dir / "04_decisions/baseline/rag_decision_trace.jsonl"
    trace = RagTraceEvent.model_validate_json(trace_path.read_text().splitlines()[-1])
    assert trace.llm_status == "SUCCESS"
    assert trace.source_ids


@pytest.mark.skipif(
    not VERIFY_RETAINED_LLM,
    reason="set HIFI_AGENT_VERIFY_RETAINED_LLM=1 to audit the retained real API artifact",
)
def test_retained_real_deepseek_artifact_revalidates_without_network() -> None:
    run_dir = PROJECT_ROOT / "results" / "Candida_albicans_phase6"
    decision_dir = run_dir / "04_decisions" / "baseline"
    bundle = ExplanationBundle.model_validate_json((decision_dir / "explanation.json").read_text())
    decision = RuleDecision.model_validate_json((decision_dir / "rule_decision.json").read_text())

    checks = validate_llm_explanation(
        bundle.explanation,
        decision=decision,
        hits=bundle.retrieval_evidence,
    )

    assert bundle.llm_status == "SUCCESS"
    assert bundle.model == "deepseek-v4-pro"
    assert checks == bundle.safety_checks
    assert bundle.explanation.confidence <= decision.confidence
    assert "80%" not in bundle.explanation.explanation
    trace = RagTraceEvent.model_validate_json(
        (decision_dir / "rag_decision_trace.jsonl").read_text().splitlines()[-1]
    )
    assert trace.llm_status == "SUCCESS"
    assert trace.model == bundle.model
    assert set(trace.source_ids) >= set(bundle.explanation.source_ids)
