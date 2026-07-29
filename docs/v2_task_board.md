# HiFi Agent V2 local milestone and issue board

This file is the auditable local source of truth for V2 work. Creating or changing remote GitHub
issues is an external operation and is not required to reproduce the repository. Remote milestones
may mirror these stable IDs without replacing them.

## Milestones

| Milestone | V2 stages | Exit condition |
|---|---|---|
| V2-M1 Correct execution | 0–2 | Parameter contract passes; history design is implemented |
| V2-M2 Unified baseline | 3–4 | One resumable command completes baseline and QC review |
| V2-M3 Controlled proposals | 5–6 | RAG/LLM proposals are structured and safety-approved |
| V2-M4 Candidate loop | 7–9 | Real candidates and up to three rounds are controlled |
| V2-M5 Release | 10–12 | Reports, benchmark, real acceptance, and clean-clone gates pass |

## Stage 0 and 1 issues

| Issue | Milestone | Dependency | Status | Acceptance evidence |
|---|---|---|---|---|
| V2-000 Freeze scope and terminology | V2-M1 | none | complete | `v2_scope.md`, ADR 0002 |
| V2-001 Capture V1 regression baseline | V2-M1 | V2-000 | complete | stage 0 Markdown/JSON baseline |
| V2-002 Register known defects | V2-M1 | V2-000 | complete | `v2_known_defects.md` |
| V2-101 Omit missing Nextflow parameters | V2-M1 | V2-001 | complete | optional-parameter tests |
| V2-102 Implement bidirectional hifiasm contract | V2-M1 | V2-101 | complete | contract unit/integration tests |
| V2-103 Isolate invalid Candida candidate | V2-M1 | V2-102 | complete | exact `true` regression fixture and retained-command audit |
| V2-104 Restore portable quality gates | V2-M1 | V2-101..103 | complete | `v2_stage1_acceptance.md` |

Statuses become `complete` only after the final stage acceptance report records all required gates
as passing. Later-stage issues are defined in `HiFi_Agent_V2_Project_Plan.md` and will be expanded
when their milestone begins.

## Retained real-data policy

- Biological inputs and run outputs remain excluded from Git.
- `input_checksums.tsv` is the run-specific identity source; validation re-hashes recorded inputs.
- A retained acceptance dataset must document sample ID, source, expected paths, checksum manifest,
  tool/database versions, and explicit acceptance environment switch.
- Tests must never rewrite retained artifacts merely to make an old run conform to a new schema.
- Invalid runs remain evidence and are excluded by a deterministic validation failure.

## Stage 2 and 3 issues

| Issue | Milestone | Dependency | Status | Acceptance evidence |
|---|---|---|---|---|
| V2-201 Add V2 optimization and identity schemas | V2-M1 | V2-104 | complete | schema and identity tests |
| V2-202 Implement immutable attempt history | V2-M1 | V2-201 | complete | retry/idempotence/tamper tests |
| V2-203 Add read-only V1 migration inspection | V2-M1 | V2-202 | complete | CLI filesystem snapshot and retained Candida audit |
| V2-301 Add unified `assemble` entry | V2-M2 | V2-201..203 | complete | CLI and controller tests |
| V2-302 Execute missing baseline/candidate artifacts | V2-M2 | V2-301 | complete | real-adapter executor-call tests |
| V2-303 Add atomic resume and idempotence | V2-M2 | V2-202, V2-301 | complete | interruption/report/tamper/trace tests |
| V2-304 Remove duplicate post-QC evaluation | V2-M2 | V2-301 | complete | legacy controller call-count test |

## Stage 4 issues

| Issue | Milestone | Dependency | Status | Acceptance evidence |
|---|---|---|---|---|
| V2-401 Add stable QC feature evidence schema | V2-M2 | V2-301 | complete | bundle schema, byte-stability, round-trip tests |
| V2-402 Normalize genome size and coverage evidence | V2-M2 | V2-401 | complete | expected/conflict/unknown/extreme boundary tests |
| V2-403 Enforce k-mer confidence authorization | V2-M2 | V2-401 | complete | low/multiple/failed/same-data and rule integration tests |
| V2-404 Add sanitized LLM summary and provenance | V2-M2 | V2-401 | complete | path-redaction and metadata-source tests |
| V2-405 Integrate bundle into unified baseline | V2-M2 | V2-301, V2-401 | complete | no-expensive-rerun controller test |
| V2-406 Complete Stage 4 quality gates | V2-M2 | V2-401..405 | complete | `v2_stage4_acceptance.md` |

## Stage 5 issues

| Issue | Milestone | Dependency | Status | Acceptance evidence |
|---|---|---|---|---|
| V2-501 Upgrade knowledge catalog schema | V2-M3 | V2-406 | complete | V2 catalog schema and 16-source audit |
| V2-502 Verify checksums, versions, and freshness | V2-M3 | V2-501 | complete | checksum/stale/version negative tests |
| V2-503 Add parameter-scoped official evidence | V2-M3 | V2-501 | complete | four-parameter index manifest coverage |
| V2-504 Add version-aware catalog-bounded retrieval | V2-M3 | V2-502..503 | complete | ranking, warning, and unknown-source tests |
| V2-505 Quarantine prompt-injection content | V2-M3 | V2-501 | complete | malicious document fixture test |
| V2-506 Emit retrieval and index audit artifacts | V2-M3 | V2-502..505 | complete | trace/manifest schema tests |
| V2-507 Complete Stage 5 quality gates | V2-M3 | V2-501..506 | complete | `v2_stage5_acceptance.md` |

## Stage 6 issues

| Issue | Milestone | Dependency | Status | Acceptance evidence |
|---|---|---|---|---|
| V2-601 Add strict LLM proposal schemas | V2-M3 | V2-507 | complete | schema/type/range/extra-field tests |
| V2-602 Build evidence-bound structured proposer | V2-M3 | V2-601 | complete | stable prompt/fingerprint and provider tests |
| V2-603 Implement deterministic Safety Arbiter | V2-M3 | V2-601..602 | complete | attack, STOP, confidence, risk, budget tests |
| V2-604 Support all three decision modes | V2-M3 | V2-602..603 | complete | rules-only/hybrid/disabled and fallback tests |
| V2-605 Merge, deduplicate, and cap candidates | V2-M3 | V2-603 | complete | global fingerprint and candidate-limit tests |
| V2-606 Emit proposal and retrieval audit receipts | V2-M3 | V2-602..605 | complete | JSON/JSONL receipt and hash tests |
| V2-607 Run genuine Candida acceptance | V2-M3 | V2-601..606 | complete | checksum-bound real-data integration test |
| V2-608 Complete Stage 6 quality gates | V2-M3 | V2-601..607 | complete | `v2_stage6_acceptance.md` |
