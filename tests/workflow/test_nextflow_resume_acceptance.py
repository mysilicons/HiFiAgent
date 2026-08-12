import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "nextflow_resume"


def _nextflow_runtime() -> tuple[str, dict[str, str]]:
    """Return a usable Nextflow executable and environment or skip the test."""
    nextflow = shutil.which("nextflow")
    if nextflow is None:
        pytest.skip("Nextflow is not installed in this environment.")
    env = os.environ.copy()
    if shutil.which("java") is None:
        pytest.skip("Java 17 or newer is not available in this environment.")
    return nextflow, env


def test_interrupted_workflow_resumes_completed_process_from_cache(tmp_path: Path) -> None:
    nextflow, env = _nextflow_runtime()
    outdir = tmp_path / "out"
    control_dir = tmp_path / "control"
    control_dir.mkdir()
    command = [
        nextflow,
        "run",
        str(FIXTURE_ROOT / "resume.nf"),
        "-c",
        str(FIXTURE_ROOT / "resume.config"),
        "-work-dir",
        str(tmp_path / "work"),
        "--outdir",
        str(outdir),
        "--control_dir",
        str(control_dir),
    ]

    interrupted = subprocess.Popen(
        command,
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    first_output = outdir / "published" / "first.txt"
    deadline = time.monotonic() + 30
    while (
        not (control_dir / "second_started").exists() or not first_output.exists()
    ) and time.monotonic() < deadline:
        if interrupted.poll() is not None:
            stdout, stderr = interrupted.communicate()
            pytest.fail(f"Workflow exited before interruption point:\n{stdout}\n{stderr}")
        time.sleep(0.1)
    assert (control_dir / "second_started").is_file(), "second process never started"
    assert first_output.is_file(), "first process output was not published before interruption"
    os.killpg(interrupted.pid, signal.SIGTERM)
    interrupted.communicate(timeout=20)

    assert first_output.read_text() == "stable completed output\n"
    assert not (outdir / "published" / "second.txt").exists()

    (control_dir / "allow_finish").write_text("finish\n")
    resumed = subprocess.run(
        [*command, "-resume"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert resumed.returncode == 0, f"{resumed.stdout}\n{resumed.stderr}"
    assert (outdir / "published" / "second.txt").read_text() == "stable completed output\n"
    trace = (outdir / "trace.txt").read_text()
    assert "FIRST_STEP" in trace
    assert "CACHED" in trace
