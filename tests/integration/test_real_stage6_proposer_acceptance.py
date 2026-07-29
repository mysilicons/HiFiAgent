import csv
import hashlib
import os
from pathlib import Path
from typing import Any

import pytest

from hifi_agent.rag import DEFAULT_INDEX_PATH, build_knowledge_index, propose_run
from hifi_agent.rag.client import LLMClientResult

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REAL_ACCEPTANCE = os.environ.get("HIFI_AGENT_REAL_ACCEPTANCE") == "1"
RUN_DIR = PROJECT_ROOT / "Data/Candida_albicans/hifiAgent"


class FixedRealContextClient:
    """Deterministic structured response evaluated against genuine Candida facts."""

    model = "fixed-stage6-real-context"

    def __init__(self) -> None:
        self.calls = 0
        self.user_prompt = ""

    def complete_json(self, *, system_prompt: str, user_prompt: str) -> LLMClientResult:
        del system_prompt
        self.calls += 1
        self.user_prompt = user_prompt
        output: dict[str, Any] = {
            "schema_version": "2.0",
            "proposals": [
                {
                    "proposal_id": "real_candida_disable_post_join",
                    "parameters": [
                        {
                            "parameter": "disable_post_join",
                            "value": True,
                            "source_ids": ["hifiasm_parameters"],
                            "metric_ids": ["quast_misassemblies", "contig_n50"],
                            "rationale": (
                                "Reference-supported structural errors justify this bounded "
                                "single-variable candidate."
                            ),
                            "applicability": ["Reference-based PacBio HiFi contig assessment"],
                            "risks": ["Contig N50 may decrease after disabling post-join"],
                            "uncertainty": (
                                "Reference differences may include biological variation."
                            ),
                            "confidence": 0.7,
                        }
                    ],
                    "summary": (
                        "The structured proposal follows the real deterministic Candida decision."
                    ),
                }
            ],
            "global_uncertainties": [
                "Only an executed candidate with homologous post-QC can establish improvement."
            ],
        }
        return LLMClientResult(
            output=output,
            metadata={"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300},
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _verify_real_input_receipt() -> None:
    receipt = RUN_DIR / "00_metadata/input_checksums.tsv"
    with receipt.open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert {row["role"] for row in rows} == {"hifi_reads", "reference_genome"}
    for row in rows:
        path = Path(row["path"])
        assert path.is_file()
        assert path.stat().st_size == int(row["bytes"])
        assert _sha256(path) == row["sha256"]


@pytest.mark.skipif(
    not REAL_ACCEPTANCE,
    reason="set HIFI_AGENT_REAL_ACCEPTANCE=1 for genuine Candida Stage 6 acceptance",
)
def test_real_candida_rules_and_fixed_hybrid_proposals_are_safe(tmp_path: Path) -> None:
    _verify_real_input_receipt()
    if not DEFAULT_INDEX_PATH.is_file():
        build_knowledge_index(output_path=DEFAULT_INDEX_PATH)
    tracked = [
        RUN_DIR / "04_decisions/baseline/rule_decision.json",
        RUN_DIR / "03_post_qc/baseline/assembly_metrics.json",
        RUN_DIR / "01_pre_qc/raw_metrics.json",
    ]
    before = {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in tracked}

    rules = propose_run(
        RUN_DIR,
        index_path=DEFAULT_INDEX_PATH,
        output_dir=tmp_path / "rules_only",
        decision_mode="rules_only",
        max_candidates=1,
    )
    client = FixedRealContextClient()
    hybrid = propose_run(
        RUN_DIR,
        index_path=DEFAULT_INDEX_PATH,
        output_dir=tmp_path / "hybrid",
        decision_mode="hybrid",
        max_candidates=2,
        confirm_medium_high_risk=True,
        client=client,
    )

    assert rules.terminal_status == "CANDIDATES_APPROVED"
    assert rules.llm_status == "NOT_REQUESTED"
    assert len(rules.approved_candidates) == 1
    rule_candidate = rules.approved_candidates[0]
    assert rule_candidate.origin == "rule"
    assert rule_candidate.approved_parameters.disable_post_join is True
    assert "hifiasm_parameters" in rule_candidate.source_ids
    assert "quast_misassemblies" in rule_candidate.metric_ids

    assert client.calls == 1
    assert hybrid.llm_status == "SUCCESS"
    assert len(hybrid.approved_candidates) == 1
    assert hybrid.approved_candidates[0] == rule_candidate
    llm_rejection = next(
        item
        for item in hybrid.rejected_proposals
        if item.proposal_id == "real_candida_disable_post_join"
    )
    assert "PARAMETER_FINGERPRINT_ALREADY_SEEN" in llm_rejection.reason_codes
    assert hybrid.prompt_sha256
    assert hybrid.proposal_output_sha256
    assert hybrid.api_metadata["total_tokens"] == 300
    assert "/data/gw" not in client.user_prompt
    assert all(
        (tmp_path / "hybrid" / name).is_file()
        for name in (
            "proposal_decision.json",
            "retrieval_trace.json",
            "proposal_trace.jsonl",
        )
    )
    assert (tmp_path / "hybrid/context/qc_feature_bundle.json").is_file()
    assert (tmp_path / "hybrid/context/qc_llm_summary.json").is_file()
    assert before == {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in tracked}
