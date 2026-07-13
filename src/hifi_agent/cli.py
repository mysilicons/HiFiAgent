"""Command line interface for HiFi Agent."""

from pathlib import Path
from typing import Annotated, NoReturn

import typer

from hifi_agent.config import validate_config_file
from hifi_agent.constants import APP_NAME, __version__
from hifi_agent.exceptions import HiFiAgentError, NotImplementedCommandError
from hifi_agent.executors.nextflow import run_phase3_workflow, run_post_qc_workflow
from hifi_agent.logging import configure_logging, get_console

app = typer.Typer(
    name=APP_NAME,
    help="Constrained PacBio HiFi genome assembly assistant.",
    no_args_is_help=True,
)


def version_callback(show_version: bool) -> None:
    """Print the package version and exit."""
    if show_version:
        typer.echo(f"{APP_NAME} {__version__}")
        raise typer.Exit()


@app.callback()
def cli_callback(
    version: Annotated[
        bool,
        typer.Option("--version", callback=version_callback, help="Show the package version."),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable debug logging."),
    ] = False,
) -> None:
    """Configure global CLI options."""
    configure_logging(verbose=verbose)


def abort_with_error(error: HiFiAgentError) -> NoReturn:
    """Print an expected project error and exit with its normalized code."""
    get_console(stderr=True).print(f"[red]{error}[/red]")
    raise typer.Exit(code=error.exit_code)


@app.command()
def validate(
    config: Annotated[Path, typer.Argument(help="Sample configuration YAML file.")],
) -> None:
    """Validate a sample configuration file."""
    try:
        result = validate_config_file(config)
    except HiFiAgentError as exc:
        abort_with_error(exc)

    console = get_console()
    console.print("[green]Validation passed.[/green]")
    console.print(f"Resolved config: {result.resolved_config}")
    console.print(f"Input checksums: {result.input_checksums}")


@app.command()
def plan(
    config: Annotated[Path, typer.Argument(help="Sample configuration YAML file.")],
) -> None:
    """Build an execution plan without running workflows."""
    abort_with_error(NotImplementedCommandError("plan", config))


@app.command()
def run(
    config: Annotated[Path, typer.Argument(help="Sample configuration YAML file.")],
    resume: Annotated[
        bool,
        typer.Option("--resume", help="Resume a previous Nextflow run when cached tasks exist."),
    ] = False,
) -> None:
    """Run the configured HiFi Agent workflow."""
    try:
        validation = validate_config_file(config)
        result = run_phase3_workflow(validation.config, resume=resume)
    except HiFiAgentError as exc:
        abort_with_error(exc)

    console = get_console()
    console.print("[green]Workflow completed.[/green]")
    console.print(f"Output directory: {result.outdir}")
    console.print(f"Reads manifest: {result.reads_manifest}")


@app.command()
def evaluate(
    run_dir: Annotated[Path, typer.Argument(help="Existing run output directory.")],
) -> None:
    """Evaluate an existing workflow run directory."""
    try:
        result = run_post_qc_workflow(run_dir.resolve())
    except HiFiAgentError as exc:
        abort_with_error(exc)
    console = get_console()
    console.print("[green]Post-assembly evaluation completed.[/green]")
    console.print(
        f"Assembly metrics: {result.outdir / '03_post_qc/baseline/assembly_metrics.json'}"
    )


@app.command()
def report(
    run_dir: Annotated[Path, typer.Argument(help="Existing run output directory.")],
) -> None:
    """Render final reports for an existing run directory."""
    abort_with_error(NotImplementedCommandError("report", run_dir))


def main() -> None:
    """Run the Typer application with normalized project errors."""
    try:
        app()
    except HiFiAgentError as exc:
        get_console(stderr=True).print(f"[red]{exc}[/red]")
        raise typer.Exit(code=exc.exit_code) from exc
