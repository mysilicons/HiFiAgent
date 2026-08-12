#!/usr/bin/env python3
"""Build a self-contained, commit-bound release evidence directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from hifi_agent.acceptance import _verify_wheel_source

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _require_equal(label: str, *values: object) -> None:
    normalized = {str(value) for value in values}
    if len(normalized) != 1:
        raise ValueError(f"{label} mismatch: {', '.join(sorted(normalized))}")


def _write_markdown(
    output_dir: Path,
    *,
    version: str,
    commit: str,
    run_identity: dict[str, Any],
    summary: dict[str, Any],
    evidence: dict[str, Any],
) -> None:
    run_uuid = str(run_identity["run_uuid"])
    outcome = str(summary["terminal_outcome"])
    notes = f"""# HiFi Agent {version}

This release provides a constrained, auditable PacBio HiFi assembly workflow with immutable run
identity, isolated attempts, deterministic comparison, recovery, deep verification, and governed
optional model proposals.

The release is bound to commit `{commit}` and real run `{run_uuid}`. The accepted outcome was
`{outcome}`; the incumbent was retained because the tested candidate did not provide a protected
material improvement. No global parameter optimality or clinical suitability is claimed.
"""
    report = f"""# Acceptance report

- Status: PASS
- Package: {version}
- Commit: `{commit}`
- Run UUID: `{run_uuid}`
- Dataset: `{evidence["dataset_id"]}`
- Terminal outcome: `{outcome}`
- Verification: `{summary["verification_status"]}`
- Real suite: {evidence["real_suite_tests"]} tests, {evidence["real_suite_failures"]} failures,
  {evidence["real_suite_errors"]} errors, {evidence["real_suite_skipped"]} skipped
- Run evidence SHA-256: `{evidence["run_evidence_sha256"]}`

The real run completed a baseline and one single-variable candidate. The release accepts the
workflow and evidence chain, not a claim that the candidate improved the assembly.
"""
    limitations = """# Known limitations

- Scope is single-sample PacBio HiFi on Linux x86_64 with hifiasm and the frozen parameter list.
- Hi-C, ONT, trio, polyploid expansion, scaffolding, and annotation are outside the release scope.
- The real release gate contains one Drosophila dataset and does not establish cross-species
  generalization.
- Same-read Merqury evidence is advisory rather than independent validation.
- Without a frozen reference, QUAST misassembly metrics are not applicable.
- The tested candidate need not improve the baseline; no global optimality claim is made.
- External model use requires explicit data-governance authorization and is not an execution
  authority.
- This software is research-use software and is not validated for clinical diagnosis.
"""
    (output_dir / "RELEASE_NOTES.md").write_text(notes)
    (output_dir / "ACCEPTANCE_REPORT.md").write_text(report)
    (output_dir / "known_limitations.md").write_text(limitations)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--evidence-manifest", type=Path, required=True)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--sdist", type=Path, required=True)
    parser.add_argument("--portable-summary", type=Path, required=True)
    parser.add_argument("--real-summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()

    commit = _git("rev-parse", "HEAD")
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise ValueError("Release source tree must be clean")
    tag_commit = _git("rev-list", "-n", "1", arguments.tag)
    _require_equal("tag and release commit", tag_commit, commit)

    run_dir = arguments.run_dir.resolve()
    run_identity = _json(run_dir / "00_metadata/run_identity.json")
    summary = _json(run_dir / "06_report/final_summary.json")
    verification = _json(run_dir / "06_report/verification_report.json")
    environment = _json(run_dir / "00_metadata/environment_manifest.json")
    evidence = _json(arguments.evidence_manifest.resolve())
    _require_equal("code commit", commit, run_identity["code_commit"], evidence["code_commit"])
    _require_equal("run UUID", run_identity["run_uuid"], evidence["run_uuid"])
    _require_equal(
        "package version",
        arguments.version,
        run_identity["package_version"],
        evidence["package_version"],
    )
    if evidence.get("status") != "PASS" or verification.get("status") != "PASS":
        raise ValueError("Real evidence and deep verification must both pass")
    if environment.get("status") != "PASS":
        raise ValueError("Recorded release environment must pass preflight")
    if (
        any(
            int(evidence[key]) != expected
            for key, expected in (
                ("real_suite_failures", 0),
                ("real_suite_errors", 0),
                ("real_suite_skipped", 0),
            )
        )
        or int(evidence["real_suite_tests"]) <= 0
    ):
        raise ValueError("Real acceptance suite is not a non-empty zero-failure zero-skip run")
    _verify_wheel_source(arguments.wheel.resolve(), arguments.version)
    if not arguments.sdist.is_file():
        raise ValueError(f"Source distribution is missing: {arguments.sdist}")

    output_dir = arguments.output_dir.resolve()
    if output_dir.exists():
        raise ValueError(f"Release output already exists: {output_dir}")
    output_dir.mkdir(parents=True)
    _write_markdown(
        output_dir,
        version=arguments.version,
        commit=commit,
        run_identity=run_identity,
        summary=summary,
        evidence=evidence,
    )
    copies = {
        "portable_test_summary.txt": arguments.portable_summary,
        "real_acceptance_summary.txt": arguments.real_summary,
        "real_run_verification.json": run_dir / "06_report/verification_report.json",
        "environment_manifest.json": run_dir / "00_metadata/environment_manifest.json",
        arguments.wheel.name: arguments.wheel,
        arguments.sdist.name: arguments.sdist,
    }
    for name, source in copies.items():
        if not source.is_file():
            raise ValueError(f"Required release input is missing: {source}")
        shutil.copy2(source, output_dir / name)

    artifact_hashes = {
        path.name: _sha256(path) for path in sorted(output_dir.iterdir()) if path.is_file()
    }
    manifest = {
        "schema_id": "hifi-agent",
        "status": "PASS",
        "release_version": arguments.version,
        "tag": arguments.tag,
        "code_commit": commit,
        "tag_commit": tag_commit,
        "run_uuid": run_identity["run_uuid"],
        "dataset_id": evidence["dataset_id"],
        "run_evidence_sha256": evidence["run_evidence_sha256"],
        "source_evidence_manifest_sha256": _sha256(arguments.evidence_manifest),
        "artifacts": artifact_hashes,
        "gates": {
            "clean_source": "PASS",
            "tag_binding": "PASS",
            "wheel_source_and_resources": "PASS",
            "deep_verification": verification["status"],
            "real_suite_tests": evidence["real_suite_tests"],
            "real_suite_failures": evidence["real_suite_failures"],
            "real_suite_errors": evidence["real_suite_errors"],
            "real_suite_skipped": evidence["real_suite_skipped"],
        },
    }
    manifest_path = output_dir / "acceptance_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    sums = [
        f"{_sha256(path)}  {path.name}"
        for path in sorted(output_dir.iterdir())
        if path.is_file() and path.name != "SHA256SUMS"
    ]
    (output_dir / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
