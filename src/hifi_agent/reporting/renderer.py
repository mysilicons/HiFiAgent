"""Jinja2 rendering and tabular artifact writers for Stage 12 reports."""

from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from hifi_agent.reporting.collector import ASSEMBLY_METRICS, ReportCollector
from hifi_agent.reporting.models import FinalReportData
from hifi_agent.reporting.synthetic import load_synthetic_scenario

TEMPLATE_DIR = Path(__file__).parent / "templates"


@dataclass(frozen=True)
class ReportOutputs:
    """Paths produced by one complete report render."""

    output_dir: Path
    markdown: Path
    summary_json: Path
    comparison_tsv: Path
    parameter_diff_tsv: Path
    provenance_tsv: Path
    software_versions_tsv: Path
    figures_dir: Path


def render_final_report(
    run_dir: Path,
    *,
    output_dir: Path | None = None,
    scenario_path: Path | None = None,
    redact_paths: bool = True,
    generated_at: datetime | None = None,
) -> ReportOutputs:
    """Collect available facts and render all required Stage 12 artifacts."""
    resolved_run_dir = run_dir.resolve()
    resolved_output = (output_dir or (resolved_run_dir / "05_report")).resolve()
    resolved_output.mkdir(parents=True, exist_ok=True)
    figures_dir = resolved_output / "figures"
    figures = _copy_figures(resolved_run_dir, figures_dir)
    scenario = load_synthetic_scenario(scenario_path) if scenario_path else None
    collector = ReportCollector(resolved_run_dir, redact_paths=redact_paths)
    data = collector.collect(
        scenario=scenario,
        scenario_source=scenario_path.resolve() if scenario_path else None,
        figures=figures,
        generated_at=generated_at,
    )
    if not figures:
        data.limitations.append("NO_REPORT_FIGURES_AVAILABLE")
    summary = resolved_output / "final_summary.json"
    markdown = resolved_output / "final_report.md"
    comparison = resolved_output / "comparison.tsv"
    parameter_diff = resolved_output / "parameter_diff.tsv"
    provenance = resolved_output / "provenance.tsv"
    software = resolved_output / "software_versions.tsv"
    summary.write_text(data.model_dump_json(indent=2) + "\n")
    markdown.write_text(_render_markdown(data))
    _write_comparison(data, comparison)
    _write_parameter_diff(data, parameter_diff)
    _write_provenance(data, provenance)
    _write_software(data, software)
    (resolved_output / "reproducible_commands.txt").write_text(
        "\n".join(data.reproducible_commands) + "\n"
    )
    return ReportOutputs(
        output_dir=resolved_output,
        markdown=markdown,
        summary_json=summary,
        comparison_tsv=comparison,
        parameter_diff_tsv=parameter_diff,
        provenance_tsv=provenance,
        software_versions_tsv=software,
        figures_dir=figures_dir,
    )


def _render_markdown(data: FinalReportData) -> str:
    environment = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    environment.filters["display"] = _display
    environment.filters["json"] = lambda value: json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
    )
    template = environment.get_template("final_report.md.j2")
    return template.render(report=data)


def _copy_figures(run_dir: Path, figures_dir: Path) -> list[str]:
    candidates = [
        *sorted((run_dir / "01_pre_qc/kmer/genomescope").glob("*.png")),
        *sorted((run_dir / "03_post_qc/baseline/merqury").rglob("*.png")),
    ]
    if not candidates:
        return []
    figures_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for source in candidates:
        prefix = "genomescope" if "genomescope" in source.parts else "merqury"
        destination = figures_dir / f"{prefix}_{source.name}"
        shutil.copy2(source, destination)
        copied.append(f"figures/{destination.name}")
    return copied


def _write_comparison(data: FinalReportData, path: Path) -> None:
    metric_names = list(ASSEMBLY_METRICS)
    fieldnames = ["run_id", "kind", "status", "synthetic", *metric_names]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for assembly in data.assembly_runs:
            row: dict[str, Any] = {
                "run_id": assembly.run_id,
                "kind": assembly.kind,
                "status": assembly.status,
                "synthetic": str(assembly.synthetic).lower(),
            }
            for metric in metric_names:
                value = assembly.metrics[metric].value
                row[metric] = "" if value is None else value
            writer.writerow(row)


def _write_parameter_diff(data: FinalReportData, path: Path) -> None:
    fieldnames = [
        "run_id",
        "parameter",
        "baseline_value",
        "candidate_value",
        "reason_codes",
        "evidence",
        "risk_level",
        "result",
        "synthetic",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for change in data.parameter_changes:
            writer.writerow(
                {
                    "run_id": change.run_id,
                    "parameter": change.parameter,
                    "baseline_value": (
                        "" if change.baseline_value is None else change.baseline_value
                    ),
                    "candidate_value": (
                        "" if change.candidate_value is None else change.candidate_value
                    ),
                    "reason_codes": ",".join(change.reason_codes),
                    "evidence": json.dumps(change.evidence, sort_keys=True),
                    "risk_level": change.risk_level,
                    "result": change.result,
                    "synthetic": str(change.synthetic).lower(),
                }
            )


def _write_provenance(data: FinalReportData, path: Path) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["artifact_id", "role", "path", "status", "sha256", "byte_size"])
        for record in data.provenance:
            writer.writerow(
                [
                    record.artifact_id,
                    record.role,
                    record.path,
                    record.status,
                    record.sha256 or "",
                    "" if record.byte_size is None else record.byte_size,
                ]
            )


def _write_software(data: FinalReportData, path: Path) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["tool", "version", "source_file"])
        for record in data.software_versions:
            writer.writerow([record.tool, record.version or "NOT_RECORDED", record.source_file])


def _display(value: object) -> str:
    if value is None:
        return "NA (not available)"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)
