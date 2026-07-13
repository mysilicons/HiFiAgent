import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_JAVA_HOME = Path("/home/gw/software/jdk21")
LOCAL_JAVA_CMD = LOCAL_JAVA_HOME / "bin" / "java"


def _nextflow_runtime() -> tuple[str, dict[str, str]]:
    """Return a usable Nextflow executable and environment or skip the test."""
    nextflow = shutil.which("nextflow") or "/home/gw/software/nextflow"
    if not Path(nextflow).exists():
        pytest.skip("Nextflow is not installed in this environment.")
    env = os.environ.copy()
    if LOCAL_JAVA_CMD.exists():
        env["JAVA_HOME"] = str(LOCAL_JAVA_HOME)
        env["JAVA_CMD"] = str(LOCAL_JAVA_CMD)
    elif shutil.which("java") is None:
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
        str(PROJECT_ROOT / "workflow" / "acceptance" / "resume.nf"),
        "-c",
        str(PROJECT_ROOT / "workflow" / "acceptance" / "resume.config"),
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
    deadline = time.monotonic() + 30
    while not (control_dir / "second_started").exists() and time.monotonic() < deadline:
        if interrupted.poll() is not None:
            stdout, stderr = interrupted.communicate()
            pytest.fail(f"Workflow exited before interruption point:\n{stdout}\n{stderr}")
        time.sleep(0.1)
    assert (control_dir / "second_started").is_file(), "second process never started"
    os.killpg(interrupted.pid, signal.SIGTERM)
    interrupted.communicate(timeout=20)

    first_output = outdir / "published" / "first.txt"
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
