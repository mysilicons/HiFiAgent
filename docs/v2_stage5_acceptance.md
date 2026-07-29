# V2 Stage 5 acceptance report

Date: 2026-07-15. Result: **PASS**.

## Acceptance matrix

| Requirement | Evidence | Result |
|---|---|---|
| Upgrade source catalog to V2 | schema/catalog validation tests | PASS |
| Evidence level and authorization scope on every source | complete 16-source catalog audit | PASS |
| Verify local SHA-256 and URL/version metadata | real index build plus mismatch negative test | PASS |
| Parameter/problem/input tags | catalog and indexed chunk assertions | PASS |
| Stale-source check | stale warning and authorization-removal test | PASS |
| Prefer actual hifiasm version | exact/mismatch ranking and executed-manifest test | PASS |
| Dedicated evidence for four parameters | index manifest parameter evidence map | PASS |
| Prompt-injection fixture | quarantined chunk excluded from retrieval | PASS |
| Retrieval trace and index manifest | schema round-trip and artifact tests | PASS |
| Every whitelist parameter has official evidence | catalog and built-index double gate | PASS |
| Version mismatch is downgraded and warned | score ordering and warning assertion | PASS |
| No parameter evidence means no LLM call | unauthorized-tag call-count test | PASS |
| Results contain only catalog source IDs | index invariant and trace subset tests | PASS |
| Malicious instructions cannot enter execution path | quarantine-before-retrieval test | PASS |

## Governed index receipt

```text
catalog schema/version: 2.0 / 2.0.0
target hifiasm: 0.25.0-r726
sources: 16
chunks: 336
stale-source warnings: 0
quarantined production chunks: 0
purge_level official sources: hifiasm_faq, hifiasm_hifi_only, hifiasm_parameters
purge_similarity official sources: hifiasm_faq, hifiasm_parameters
hom_cov official sources: hifiasm_faq, hifiasm_output, hifiasm_parameters
disable_post_join official sources: hifiasm_faq, hifiasm_parameters
```

## Retained Candida read-only retrieval audit

The retained baseline manifest reports hifiasm `0.25.0-r726`. Read-only retrieval returned only
catalog sources, all hifiasm hits were exact-version matches, and no mismatch/stale warning was
emitted. No file under the retained run was written.

## Quality gates

```text
Stage 5 RAG governance tests: 27 passed
Stage 5 plus CLI focused regression: 38 passed
Final full pytest: 268 passed, 13 skipped
Ruff check: PASS
Ruff format --check: PASS (93 files)
mypy strict: PASS (93 source files)
Coverage: 83.71% (required 80%; entire `hifi_agent.rag` package included)
```

The 13 skips remain explicit retained-data/live-API gates. Stage 5 uses only local evidence and did
not call an external LLM or launch an assembly.
