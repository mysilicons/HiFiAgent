"""Logging and console helpers."""

import logging

from rich.console import Console
from rich.logging import RichHandler

LOG_FORMAT = "%(message)s"
DATE_FORMAT = "[%Y-%m-%d %H:%M:%S]"


def configure_logging(*, verbose: bool = False) -> None:
    """Configure process logging once for CLI commands."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        datefmt=DATE_FORMAT,
        handlers=[RichHandler(rich_tracebacks=True, markup=True)],
        force=True,
    )


def get_console(*, stderr: bool = False) -> Console:
    """Return a Rich console for user-facing CLI output."""
    return Console(stderr=stderr)
