"""Project-wide constants."""

from enum import IntEnum

APP_NAME = "hifi-agent"
__version__ = "0.1.0"


class ExitCode(IntEnum):
    """Process exit codes used by the HiFi Agent CLI."""

    OK = 0
    USAGE_ERROR = 2
    NOT_IMPLEMENTED = 10
    INPUT_VALIDATION_FAILED = 20
    TOOL_EXECUTION_FAILED = 30
    INSUFFICIENT_EVIDENCE = 40
    INTERNAL_ERROR = 70
