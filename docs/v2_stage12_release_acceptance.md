# V2 Stage 12 release acceptance

Date: 2026-07-29

Version: `2.0.0`

Result: **PASS**

## Acceptance mapping

| Project-plan criterion | Evidence | Result |
|---|---|---:|
| P0/P1 closed | `docs/v2_known_defects.md`, Stage 1–11 acceptance | PASS |
| all portable tests/gates | 353 passed, 17 explicit-real skips; coverage 87.14% ≥85%; Ruff/format/mypy | PASS |
| real candidate contract | genuine Candida `attempt_002`, `disable_post_join=true`, parsed contract | PASS |
| three complete rounds | production `OptimizationLoop` fixture, `STOP_MAX_ROUNDS` | PASS |
| real repaired candidate | one approved variable, genuine execution and homologous post-QC | PASS |
| report traces actual argv | Stage 10 report + Stage 7 manifest/parameter lineage | PASS |
| truthful LLM authority docs | README/user/architecture/privacy docs | PASS |
| portable installed demo | wheel install outside repository, 5/5 | PASS |
| genuine input audit | full Candida + Drosophila FASTQ SHA-256/size/header | PASS |
| clean clone | commit `2469b9d`, all public help, README quickstart, release tests, isolated wheel | PASS |
| annotated tag | created only after final commit and clean-tree verification | PASS |

## Genuine evidence

The current V2 real-data suite passed 4/4 selected acceptance tests:

```text
test_real_stage6_proposer_acceptance.py
test_real_stage7_candidate_acceptance.py
test_real_stage8_stage9_acceptance.py
test_real_v2_stage10_stage11_acceptance.py
```

Those tests read and hash the genuine 9,685,432,968-byte Candida FASTQ and
34,915,862,206-byte Drosophila FASTQ. Candida baseline plus the repaired single-variable candidate
were evaluated. Candidate contract and actual argv lineage passed; the scientifically correct
outcome was `STOP_PLATEAU`, with no optimization improvement claim. Drosophila is only an
independent genuine-input integrity/scale audit.

The retained real DeepSeek receipt records `SUCCESS`, model `deepseek-v4-pro`, 5,855 prompt tokens,
2,115 completion tokens (7,970 total), response/prompt hashes, zero raw candidates, and all
sensitive-payload checks false. Stage 12 revalidated it against the fixed knowledge-index hash; it
did not make a new paid API call.

## Quality and installation

- pytest: 353 passed, 17 skipped behind explicit real-data switches;
- safety coverage: 87.14%, required 85%;
- Ruff, Ruff format, strict mypy: PASS;
- Nextflow 25.04.7 configuration parse with Java 21: PASS;
- wheel: `hifi_agent-2.0.0-py3-none-any.whl`;
- clean-clone reproducible SHA-256:
  `71b9164d66630a3ea0bbbe22a26db129b96155a42f91c30f3098a6f3c45a35fa`;
- isolated target install: version 2.0.0, packaged policy 2.0.0, CLI help and demo 5/5: PASS.

The clean clone ran `--help` for every public CLI command, the README quickstart, 7/7 release
tests, a source build with fixed `SOURCE_DATE_EPOCH`, and a second isolated wheel installation.

## Explicit non-pass observation

Enabling the shared historical real-data switch over every integration file produced 12 failures,
3 passes, and 1 live-API skip because 11 V1 tests still target removed
`results/Candida_albicans_phase6` artifacts. One historical test also rebuilt the ignored knowledge
index; the fixed, DeepSeek-bound index was restored and its expected SHA-256 revalidated.

These V1 artifacts are not V2 release evidence, so they were not relabeled as passing. The current
V2 real suite above is the release gate. This limitation is retained here to keep the acceptance
record honest.

Machine-readable evidence:
[`benchmark/reports/v2_stage12_acceptance.json`](../benchmark/reports/v2_stage12_acceptance.json).
