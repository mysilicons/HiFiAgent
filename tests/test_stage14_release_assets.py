import re
import subprocess
from pathlib import Path

import yaml

from hifi_agent.constants import __version__

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_release_version_and_required_files_are_consistent() -> None:
    assert __version__ == "1.0.0"
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text()
    citation = yaml.safe_load((PROJECT_ROOT / "CITATION.cff").read_text())
    assert 'version = "1.0.0"' in pyproject
    assert citation["version"] == "1.0.0"
    for relative in (
        "LICENSE",
        "CHANGELOG.md",
        "docs/user_guide.md",
        "docs/developer_guide.md",
        "docs/architecture.md",
        "docs/rule_catalog.md",
        "docs/release_checklist.md",
        "docs/releases/v1.0.0.md",
        "docs/interview_qa.md",
    ):
        assert (PROJECT_ROOT / relative).is_file(), relative


def test_readme_quickstart_uses_a_real_cli_command() -> None:
    readme = (PROJECT_ROOT / "README.md").read_text()
    assert "hifi-agent demo /tmp/hifi-agent-demo" in readme
    assert "Scenarios passed: 9/9" in readme
    assert "Git remote" in readme


def test_demo_gif_is_3_to_5_minutes_and_snapshot_is_a_gif() -> None:
    demo = (PROJECT_ROOT / "docs/assets/hifi_agent_demo.gif").read_bytes()
    snapshot = (PROJECT_ROOT / "docs/assets/candida_report_snapshot.png").read_bytes()
    assert demo.startswith(b"GIF89a")
    assert snapshot.startswith(b"\x89PNG\r\n\x1a\n")
    delays = [
        int.from_bytes(demo[match.start() + 4 : match.start() + 6], "little")
        for match in re.finditer(b"\x21\xf9\x04", demo)
    ]
    duration_seconds = sum(delays) / 100
    assert 180 <= duration_seconds <= 300
    assert len(delays) == 12


def test_repository_does_not_track_large_biological_file_extensions() -> None:
    forbidden = {".fastq", ".fq", ".bam", ".cram", ".meryl"}
    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    files = [PROJECT_ROOT / path for path in tracked]
    offenders = [path for path in files if path.suffix.lower() in forbidden]
    assert offenders == []
