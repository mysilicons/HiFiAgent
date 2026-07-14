"""Command line interface for HiFi Agent."""

from pathlib import Path
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from hifi_agent.agent import AgentController, AssemblyConfig, ExistingRunAgentTools
from hifi_agent.benchmarking import run_benchmark
from hifi_agent.config import validate_config_file
from hifi_agent.constants import APP_NAME, __version__
from hifi_agent.exceptions import (
    HiFiAgentError,
    NotImplementedCommandError,
    RuleEvaluationError,
)
from hifi_agent.executors.nextflow import (
    run_candidate_workflow,
    run_phase3_workflow,
    run_post_qc_workflow,
)
from hifi_agent.logging import configure_logging, get_console
from hifi_agent.optimization import (
    DEFAULT_STAGE11_SCENARIO,
    run_stage11_optimization,
    synthesize_candida_stage11_scenario,
)
from hifi_agent.rag import DEFAULT_INDEX_PATH, build_knowledge_index, explain_run
from hifi_agent.reporting import (
    DEFAULT_SYNTHETIC_SCENARIO,
    render_final_report,
    synthesize_candida_quality_regression,
)
from hifi_agent.rules import load_default_rule_engine, load_rule_context, write_rule_decision
from hifi_agent.schemas.metrics import AssemblyMetrics

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


@app.command("rag-index")
def rag_index(
    output: Annotated[
        Path,
        typer.Option("--output", help="Local full-text index JSON path."),
    ] = DEFAULT_INDEX_PATH,
) -> None:
    """Build the local provenance-preserving Stage 10 knowledge index."""
    try:
        index = build_knowledge_index(output_path=output.resolve())
    except HiFiAgentError as exc:
        abort_with_error(exc)
    console = get_console()
    console.print("[green]Knowledge index built.[/green]")
    console.print(f"Sources: {len(index.sources)}")
    console.print(f"Chunks: {len(index.chunks)}")
    console.print(f"Index: {output.resolve()}")


@app.command("explain")
def explain_decision(
    run_dir: Annotated[Path, typer.Argument(help="Existing Stage 8/9 run directory.")],
    index: Annotated[
        Path,
        typer.Option("--index", help="Local RAG index JSON path."),
    ] = DEFAULT_INDEX_PATH,
    llm: Annotated[
        bool,
        typer.Option("--llm/--no-llm", help="Enable or disable DeepSeek explanation."),
    ] = True,
) -> None:
    """Produce a constrained rules+RAG explanation and safety comparison."""
    resolved_run_dir = run_dir.resolve()
    try:
        bundle = explain_run(
            resolved_run_dir,
            index_path=index.resolve(),
            enable_llm=llm,
        )
    except HiFiAgentError as exc:
        abort_with_error(exc)
    output_dir = resolved_run_dir / "04_decisions" / "baseline"
    console = get_console()
    console.print(f"[green]Explanation status: {bundle.llm_status}[/green]")
    console.print(f"Recommended action: {bundle.explanation.recommended_action}")
    console.print(f"Retrieved sources: {len({hit.source_id for hit in bundle.retrieval_evidence})}")
    console.print(f"Explanation: {output_dir / 'explanation.json'}")
    console.print(f"RAG comparison: {output_dir / 'rag_comparison.json'}")


@app.command("synthesize-stage11-anomaly")
def synthesize_stage11_anomaly(
    run_dir: Annotated[
        Path,
        typer.Argument(help="Real Candida run directory used as the Stage 11 source."),
    ],
    output: Annotated[
        Path,
        typer.Option("--output", help="Stage 11 synthetic closed-loop scenario JSON."),
    ] = DEFAULT_STAGE11_SCENARIO,
) -> None:
    """Create the genuine-Candida-derived Stage 11 acceptance anomaly."""
    try:
        scenario = synthesize_candida_stage11_scenario(run_dir.resolve(), output.resolve())
    except HiFiAgentError as exc:
        abort_with_error(exc)
    console = get_console()
    console.print("[yellow]Stage 11 synthetic anomaly created.[/yellow]")
    console.print(scenario.disclaimer)
    console.print(f"Scenario: {output.resolve()}")


