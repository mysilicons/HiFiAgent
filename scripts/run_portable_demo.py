#!/usr/bin/env python3
"""Create and run the production current CLI against the executable portable fixture."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

TOOL_NAMES = (
    "java",
    "nextflow",
    "hifiasm",
    "gfatools",
    "seqkit",
    "NanoPlot",
    "meryl",
    "quast.py",
    "busco",
    "merqury.sh",
    "minimap2",
    "samtools",
    "Rscript",
    "genomescope2",
    "bedtools",
)
CONFIG_TOOL_NAMES = {
    "NanoPlot": "nanoplot",
    "quast.py": "quast",
    "merqury.sh": "merqury",
    "Rscript": "rscript",
    "genomescope2": "genomescope",
}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _install_toolchain(workspace: Path) -> dict[str, str]:
    source = _project_root() / "tests/fixtures/toolchain/fixture_tool.py"
    tool_bin = workspace / "fixture-bin"
    tool_bin.mkdir(parents=True, exist_ok=True)
    overrides: dict[str, str] = {}
    for executable_name in TOOL_NAMES:
        target = tool_bin / executable_name
        if target.exists() or target.is_symlink():
            target.unlink()
        shutil.copy2(source, target)
        config_name = CONFIG_TOOL_NAMES.get(executable_name, executable_name)
        overrides[config_name] = str(target)
    for relative in ("util/util.sh", "eval/spectra-cn.sh", "eval/qv.sh"):
        asset = tool_bin / relative
        asset.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, asset)
    return overrides


def _write_config(workspace: Path, scenario: str) -> tuple[Path, Path]:
    workspace.mkdir(parents=True, exist_ok=True)
    reads = workspace / "reads.fastq"
    reads.write_text("@portable\nACGTACGT\n+\nIIIIIIII\n")
    run_dir = workspace / "run"
    replay = _project_root() / "tests/fixtures/toolchain/recorded_llm_transcript.json"
    optimization: dict[str, object] = {
        "max_rounds": 3,
        "max_candidates_per_round": 2 if scenario == "human-review" else 1,
        "decision_mode": (
            "hybrid" if scenario in {"llm-replay", "llm-required-failure"} else "rules_only"
        ),
        "require_llm": scenario in {"llm-replay", "llm-required-failure"},
    }
    if scenario == "llm-replay":
        replay_copy = workspace / "recorded_llm_transcript.json"
        shutil.copy2(replay, replay_copy)
        optimization["llm_replay_transcript"] = str(replay_copy)
    config = {
        "schema_id": "hifi-agent",
        "sample_id": f"fixture-{scenario}",
        "read_technology": "pacbio_hifi",
        "hifi_reads": [str(reads)],
        "outdir": str(run_dir),
        "resources": {"max_threads": 2, "max_memory_gb": 4},
        "optimization": optimization,
        "execution_budget": {
            "max_total_assemblies": 7,
            "max_cpu_hours": 100,
            "max_walltime_hours": 24,
            "min_free_disk_gib": 0,
        },
        "tools": {
            "coverage_backend": "bedtools",
            "executable_overrides": _install_toolchain(workspace),
        },
    }
    path = workspace / "sample.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    return path, run_dir


def _run_cli(config: Path, *, resume: bool = False) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "hifi_agent", "assemble", str(config)]
    if resume:
        command.append("--resume")
    environment = os.environ.copy()
    environment.pop("DEEPSEEK_API_KEY", None)
    environment["PYTHONPATH"] = str(_project_root() / "src")
    return subprocess.run(
        command,
        cwd=_project_root(),
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument(
        "--scenario",
        choices=(
            "three-rounds",
            "llm-replay",
            "llm-required-failure",
            "resume",
            "human-review",
            "tool-failure",
        ),
        default="three-rounds",
    )
    arguments = parser.parse_args()
    config, run_dir = _write_config(arguments.workspace.resolve(), arguments.scenario)
    first = _run_cli(config)
    observed_codes = [first.returncode]
    stderr = first.stderr
    stdout = first.stdout
    if arguments.scenario == "resume" and first.returncode == 4:
        resumed = _run_cli(config, resume=True)
        observed_codes.append(resumed.returncode)
        stderr += resumed.stderr
        stdout += resumed.stdout
    result = {
        "schema_id": "hifi-agent",
        "scenario": arguments.scenario,
        "config": str(config),
        "run_dir": str(run_dir),
        "exit_codes": observed_codes,
        "stdout": stdout,
        "stderr": stderr,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    expected = {
        "three-rounds": [0],
        "llm-replay": [0],
        "llm-required-failure": [5],
        "resume": [4, 0],
        "human-review": [3],
        "tool-failure": [4],
    }[arguments.scenario]
    return 0 if observed_codes == expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
