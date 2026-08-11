"""Production assembly execution interfaces."""

from hifi_agent.executors.assembly import AssemblyExecutor, AssemblyWorkflowRunner
from hifi_agent.executors.models import (
    AssemblyInputManifest,
    AttemptCoordinate,
    ExecutionEstimate,
    InputArtifact,
    WorkflowInvocation,
    WorkflowResult,
)
from hifi_agent.executors.nextflow import (
    NextflowAssemblyRunner,
    assembly_inputs_from_run,
    run_pre_qc_workflow,
)

__all__ = [
    "AssemblyExecutor",
    "AssemblyInputManifest",
    "AssemblyWorkflowRunner",
    "AttemptCoordinate",
    "ExecutionEstimate",
    "InputArtifact",
    "NextflowAssemblyRunner",
    "WorkflowInvocation",
    "WorkflowResult",
    "assembly_inputs_from_run",
    "run_pre_qc_workflow",
]
