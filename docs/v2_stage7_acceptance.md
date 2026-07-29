# V2 Stage 7 acceptance report

Date: 2026-07-29. Result: **PASS**.

## Acceptance matrix

| Requirement | Evidence | Result |
|---|---|---|
| Executor accepts only `ApprovedCandidate` | strict CLI schema and non-approved JSON rejection | PASS |
| Input checksum, resource, and parameter preflight | tamper/resource/risk tests and real checksum re-hash | PASS |
| hifiasm cache compatibility | pre-launch exact version check and three bin SHA-256 values | PASS |
| Incompatible cache is rejected with reason | version-drift zero-runner test and FAILED receipt | PASS |
| requested/approved/rendered/realized match | real `parameter_lineage.json`, no differences | PASS |
| All scientific and audit artifacts retained | real 9,722-entry, 17,691,994,610-byte inventory | PASS |
| Baseline/candidate tool versions match | real `post_qc_homology.json`, no differences | PASS |
| Evaluation parameters match | BUSCO lineage, mapping filters, and k-mer-source signature | PASS |
| post-QC is bound to attempt | real attempt binding for `attempt_002` | PASS |
| Tool failure is not biological quality | separate failure category and fixed interpretation test | PASS |
| Failure retains partial outputs | real FAILED `attempt_001` plus partial inventory | PASS |
| Retry does not overwrite logs | real failed-log SHA-256 values unchanged after `attempt_002` | PASS |
| Resume and retry semantics | interruption resumes `attempt_001`; failure retries `attempt_002` | PASS |

## Genuine DeepSeek-approved Candida execution

The candidate fingerprint
`22e8817baaef124ad72862795a9bb3685b50994d6ec1952f419290dcd86ecfae`
is identical to the candidate retained by the genuine DeepSeek Stage 6 call
(`deepseek-v4-pro`, response ID `e7377a3b-312e-417a-9f2a-472f77feb665`).
DeepSeek returned a schema-valid empty LLM proposal list, so the Safety Arbiter retained the
deterministic, evidence-backed `disable_post_join=true` candidate.

Real inputs and execution:

- HiFi FASTQ: 9,685,432,968 bytes, checksum revalidated from the retained manifest;
- reference checksum and all input sizes revalidated;
- baseline hifiasm and runtime hifiasm: `0.25.0-r726`;
- three genuine baseline bins hashed and reused;
- realized command changed only by `-u0`; no `--hom-cov` was rendered;
- threads: 480 within the validated 480-thread limit;
- successful run: `candidate_r01_c01`, `attempt_002`;
- Nextflow: 6/6 tasks succeeded, 87.0 CPU hours;
- assembly: 512.929 real seconds, 534.051 CPU seconds, 8.612 GB peak RSS;
- mapping peak RSS: 21.5 GB;
- candidate post-QC: N50 1,247,647; QUAST misassemblies 163; BUSCO complete 98.2%;
  Merqury QV 20.29; mapped-read fraction 1.0;
- tool failures: none.

The first real execution (`attempt_001`) exposed a publish collision caused by creating the
candidate metadata destination before Nextflow. All six scientific tasks had succeeded, but the
manifest was not published. Stage 7 correctly retained the attempt as FAILED. The fix moved
pre-launch contract files under `workflow/00_metadata`; `attempt_002` then completed. The first
attempt's completion and hifiasm log hashes remained unchanged.

The retained scientific output remains under ignored `results/v2_stage7_candida`. The committed
gated test re-hashes real artifacts rather than trusting the report:

```text
HIFI_AGENT_REAL_ACCEPTANCE=1 \
  pytest -q tests/integration/test_real_stage7_candidate_acceptance.py
1 passed in 29.32s
```

## Quality gates

```text
Focused Stage 7/CLI/workflow regressions: 77 passed
Full portable pytest: 318 passed, 15 skipped
Configured coverage including the Stage 7 executor: 85.58% (required 85%)
Genuine Candida Stage 7 acceptance: 1 passed
Ruff check: PASS
Ruff format --check: PASS
mypy strict: PASS
```

The portable skip for the real Stage 7 test is expected; the retained-data test is run separately
with its explicit environment gate.
