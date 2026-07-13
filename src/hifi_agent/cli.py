"""Command line interface for HiFi Agent."""

from pathlib import Path
from typing import Annotated, NoReturn

import typer

from hifi_agent.agent import AgentController, ExistingRunAgentTools
from hifi_agent.config import validate_config_file
from hifi_agent.constants import APP_NAME, __version__
from hifi_agent.exceptions import HiFiAgentError, NotImplementedCommandError
from hifi_agent.executors.nextflow import run_phase3_workflow, run_post_qc_workflow
from hifi_agent.logging import configure_logging, get_console
from hifi_agent.rules import load_default_rule_engine, load_rule_context, write_rule_decision

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
    console.print(f"Validation receipt: {result.validation_receipt}")


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
def decide(
    run_dir: Annotated[Path, typer.Argument(help="Existing evaluated run directory.")],
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Optional rule-decision JSON path."),
    ] = None,
) -> None:
    """Evaluate the audited Stage 8 expert rules without an LLM."""
    resolved_run_dir = run_dir.resolve()
    decision_path = output or (
        resolved_run_dir / "04_decisions" / "baseline" / "rule_decision.json"
    )
    try:
        context = load_rule_context(resolved_run_dir)
        decision = load_default_rule_engine().evaluate(context)
        written = write_rule_decision(decision, decision_path)
    except HiFiAgentError as exc:
        abort_with_error(exc)
    console = get_console()
    console.print(f"[green]Rule decision: {decision.decision}[/green]")
    console.print(f"Action: {decision.action}")
    console.print(f"Decision record: {written}")


@app.command("agent")
def run_agent(
    run_dir: Annotated[Path, typer.Argument(help="Existing HiFi Agent run directory.")],
    resume: Annotated[
        bool,
        typer.Option("--resume", help="Resume from 05_agent/agent_state.json."),
    ] = False,
) -> None:
    """Run or resume the explicit Stage 9 controller without an LLM."""
    resolved_run_dir = run_dir.resolve()
    config_path = resolved_run_dir / "00_metadata" / "resolved_config.yaml"
    try:
        controller = AgentController(
            resolved_run_dir,
            config_path,
            ExistingRunAgentTools(resolved_run_dir),
        )
        state = controller.run(resume=resume)
    except HiFiAgentError as exc:
        abort_with_error(exc)
    console = get_console()
    console.print(f"[green]Agent terminal outcome: {state.terminal_outcome}[/green]")
    console.print(f"State: {state.state}")
    console.print(f"State file: {controller.store.state_path}")
    console.print(f"Decision trace: {controller.store.trace_path}")


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
