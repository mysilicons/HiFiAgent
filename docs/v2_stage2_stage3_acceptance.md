# V2 Stages 2 and 3 acceptance report

Date: 2026-07-15. Result: **PASS**.

## Stage 2 acceptance

| Requirement | Evidence | Result |
|---|---|---|
| `OptimizationConfig` with at most three rounds | schema and boundary test | PASS |
| Run/attempt/round/history Pydantic schemas | `orchestration/models.py` | PASS |
| Stable round/candidate/attempt IDs | identifier tests | PASS |
| round/candidate/attempt audit directories | history layout tests and documentation | PASS |
| Scientific publish overwrite disabled by default | workflow static test; 14 process declarations | PASS |
| Pre-write target/completion checks | exclusive run/attempt/manifest creation | PASS |
| Artifact SHA-256, bytes, mtime, schema | `ArtifactRecord` and tamper tests | PASS |
| V1 read-only loader | filesystem snapshot test | PASS |
| `migrate-v1 --dry-run` and rejected `--execute` | CLI tests | PASS |
| Tool retry creates attempt 002 | retry test | PASS |
| Completed logical run creates no new attempt | idempotence test | PASS |
| Artifact or manifest mutation fails verification | two tamper tests | PASS |
| Concurrent run identity has one winner | two-thread exclusive-create test | PASS |

The audit layer references real workflow artifacts by checksum instead of copying large FASTA/GFA/bin
files. This preserves an immutable logical history while keeping V1 executor output compatibility
during incremental migration.

## Stage 3 acceptance

| Requirement | Evidence | Result |
|---|---|---|
| Unified `hifi-agent assemble CONFIG --resume` | CLI help and invocation test | PASS |
| Controller calls real baseline/candidate executors | explicit adapter-call test | PASS |
| Read/execute responsibilities separated | `AssemblyTools` protocol and `ExecutingAssemblyTools` | PASS |
| Post-QC not called again during evaluation | legacy controller call-count regression | PASS |
| Expensive baseline/candidate checks are idempotent | interruption and completed-attempt tests | PASS |
| Tool retry and optimization candidate are distinct | attempt 002 and candidate identity tests | PASS |
| V1 commands retained as advanced steps | CLI help test | PASS |
| Atomic state plus append-only trace | state implementation and trace-repair test | PASS |
| Resume verifies config/history/artifacts | config and artifact tamper tests | PASS |
| Resume propagates Nextflow cache flag | incomplete retry test observes `False, True` | PASS |
| Internal interruption hook is not public CLI | controller API/help inspection | PASS |
| Fixture completes baseline and report | controller fixture test | PASS |
| RETRY starts candidate execution path | candidate controller and adapter tests | PASS |
| REPORT resume has no new event/report | no-op resume test | PASS |
| Illegal transition leaves state/history unchanged | negative transition test | PASS |

## Retained Candida migration audit

Command:

```bash
hifi-agent migrate-v1 Data/Candida_albicans/hifiAgent --dry-run
```

Result:

- all five required V1 artifacts found;
- no missing required artifact;
- proposed V2 paths printed;
- `05_agent/v2` did not exist before or after the command;
- no retained artifact was modified.

## Quality gates

```text
Stage 2/3 focused tests: 84 passed
Final full pytest: 243 passed, 13 skipped
Ruff check: PASS
Ruff format --check: PASS (90 files)
mypy strict: PASS (89 source files)
Nextflow smoke: PASS
Coverage: 82.72% (required 80%)
```

The 13 skips remain explicit retained-data/live-API gates and are not required by Stages 2–3. No
new expensive biological assembly was required or started; the stage acceptance explicitly calls
for fixture orchestration and a read-only retained V1 audit.

## Scope boundary

Stage 3 stops after executing the first authorized candidate. It does not claim candidate selection,
incumbent update, plateau detection, or rounds 2–3; those remain Stage 8/9 deliverables.
