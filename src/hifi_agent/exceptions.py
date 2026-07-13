"""Typed exceptions for predictable CLI and workflow failures."""

from pathlib import Path

from hifi_agent.constants import ExitCode


class HiFiAgentError(Exception):
    """Base class for expected HiFi Agent failures."""

    exit_code: ExitCode = ExitCode.INTERNAL_ERROR


class NotImplementedCommandError(HiFiAgentError):
    """Raised by CLI commands that are registered before their workflow exists."""

    exit_code = ExitCode.NOT_IMPLEMENTED

    def __init__(self, command: str, target: Path) -> None:
        self.command = command
        self.target = target
        super().__init__(f"`hifi-agent {command}` is not implemented yet for {target}.")


class InputValidationError(HiFiAgentError):
    """Raised when user-supplied sample configuration or paths are invalid."""

    exit_code = ExitCode.INPUT_VALIDATION_FAILED


class ToolExecutionError(HiFiAgentError):
    """Raised when an external tool exits unsuccessfully or is unavailable."""

    exit_code = ExitCode.TOOL_EXECUTION_FAILED


class RuleConfigurationError(HiFiAgentError):
    """Raised when expert rules or thresholds violate the audited schema."""

    exit_code = ExitCode.INPUT_VALIDATION_FAILED


class RuleEvaluationError(HiFiAgentError):
    """Raised when a rule decision cannot be produced from supplied run artifacts."""

    exit_code = ExitCode.INSUFFICIENT_EVIDENCE


class AgentStateError(HiFiAgentError):
    """Raised when persisted Agent state is missing, corrupt, or incompatible."""

    exit_code = ExitCode.INTERNAL_ERROR


class IllegalStateTransitionError(AgentStateError):
    """Raised when the controller attempts a transition outside the state graph."""


class LLMProviderError(HiFiAgentError):
    """Raised when the optional LLM provider cannot return a usable response."""

    exit_code = ExitCode.INSUFFICIENT_EVIDENCE


class LLMSafetyError(HiFiAgentError):
    """Raised when structured LLM output violates deterministic safety constraints."""

    exit_code = ExitCode.INSUFFICIENT_EVIDENCE
