"""Command-line interface for the production assembly workflow."""

from pathlib import Path
from typing import Annotated, Literal, NoReturn

import typer

from hifi_agent.acceptance import (
    build_evidence_bundle,
    resolve_dataset,
    verify_real_run,
)
from hifi_agent.config import validate_config_file
from hifi_agent.constants import APP_NAME, __version__
from hifi_agent.exceptions import HiFiAgentError
from hifi_agent.live_smoke import run_live_smoke
from hifi_agent.logging import configure_logging, get_console
from hifi_agent.orchestration.bootstrap import write_bootstrap_failure
from hifi_agent.orchestration.controller import RunCoordinator
from hifi_agent.orchestration.environment import (
    require_environment_preflight,
    run_environment_preflight,
)
from hifi_agent.orchestration.runtime_config import DecisionMode, resolve_runtime_config
from hifi_agent.orchestration.verifier import require_verification_success, verify_run
from hifi_agent.reporting.models import FinalSummary

app = typer.Typer(
    name=APP_NAME,
    help=(
        "Constrained PacBio HiFi genome assembly assistant. "
        "Advanced options are explicitly labeled."
    ),
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
        typer.Option("--version", callback=version_callback, help="Show the package release."),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable debug logging."),
    ] = False,
) -> None:
    """Configure global CLI options."""
    configure_logging(verbose=verbose)


def abort_with_error(error: HiFiAgentError) -> NoReturn:
    """Print an expected failure and use the public exit-code contract."""
    get_console(stderr=True).print(f"[red]{error}[/red]")
    raise typer.Exit(code=int(error.exit_code))


@app.command()
def validate(
    config: Annotated[Path, typer.Argument(help="Species/sample YAML file.")],
) -> None:
    """Validate inputs and materialize metadata receipts."""
    try:
        result = validate_config_file(config)
    except HiFiAgentError as exc:
        abort_with_error(exc)
    console = get_console()
    console.print("[green]Validation passed.[/green]")
    console.print(f"Resolved config: {result.resolved_config}")
    console.print(f"Input manifest: {result.input_manifest}")
    console.print(f"Validation receipt: {result.validation_receipt}")


@app.command()
def plan(
    config: Annotated[Path, typer.Argument(help="Species/sample YAML file.")],
    decision_mode: Annotated[
        Literal["rules_only", "hybrid", "llm_disabled"] | None,
        typer.Option("--decision-mode", help="Advanced: audited decision-mode override."),
    ] = None,
) -> None:
    """Validate configuration/environment and print a read-only plan."""
    try:
        runtime = resolve_runtime_config(
            config,
            decision_mode_override=decision_mode,
            write_outputs=False,
        )
        environment = run_environment_preflight(runtime.effective.sample)
        require_environment_preflight(environment)
    except HiFiAgentError as exc:
        abort_with_error(exc)
    console = get_console()
    console.print("[green]Plan and environment preflight passed.[/green]")
    console.print(runtime.plan().model_dump_json(indent=2))
    console.print(f"Environment status: {environment.status}")
    console.print("No run artifacts were written.")


@app.command()
def assemble(
    config: Annotated[Path, typer.Argument(help="Species/sample YAML file.")],
    resume: Annotated[
        bool,
        typer.Option(
            "--resume",
            help="Advanced: force resume when the shared runtime uses explicit mode.",
        ),
    ] = False,
    decision_mode: Annotated[
        Literal["rules_only", "hybrid", "llm_disabled"] | None,
        typer.Option("--decision-mode", help="Advanced: audited decision-mode override."),
    ] = None,
    confirm_medium_high_risk: Annotated[
        bool,
        typer.Option(
            "--confirm-medium-high-risk",
            help="Advanced: authorize candidates approved by the safety arbiter.",
        ),
    ] = False,
) -> None:
    """Run the production coordinator through a terminal report."""
    try:
        result = RunCoordinator(
            config,
            decision_mode_override=decision_mode,
            confirm_medium_high_risk=confirm_medium_high_risk,
        ).run(resume=resume)
    except HiFiAgentError as exc:
        if not resume and not _configured_identity_exists(config, decision_mode):
            write_bootstrap_failure(config, exc, stage="CONTROLLER_BOOTSTRAP")
        abort_with_error(exc)
    console = get_console()
    console.print("[green]Coordinator reached a reported terminal state.[/green]")
    console.print(f"Run directory: {result.run_dir}")
    console.print(f"Control state: {result.state.state.value}")
    console.print(f"Outcome: {result.state.terminal_outcome}")
    console.print(
        "Baseline attempt: "
        f"{result.baseline_attempt.attempt_id if result.baseline_attempt else 'NOT_AVAILABLE'}"
    )
    console.print(f"Report: {result.report_bundle.markdown}")
    console.print(f"Verify: hifi-agent verify-run {result.run_dir} --deep")
    summary = result.report_bundle.summary.read_text()
    exit_code = FinalSummary.model_validate_json(summary).process_exit_code
    if exit_code:
        raise typer.Exit(code=exit_code)