@app.command()
def optimize(
    run_dir: Annotated[Path, typer.Argument(help="Existing run output directory.")],
    scenario: Annotated[
        Path | None,
        typer.Option("--scenario", help="Explicitly synthetic Stage 11 scenario JSON."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", help="Defaults to RUN_DIR/05_agent/optimization."),
    ] = None,
    execute: Annotated[
        bool,
        typer.Option("--execute", help="Execute authorized real candidate workflows."),
    ] = False,
    confirm_medium_high_risk: Annotated[
        bool,
        typer.Option(
            "--confirm-medium-high-risk",
            help="Explicitly authorize medium-high candidate execution.",
        ),
    ] = False,
) -> None:
    """Run one bounded Stage 11 candidate planning and comparison round."""
    resolved_run = run_dir.resolve()

    def _execute_candidate(candidate: AssemblyConfig) -> AssemblyMetrics:
        run_candidate_workflow(resolved_run, candidate)
        metrics_path = resolved_run / "03_post_qc" / candidate.run_id / "assembly_metrics.json"
        return AssemblyMetrics.model_validate_json(metrics_path.read_text())

    try:
        result = run_stage11_optimization(
            resolved_run,
            scenario_path=scenario.resolve() if scenario else None,
            output_dir=output_dir.resolve() if output_dir else None,
            executor=_execute_candidate if execute else None,
            confirm_medium_high_risk=confirm_medium_high_risk,
        )
    except (HiFiAgentError, ValidationError, OSError) as exc:
        abort_with_error(RuleEvaluationError(f"Stage 11 optimization failed: {exc}"))
    destination = (output_dir or resolved_run / "05_agent/optimization").resolve()
    console = get_console()
    console.print(f"[green]Stage 11 outcome: {result.outcome}[/green]")
    console.print(f"Selected run: {result.selected_run_id or 'NONE'}")
    console.print(f"Comparison: {destination / 'comparison.tsv'}")


@app.command("synthesize-report-anomaly")
def synthesize_report_anomaly(
    run_dir: Annotated[
        Path,
        typer.Argument(help="Real Candida run directory used as the synthesis source."),
    ],
    output: Annotated[
        Path,
        typer.Option("--output", help="Synthetic report scenario JSON path."),
    ] = DEFAULT_SYNTHETIC_SCENARIO,
) -> None:
    """Create the report-only Candida quality-regression acceptance scenario."""
    try:
        scenario = synthesize_candida_quality_regression(
            run_dir.resolve(),
            output.resolve(),
        )
    except HiFiAgentError as exc:
        abort_with_error(exc)
    console = get_console()
    console.print("[yellow]Synthetic report scenario created.[/yellow]")
    console.print(scenario.disclaimer)
    console.print(f"Scenario: {output.resolve()}")


@app.command()
def report(
    run_dir: Annotated[Path, typer.Argument(help="Existing run output directory.")],
    output_dir: Annotated[
        Path | None,
        typer.Option(
            "--output-dir", help="Report output directory; defaults to RUN_DIR/05_report."
        ),
    ] = None,
    scenario: Annotated[
        Path | None,
        typer.Option("--scenario", help="Optional explicitly synthetic scenario JSON."),
    ] = None,
    show_absolute_paths: Annotated[
        bool,
        typer.Option(
            "--show-absolute-paths",
            help="Disable default sensitive-path redaction.",
        ),
    ] = False,
) -> None:
    """Render final reports for an existing run directory."""
    try:
        outputs = render_final_report(
            run_dir.resolve(),
            output_dir=output_dir.resolve() if output_dir else None,
            scenario_path=scenario.resolve() if scenario else None,
            redact_paths=not show_absolute_paths,
        )
    except HiFiAgentError as exc:
        abort_with_error(exc)
    console = get_console()
    console.print("[green]Final report rendered.[/green]")
    console.print(f"Markdown: {outputs.markdown}")
    console.print(f"Summary JSON: {outputs.summary_json}")
    console.print(f"Comparison: {outputs.comparison_tsv}")


@app.command()
def benchmark(
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Stage 13 benchmark artifact directory."),
    ] = Path("benchmark/reports"),
    real_run_dir: Annotated[
        Path,
        typer.Option("--real-run-dir", help="Retained public Candida workflow run."),
    ] = Path("results/Candida_albicans_phase6"),
    fixtures_only: Annotated[
        bool,
        typer.Option(
            "--fixtures-only",
            help="Run the portable logic demo without requiring retained real artifacts.",
        ),
    ] = False,
) -> None:
    """Run the reproducible Stage 13 benchmark and ablations."""
    try:
        result = run_benchmark(
            output_dir.resolve(),
            real_run_dir=None if fixtures_only else real_run_dir.resolve(),
            require_real_data=not fixtures_only,
        )
    except (HiFiAgentError, ValidationError, OSError, ValueError) as exc:
        abort_with_error(RuleEvaluationError(f"Stage 13 benchmark failed: {exc}"))
    console = get_console()
    status = "PASS" if result.acceptance_passed else "FAIL"
    color = "green" if result.acceptance_passed else "red"
    console.print(f"[{color}]Stage 13 benchmark: {status}[/{color}]")
    console.print(f"Scenarios: {result.metrics.scenario_count}")
    console.print(f"Report: {output_dir.resolve() / 'v1_benchmark.md'}")
    if not result.acceptance_passed:
        raise typer.Exit(code=1)


@app.command()
def demo(
    output_dir: Annotated[
        Path,
        typer.Argument(help="Portable demo output directory."),
    ] = Path("demo_output"),
) -> None:
    """Run the small, data-free Agent decision demo in under ten minutes."""
    try:
        result = run_benchmark(
            output_dir.resolve(),
            real_run_dir=None,
            require_real_data=False,
        )
    except (HiFiAgentError, ValidationError, OSError, ValueError) as exc:
        abort_with_error(RuleEvaluationError(f"Demo failed: {exc}"))
    console = get_console()
    console.print("[green]Portable Agent demo completed.[/green]")
    console.print(
        f"Scenarios passed: {sum(item.passed for item in result.scenarios)}/{len(result.scenarios)}"
    )
    console.print(f"Readable report: {output_dir.resolve() / 'v1_benchmark.md'}")


def main() -> None:
    """Run the Typer application with normalized project errors."""
    try:
        app()
    except HiFiAgentError as exc:
        get_console(stderr=True).print(f"[red]{exc}[/red]")
        raise typer.Exit(code=exc.exit_code) from exc
