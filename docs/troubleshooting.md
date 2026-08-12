# Troubleshooting

**English** | [简体中文](zh-CN/troubleshooting.md)

Preserve evidence first. Do not delete a run directory, lock, attempt, cache, or manifest before
recording the command, exit code, terminal outcome, and reason codes.

## Configuration and input

For `Sample configuration failed validation`, follow the full field path in the error and compare it
with the [configuration reference](configuration-reference.md). Common causes are unknown fields,
wrong schema IDs, out-of-range values, or inconsistent provider policy.

Input paths must be relative to `data_root`, contain no `..`, and remain inside the root after symlink
resolution. Check FASTQ before creating a run:

```bash
gzip -t Data/sample/reads.fastq.gz
seqkit stats Data/sample/reads.fastq.gz
```

Recompression changes identity; use a new run after repairing data.

## Environment preflight

For `TOOL_NOT_FOUND`, activate the intended environment and check resolution:

```bash
conda activate hifiAgent
command -v nextflow
command -v hifiasm
hifi-agent plan configs/sample.yaml
```

Prefer the active environment over executable overrides. Rebuild from `environment.yml` for version
contract errors. Lower requested CPU or memory while reserving operating-system capacity. Resolve
disk pressure outside the active attempt; never remove its work directory during execution.

## BUSCO

With `download_missing_busco: true`, preflight may report a pending download and assembly acquires a
shared cache lock. In offline environments, pre-populate a complete lineage containing valid
`dataset.cfg` under the configured cache and set downloads to false. Empty placeholders and invalid
metadata are rejected.

## Nextflow and external tools

After SIGINT/SIGTERM, wait for the original process to exit and repeat `assemble`; do not manually
add `-resume` to internal Nextflow. For `FAILED_TOOL`, inspect the attempt's workflow log, stderr,
exit status, and completion marker. Correct system conditions and resume within retry budget, or
start a new run if inputs, tools, resources, or contracts must change.

`FAILED_PARAMETER_CONTRACT` means requested, approved, rendered argv, or realized parameters differ.
Preserve the hifiasm banner, argv receipt, and parser evidence; this is not an ordinary retry.

## Locks and recovery

One run permits one controller. Do not remove a lock while its process may be alive. Controlled stale
lock takeover validates identity and process state. Identity/checksum drift is an expected safety
rejection. Never copy a Nextflow cache from another attempt.

## Decision service

`rules_only` and `llm_disabled` need no key. Online hybrid mode requires:

```bash
export DEEPSEEK_API_KEY='set-in-your-secret-manager'
```

Optional-provider failures fall back deterministically and are recorded; required-provider failure
ends with `FAILED_REQUIRED_LLM` and exit 5. A rejected proposal should be investigated through the
reason codes in `04_decisions`; never execute provider text directly.

## Verification failure

```bash
hifi-agent verify-run results/sample_001 --deep
```

Preserve `verification_report.json` and find the first failed check. Do not edit a manifest or report
to force a pass. Trace the provenance back to the missing, modified, or hash-mismatched source. If the
chain cannot be restored, exclude the run from scientific conclusions.

## Reproducible diagnostics

Report the application version, operating system and environment export, command and exit code,
terminal outcome and reason codes, redacted environment/verification manifests, and a minimal
configuration. Never share reads, sequence, API keys, personal absolute paths, or unauthorized run
artifacts.
