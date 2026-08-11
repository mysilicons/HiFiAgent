"""Typed exceptions for predictable CLI and workflow failures."""

from hifi_agent.constants import ExitCode


class HiFiAgentError(Exception):
    """Base class for expected HiFi Agent failures."""

    exit_code: ExitCode = ExitCode.INTERNAL_ERROR


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

    exit_code = ExitCode.ACTION_REQUIRED


class AgentStateError(HiFiAgentError):
    """Raised when persisted Agent state is missing, corrupt, or incompatible."""

    exit_code = ExitCode.INTERNAL_ERROR


class IllegalStateTransitionError(AgentStateError):
    """Raised when the controller attempts a transition outside the state graph."""


class LLMProviderError(HiFiAgentError):
    """Raised when the optional LLM provider cannot return a usable response."""

    exit_code = ExitCode.REQUIRED_EXTERNAL_SERVICE_FAILED


class LLMSafetyError(HiFiAgentError):
    """Raised when structured LLM output violates deterministic safety constraints."""

    exit_code = ExitCode.ACTION_REQUIRED


class InterruptedExecutionError(HiFiAgentError):
    """Raised when an attempt may be resumed in the same workspace."""

    exit_code = ExitCode.TOOL_EXECUTION_FAILED
