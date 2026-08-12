# Configuration Reference

**English** | [简体中文](zh-CN/configuration-reference.md)

HiFi Agent uses two strict YAML schemas. The runtime file describes shared infrastructure and
policy; the sample file describes one dataset and its scientific facts. Unknown fields, unsafe
paths, inconsistent budgets, and unsupported values are rejected.

## Path resolution

- `runtime_config` is resolved relative to the sample file.
- Runtime roots are resolved relative to the runtime file.
- Sample inputs are relative to `paths.data_root`; absolute paths and `..` are forbidden.
- Symlink targets must remain inside `data_root`.
- Output identity is derived from the resolved configuration and input bytes, not the current shell
  directory.

## Runtime configuration

| Section | Fields | Purpose |
|---|---|---|
| `paths` | `data_root`, `output_root`, `cache_root` | Controlled input, output, and shared-cache roots |
| `resources` | `max_threads`, `max_memory_gb` | Per-workflow host ceilings checked during preflight |
| `optimization` | enablement, rounds, candidates, decision mode, risk and retention | Bounds scientific search and authorization |
| `execution_budget` | assemblies, retries, CPU/wall time, disk, provider calls | Bounds run-wide consumption |
| `tools` | BUSCO cache, coverage backend, lineage download, executable overrides | Selects validated external integrations |
| `kmer` | `k`, low-coverage threshold | Controls pre-QC and evidence applicability |
| `mapping_qc` | read filters and coverage window | Fixes mapping/coverage comparison semantics |
| `runtime` | resume mode and retention | Controls recovery and terminal cleanup |

Important constraints include: `max_rounds` 0–3, candidates per round 1–2, at most one parameter
change per candidate, total assemblies 1–7, tool retries 0–3, at most one provider call per round and
three per run. `require_llm: true` is valid only with `decision_mode: hybrid` and sufficient provider
budgets. `rules_only` and `llm_disabled` require zero provider-call budgets.

Executable overrides are intended for controlled installations that cannot be exposed through
`PATH`. They must be explicit executable paths and are recorded in the environment manifest. Prefer
the active Conda environment.

## Sample configuration

| Field | Required | Meaning |
|---|---:|---|
| `schema_id` | yes | Must be `hifi-agent-sample` |
| `runtime_config` | yes | Runtime YAML, relative to this file |
| `sample_id` | yes | Stable safe identifier |
| `read_technology` | yes | Must be `pacbio_hifi` |
| `hifi_reads` | yes | One or more FASTQ/FASTQ.GZ paths under `data_root` |
| `species_name` | no | Scientific label; `null` when unknown or intentionally omitted |
| `expected_genome_size` | no | Trusted expected haploid size used for applicable metrics |
| `ploidy` | no | Known ploidy; never infer it merely to satisfy configuration |
| `inbred` | no | Known inbreeding state |
| `busco_lineage` | no | Explicit BUSCO lineage identifier |
| `kmer_reads` | no | Independent reads for stronger k-mer validation |
| `reference_genome` | no | Trusted reference enabling reference-based QUAST evidence |

When `kmer_reads` is absent, same-read k-mer metrics are marked advisory. When a trusted reference is
absent, reference-only metrics are inapplicable rather than silently replaced.

## Complete generic example

Use the checked templates [runtime.yaml](../configs/runtime.yaml) and
[sample.yaml](../configs/sample.yaml). A normal invocation always points only to the sample file:

```bash
hifi-agent validate configs/sample.yaml
hifi-agent plan configs/sample.yaml
hifi-agent assemble configs/sample.yaml
```

Configuration becomes part of immutable run identity. Changing inputs, runtime policy, tool
contracts, or scientific facts after run creation requires a new run; `--resume` cannot override
identity checks.

## Validation strategy

Use `validate` for schema, path, format, and input hashing. Use `plan` for the resolved effective
configuration and environment preflight. Keep both receipts. For terminal evidence, use
`verify-run --deep`; it validates that snapshots and realized execution still match the approved
configuration.