def _configured_identity_exists(config: Path, decision_mode: DecisionMode | None) -> bool:
    """Avoid writing bootstrap diagnostics into an already identified auto-resume run."""
    try:
        runtime = resolve_runtime_config(
            config,
            decision_mode_override=decision_mode,
            write_outputs=False,
        )
    except HiFiAgentError:
        return False
    return (runtime.effective.sample.outdir / "00_metadata/run_identity.json").is_file()


@app.command("verify-run")
def verify_run_command(
    run_dir: Annotated[Path, typer.Argument(help="Existing run directory.")],
    deep: Annotated[
        bool,
        typer.Option("--deep", help="Re-hash all attempt inventory artifacts."),
    ] = False,
    rag_index: Annotated[
        Path | None,
        typer.Option(
            "--rag-index",
            help="Advanced verification: override the frozen RAG index snapshot path.",
        ),
    ] = None,
) -> None:
    """Read-only verification of identity, journal, budgets, and attempts."""
    report = verify_run(run_dir, deep=deep, rag_index=rag_index)
    get_console().print(report.model_dump_json(indent=2))
    try:
        require_verification_success(report)
    except HiFiAgentError as exc:
        abort_with_error(exc)


@app.command("check-dataset")
def check_dataset(
    registry: Annotated[Path, typer.Argument(help="Versioned dataset registry YAML.")],
    dataset_id: Annotated[str, typer.Argument(help="Dataset identifier in the registry.")],
) -> None:
    """Resolve and fully hash one external real-data input."""
    try:
        resolved = resolve_dataset(registry, dataset_id)
    except HiFiAgentError as exc:
        abort_with_error(exc)
    get_console().print(resolved.model_dump_json(indent=2))


@app.command("verify-real")
def verify_real(
    run_dir: Annotated[Path, typer.Argument(help="Completed real run directory.")],
    registry: Annotated[Path, typer.Argument(help="Versioned dataset registry YAML.")],
    dataset_id: Annotated[str, typer.Argument(help="Dataset identifier in the registry.")],
) -> None:
    """Apply strict biological run, contract, comparator, and deep-verification gates."""
    try:
        dataset = resolve_dataset(registry, dataset_id)
        result = verify_real_run(run_dir, dataset)
    except HiFiAgentError as exc:
        abort_with_error(exc)
    get_console().print(result.model_dump_json(indent=2))


@app.command("live-smoke")
def live_smoke(
    run_dir: Annotated[Path, typer.Argument(help="Completed real run directory.")],
    output_dir: Annotated[Path, typer.Argument(help="New directory for secret-free receipts.")],
) -> None:
    """Advanced: call the live provider once against a real governed round context."""
    try:
        manifest = run_live_smoke(run_dir, output_dir)
    except HiFiAgentError as exc:
        abort_with_error(exc)
    get_console().print(f"Live provider smoke passed: {manifest}")


@app.command("build-evidence")
def build_evidence(
    run_dir: Annotated[Path, typer.Argument(help="Completed real run directory.")],
    registry: Annotated[Path, typer.Argument(help="Versioned dataset registry YAML.")],
    dataset_id: Annotated[str, typer.Argument(help="Dataset identifier in the registry.")],
    source_config: Annotated[Path, typer.Option(help="Committed source sample config.")],
    wheel: Annotated[Path, typer.Option(help="Wheel built from the accepted commit.")],
    live_manifest: Annotated[Path, typer.Option(help="Passed live-smoke manifest.")],
    real_suite_report: Annotated[Path, typer.Option(help="JUnit XML from the enabled real suite.")],
    output_dir: Annotated[Path, typer.Option(help="New evidence bundle directory.")],
) -> None:
    """Build a release evidence bundle after every real gate has passed."""
    try:
        manifest = build_evidence_bundle(
            run_dir=run_dir,
            registry_path=registry,
            dataset_id=dataset_id,
            source_config=source_config,
            wheel_path=wheel,
            live_smoke_manifest=live_manifest,
            real_suite_report=real_suite_report,
            output_dir=output_dir,
        )
    except HiFiAgentError as exc:
        abort_with_error(exc)
    get_console().print(f"Evidence bundle passed: {manifest}")


def main() -> None:
    """Console-script entry point."""
    app()
