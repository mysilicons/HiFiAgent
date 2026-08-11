"""Project-wide constants."""

from enum import IntEnum
from importlib.metadata import PackageNotFoundError, version

APP_NAME = "hifi-agent"
try:
    __version__ = version(APP_NAME)
except PackageNotFoundError:
    __version__ = "unknown"


class ExitCode(IntEnum):
    """Process exit codes documented by the public CLI contract."""

    OK = 0
    INPUT_VALIDATION_FAILED = 2
    ACTION_REQUIRED = 3
    TOOL_EXECUTION_FAILED = 4
    REQUIRED_EXTERNAL_SERVICE_FAILED = 5
    INTERNAL_ERROR = 4
