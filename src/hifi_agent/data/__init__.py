"""Paths to immutable runtime resources shipped with the package."""

from pathlib import Path

RESOURCE_ROOT = Path(__file__).resolve().parent
WORKFLOW_ROOT = RESOURCE_ROOT / "workflow"
WORKFLOW_ENTRY = WORKFLOW_ROOT / "main.nf"
WORKFLOW_CONFIG = WORKFLOW_ROOT / "nextflow.config"
COMPARISON_POLICY = RESOURCE_ROOT / "comparison_policy.yaml"
KNOWLEDGE_INDEX = RESOURCE_ROOT / "knowledge/index.json"

__all__ = [
    "COMPARISON_POLICY",
    "KNOWLEDGE_INDEX",
    "RESOURCE_ROOT",
    "WORKFLOW_CONFIG",
    "WORKFLOW_ENTRY",
    "WORKFLOW_ROOT",
]
