# V2 Stage 6 acceptance report

Date: 2026-07-29. Result: **PASS**.

## Acceptance matrix

| Requirement | Evidence | Result |
|---|---|---|
| Structured proposer and strict JSON schema | `rag/proposer.py`, Pydantic extra/type tests | PASS |
| Legal proposal becomes `ApprovedCandidate` | exact requested/approved and fingerprint test | PASS |
| Unknown parameters and fields execute nothing | schema failure and zero-approval test | PASS |
| Shell, flags, paths, and environment text rejected | long/short flag and unsafe-text tests | PASS |
| Only retrieved source IDs are accepted | unknown and parameter-scope source tests | PASS |
| Only real metric IDs are accepted | invented metric test | PASS |
| Confidence cannot exceed evidence | rule/source/QC confidence-cap tests | PASS |
| BUSCO percentage cannot be scaled 100 times | `0.8` versus `80%` attack test | PASS |
| Seen parameter sets are rejected | stable global SHA-256 fingerprint test | PASS |
| Candidate count is at most two | excess proposal rejection test | PASS |
| STOP rule cannot be overridden | no-provider-call STOP test | PASS |
| `hom_cov` requires trusted k-mer evidence | low-confidence real-shaped QC test | PASS |
| Medium-high/high risk requires confirmation | confirmed/unconfirmed branch test | PASS |
| Exhausted compute budget starts no proposal | zero-budget no-call test | PASS |
| Timeout, 429, 5xx, and invalid JSON degrade safely | provider and proposer failure tests | PASS |
| Prompt injection does not reach the prompt | quarantined chunk test | PASS |
| Three decision modes are network-auditable | provider call-count tests | PASS |
| `require_llm` stops instead of falling back | `STOP_LLM_REQUIRED` test and config invariant | PASS |
| Prompt/model/provider/token use are recorded | hash and safe metadata tests | PASS |
| Fixed inputs and fixed output are stable | bundle and prompt SHA equality test | PASS |

## Genuine Candida acceptance

The gated test `tests/integration/test_real_stage6_proposer_acceptance.py` was run with
`HIFI_AGENT_REAL_ACCEPTANCE=1`.

- Real HiFi FASTQ: 9,685,432,968 bytes;
- FASTQ SHA-256: `cde62d7e3754ca81fdd24c902f2f4b3beaa0814932015e57527486bdf365e8c1`;
- real reference SHA-256:
  `32d5d3189a4813f0f095393de325c124f65712ad6376dc5ac7e38bd304e19b64`;
- real baseline metrics included N50 1,247,647 and 163 reference-based QUAST
  misassemblies;
- real deterministic decision: `RETRY / PROPOSE_DISABLE_POST_JOIN`;
- rules-only approved exactly `disable_post_join=true`;
- fixed structured hybrid response over the genuine prompt was rejected as an already-seen
  fingerprint rather than executed twice;
- all Stage 6 outputs were redirected to pytest temporary storage;
- retained Candida artifacts had identical size and mtime before and after acceptance.

Result:

```text
1 passed
```

After explicit user authorization, a live DeepSeek request was run with the genuine
Candida-derived, path-free prompt:

```text
provider/model: deepseek / deepseek-v4-pro
LLM status: SUCCESS
terminal status: CANDIDATES_APPROVED
prompt SHA-256: a99856e853ec287ba19348a874cc2e56d65678b36dbe5bcb1597a10cf4a4bf16
proposal SHA-256: e45ace004493531c632d8b44720be1cfe73da5247e5cc0892102728e7be5e085
tokens: 5,855 prompt + 2,115 completion = 7,970 total
```

The provider returned a schema-valid empty proposal list. The arbiter therefore retained only the
deterministic `disable_post_join=true` rule candidate. All nine safety checks passed. The request
contained no FASTQ bases, reference sequence, absolute workspace path, API key, or environment
variable. The sanitized receipt is retained in
`benchmark/reports/v2_stage6_live_deepseek_acceptance.json`.

## Quality gates

```text
Stage 6 proposer tests: 22 passed
Stage 6 provider tests: 14 passed
Full portable pytest: 306 passed, 14 skipped
Ruff check: PASS
Ruff format --check: PASS (98 files)
mypy strict: PASS (97 source files)
Coverage: 85.38% (required 85%)
Genuine Candida acceptance: 1 passed
Live DeepSeek acceptance: PASS
```

The portable-suite skip for this real acceptance is expected because the same test is run
separately with its explicit environment gate. Other retained/live gates belong to later stages.
Stage 6 launches no Nextflow process and no biological assembly.
