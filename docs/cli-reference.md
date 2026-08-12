# CLI Reference

**English** | [简体中文](zh-CN/cli-reference.md)

The installed entry point is `hifi-agent`. Commands emit stable exit codes and persist detailed
machine-readable receipts in a run or explicitly selected output directory.

## Global options

```bash
hifi-agent --help
hifi-agent --version
```

Use each command's `--help` as the authoritative option list for the installed release.

## `validate`

```bash
hifi-agent validate configs/sample.yaml
```

Parses both configuration layers, resolves safe input paths, validates FASTQ/gzip, computes complete
input hashes, and creates a validation receipt. It does not launch assembly.

## `plan`

```bash
hifi-agent plan configs/sample.yaml
```

Performs configuration resolution and a read-only production preflight: executable resolution,
version contracts, CPU, memory, disk reserve, cache permissions, coverage backend, and BUSCO
lineage state. Use it immediately before an expensive run on the target host.

## `assemble`

```bash
hifi-agent assemble configs/sample.yaml
hifi-agent assemble configs/sample.yaml --resume
```

Creates or resumes the controlled lifecycle. In `auto` mode, the first form safely resumes when the
same immutable run exists. In `explicit` mode, continuation requires `--resume`. Resume never
bypasses identity, journal, budget, inventory, or parameter-contract verification.

## `verify-run`

```bash
hifi-agent verify-run results/sample_001 --deep
```

Deep mode recomputes run identity, state/event and budget consistency, attempt inventories,
completion markers, approved/rendered/realized parameters, incumbent history, canonical report
agreement, and provenance hashes. Use it before interpreting or publishing results.

## External dataset commands

```bash
hifi-agent check-dataset REGISTRY.yaml DATASET_ID
hifi-agent verify-real RUN_DIR REGISTRY.yaml DATASET_ID
```

`check-dataset` resolves a registry entry and hashes its external bytes. `verify-real` combines deep
run integrity with registry binding and strict real-data acceptance. Data remains outside Git.

For release-only tests, set both variables explicitly:

```bash
export HIFI_AGENT_REAL_REGISTRY=/controlled/path/datasets.yaml
export HIFI_AGENT_REAL_DATASET_ID=dataset_id
pytest -m real_acceptance tests/integration/test_real_acceptance.py
```

## External-provider acceptance

```bash
hifi-agent live-smoke RUN_DIR OUTPUT_DIR
hifi-agent build-evidence --help
```

`live-smoke` sends only authorized, redacted aggregate context and records a receipt; it never sends
reads, sequence, absolute paths, or API keys. `build-evidence` creates a hash-bound release evidence
bundle from a verified run, registry, source configuration, wheel, tests, and commit metadata.

Online hybrid mode reads `DEEPSEEK_API_KEY` from the environment. The key is never written to run
artifacts. Offline transcript replay uses a checksummed fixture bound to an exact round and context.

## Exit codes

| Code | Class | Meaning |
|---:|---|---|
| `0` | scientific | Accepted or stopped normally according to configured policy |
| `2` | validation | Configuration, path, format, or input validation failed |
| `3` | action required | Budget, risk confirmation, or human review blocks progress |
| `4` | engineering failure | Tool, parameter contract, state, report, or integrity failed |
| `5` | required provider | A provider required by policy did not return a valid result |

An exit code of zero is not a claim that the assembly is globally optimal or fit for every downstream
use. Always review the terminal outcome, reason codes, verification report, and scientific evidence.
