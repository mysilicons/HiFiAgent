# V2 Stage 8 and 9 acceptance report

Date: 2026-07-29. Result: **PASS**.

## Stage 8 acceptance matrix

| Required acceptance case | Executed evidence | Result |
|---|---|---|
| N50 +50% with BUSCO/k-mer hard regression is rejected | candidate classified `HARD_REGRESSION`; protected metrics recorded | PASS |
| All changes below material thresholds stop as plateau | `STOP_PLATEAU`, incumbent unchanged | PASS |
| One safe material improvement becomes incumbent | arbitrary-incumbent round-2 test selects the unique candidate | PASS |
| Multiple unresolved tradeoffs stop for review | two non-dominated candidates produce `STOP_CONFLICT` | PASS |
| Missing core metric prevents selection | missing k-mer QV produces `STOP_INSUFFICIENT_METRICS` | PASS |
| Invalid parameter contract cannot enter selection | invalid-contract candidate is excluded | PASS |
| Reference/genome-size applicability is respected | reference-free QUAST and untrusted size-ratio branches tested | PASS |
| Comparison evidence is retained | JSON, TSV, parameter diff, and tradeoff Markdown asserted | PASS |

## Stage 9 prescribed scenario matrix

| Scenario | Observed terminal behavior | Result |
|---|---|---|
| Baseline directly accepted | `ACCEPTED_BASELINE`, zero candidate calls | PASS |
| Round 1 improves, then accepted | round-1 candidate retained as selected incumbent | PASS |
| Round 1 improves, round 2 plateaus | stops in round 2 with round-1 incumbent | PASS |
| Rounds 1/2/3 all improve | creates `candidate_r02_c01` and `candidate_r03_c01`, then `STOP_MAX_ROUNDS` | PASS |
| Round 1 conflicts | immediate `STOP_CONFLICT` | PASS |
| Round 2 interrupted | resumes round 2; round 1 executes exactly once | PASS |
| All parameter sets have been seen | `NO_UNIQUE_CANDIDATE`, no duplicate execution | PASS |
| CPU budget permits only one candidate | second launch is forbidden with `STOP_BUDGET` | PASS |

An additional post-QC interruption test resumes the `COMPARE` phase without rerunning its completed
candidate. Identity, state tampering, canonical run-ID, and approved/executed parameter mismatch
tests also fail closed.

## Genuine Candida acceptance

The gated test re-hashed the retained input manifest and loaded the actual Stage 7
DeepSeek-approved candidate `candidate_r01_c01/attempt_002`. The candidate changes only
`disable_post_join=false -> true`. Baseline and candidate were evaluated with the homologous
Stage 7 pipeline.

| Metric | Baseline | Candidate | Comparison |
|---|---:|---:|---|
| contig N50 | 1,247,647 | 1,247,647 | unchanged |
| QUAST misassemblies | 163 | 163 | unchanged |
| BUSCO complete (%) | 98.2 | 98.2 | unchanged |
| BUSCO duplicated (%) | 0.8 | 0.8 | unchanged |
| k-mer completeness (%) | 61.1863 | 61.1863 | unchanged |
| k-mer QV | 20.29 | 20.29 | unchanged |
| mapped-read fraction | 1.0 | 1.0 | unchanged |
| coverage CV | 0.6728233769751378 | 0.6728233769751378 | unchanged |
| assembly-size ratio | unavailable | unavailable | not applicable: genome size untrusted |

Stage 8 therefore returned `STOP_PLATEAU`, retained `baseline` as incumbent, and selected no
candidate. Stage 9 consumed the same genuine attempt and independently reached `STOP_PLATEAU` in
round 1. It accounted 0.1483475 CPU hours and 0.1424803 wall-time hours exactly once. The five-event
trace ends with `NO_METRIC_EXCEEDED_MATERIAL_THRESHOLD`.

This is the scientifically valid real-data result. The acceptance did not launch artificial
round-2 or round-3 biological assemblies after a proven plateau. Those controller paths are
accepted using deterministic metric fixtures and the production `OptimizationLoop`, including
real canonical round IDs and persistence behavior.

The retained outputs remain ignored under `results/v2_stage8_stage9_candida`. Source and Stage 7
evidence sizes and modification times are asserted unchanged. Final evidence hashes are:

```text
comparison policy: b9f4a2ffc87e0aecf972db40f29e8b5aae7f6017c83223944d40c8bd0b779a59
Stage 8 comparison: 6f1848c7d2018d5b1f38f12eb5308090dccf21ec019dedea8bdba2ed8ec1b2b8
Stage 9 state:      b0ec56cf353e0146ad72bc408abbe23e6371c3d61c82270f6811c6481f9d5a62
Stage 9 trace:      a5d223debf9b03ca63c02ab2ef029990fadaf47cf9de15b5e045de721c39b30f
```

## Quality gates

```text
Focused Stage 8/9 behavior: 20 tests collected and passed
Full portable pytest: 339 passed, 16 skipped
Configured coverage: 86.25% (required 85%)
Genuine Candida Stage 8/9 acceptance: 1 passed in 7.86s
Ruff check: PASS
Ruff format --check: PASS
mypy strict: PASS
Nextflow 25.04.7 with Java 21: PASS
```

The real-data test is intentionally skipped in the portable suite and enabled only with
`HIFI_AGENT_REAL_ACCEPTANCE=1`.
