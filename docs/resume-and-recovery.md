# Resume and Recovery

**English** | [简体中文](zh-CN/resume-and-recovery.md)

Recovery continues the same verified run; it does not force execution after facts change. Immutable
identity, transactional state, append-only events, a budget ledger, a single-writer lock, and
attempt-local Nextflow cache make continuation safe.

## Resume modes

```yaml
runtime:
  resume_mode: auto
  retention: standard
```

In `auto` mode, repeat the original command:

```bash
hifi-agent assemble configs/sample.yaml
```

In `explicit` mode, use `--resume`. Neither mode bypasses integrity verification.

## Immutable identity

Resume binds the original runtime and sample snapshots, resolved/effective configuration, input
sizes and SHA-256, environment manifest, comparison policy, governed knowledge, package/commit,
state/event/budget/manifest chains, and attempt inventories and parameter contracts. Changed input
bytes, symlink targets, configuration, tools, or hand-edited evidence fail closed and require a new
run.

## Attempt semantics

- Baseline is an independent round-zero attempt.
- Round, candidate, and attempt numbers uniquely identify candidate execution.
- A tool retry creates a new attempt and never overwrites prior evidence.
- Every attempt owns its workflow directory, logs, contract, inventory, and completion marker.
- The completion marker is last and is reusable only after all required evidence validates.
- Cache must never be copied from a different attempt.

## Failure behavior

| Scenario | Recovery behavior |
|---|---|
| SIGINT/SIGTERM | Preserve current attempt/cache and repeat the same command |
| Deterministic tool failure | Create a new attempt within retry budget |
| Completed attempt | Verify and reuse without rerun or duplicate accounting |
| Manifest written before controller exit | Reconcile transaction, event, and history |
| Reports not yet generated | Rebuild idempotently from authoritative terminal evidence |
| Modified report or inventory | Verification fails; modified evidence is not overwritten |
| Second writer | Single-writer lock rejects it |
| Stale lock | Validate process and identity, then take over and archive the old lock |
| Missing current-attempt cache | Fail explicitly; do not borrow another cache |
| Configuration/input drift | Reject resume and require a new run |

## Operational procedure

After interruption, confirm no controller remains, keep `02_assembly`, `05_agent`, and work files,
repeat the original command, inspect resume events and attempt logs, then run deep verification.
After a tool failure, correct only the external condition if configuration and identity remain valid;
otherwise create a new output name. Never delete a lock directly: verify the recorded host, PID, and
process, and let controlled stale-lock handling decide.

For integrity failure, preserve the complete run read-only and run:

```bash
hifi-agent verify-run results/sample_001 --deep
```

If altered evidence cannot be restored from authoritative sources, do not use that run for a
scientific conclusion; start from clean inputs.

## Retention policy

`full` keeps workflow work, cache, and intermediates for investigation. `standard` deletes only
reproducible work after terminal state, all canonical reports, and a passing deep verification exist,
and only targets listed by the retention inventory. Assemblies, post-QC, contracts, logs, Nextflow
metadata, reports, and audit records remain. The action is recorded in
`00_metadata/retention_receipt.json`.
