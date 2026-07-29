# V2 stages 0 and 1 acceptance report

Date: 2026-07-15. Result: **PASS**.

## Stage 0 acceptance

| Requirement | Evidence | Result |
|---|---|---|
| Freeze V2 scope and terminology | `docs/v2_scope.md` | PASS |
| Baseline is round 0; optimization is rounds 1–3 | ADR 0002 | PASS |
| Freeze initial parameter whitelist | scope and V2 plan | PASS |
| Preserve pre-existing dirty-worktree edits | baseline record and reviewed diff | PASS |
| Capture V1 regression result | Markdown and JSON baseline | PASS |
| Register Candida `--hom-cov true` as P0 | known-defect register | PASS |
| Define V1 read-only compatibility | scope freeze | PASS |
| Define retained-data checksum policy | local task board | PASS |
| Establish milestones and task dependencies | local milestone/issue board | PASS |

The repository had no applicable `AGENTS.md`. No retained biological artifact was modified or
deleted. Remote GitHub issues were not mutated; `docs/v2_task_board.md` is the reproducible local
source of truth and provides stable IDs for later mirroring.

## Stage 1 implementation acceptance

| Requirement | Implementation/evidence | Result |
|---|---|---|
| `hom_cov=None` is omitted | common optional encoder and unit test | PASS |
| Numeric `hom_cov` round-trips | `37` positive test | PASS |
| Optional genome size/reference/lineage are omitted | executor changes and optional-value tests | PASS |
| Empty string no longer represents missing | common encoder rejects blank strings | PASS |
| Bidirectional hifiasm contract | `executors/hifiasm_contract.py` | PASS |
| requested/approved/rendered/realized/check artifacts | executor finalization and artifact test | PASS |
| Unknown/duplicate/missing/bool-as-int flags rejected | parameter-contract negative tests | PASS |
| threads, output prefix, and reads checked | runtime-drift parameterized tests | PASS |
| Historical invalid candidate cannot be selected | Stage 11 runner validates existing command before metrics | PASS |
| README portable regression restored | release asset test passes | PASS |

## Retained Candida read-only audit

The contract was run directly against:

```text
Data/Candida_albicans/hifiAgent/
  02_assembly/candidate_r01_c01/metadata/hifiasm_command.txt
```

It rejected the retained command with:

```text
PARAMETER_CONTRACT_VIOLATION: Invalid value `true` for hifiasm parameter flag --hom-cov
```

This is the expected isolation result. The retained command and metrics were not rewritten. New
candidate executions write a `parameter_contract_check.json`; historical commands are validated
in memory before their metrics can enter Stage 11 comparison.

## Verification results

### Required stage commands

```text
pytest contract/stage11/reuse/release subset: 36 passed
Nextflow workflow smoke and structure subset: 36 passed
ruff check .: PASS
ruff format --check .: PASS (83 files formatted)
mypy: PASS (82 source files)
```

### Full portable regression

```text
218 passed, 13 skipped
```

The 13 skips are pre-existing explicit gates for retained real data, live LLM/API, and one missing
retained benchmark path. Stages 0 and 1 do not require live API or a new biological assembly. The
Nextflow smoke test executed successfully with assembly disabled and verified generated QC and
execution artifacts.

### Coverage

```text
Required coverage: 80%
Observed coverage: 81.44%
Result: PASS
```

## Defect closure

- `V2-P0-001`: closed with omission, parser, exact failure fixture, and retained-command audit.
- `V2-P0-002`: closed with preflight round-trip and post-run realized-command comparison.
- `V2-P0-003`: closed with one optional Nextflow encoder for genome size, reference, lineage, and
  hom-cov.
- `V2-P2-002`: closed by restoring the README release-asset contract.

Later-round orchestration, immutable attempt directories, and LLM proposal authority remain
explicitly deferred to their V2 stages. They are not claimed as completed by this report.
