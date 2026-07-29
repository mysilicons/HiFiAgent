# V2 Stage 10 and 11 acceptance report

Date: 2026-07-29. Result: **PASS**.

## Stage 10 acceptance matrix

| Acceptance requirement | Observed evidence | Result |
|---|---|---|
| Report alone identifies final choice and stop reason | `STOP_PLATEAU`, no selected candidate, final incumbent `baseline` | PASS |
| Parameters equal actual argv | all four `attempt_002` values match requested/approved/rendered/realized/argv contract | PASS |
| LLM content cannot masquerade as fact | four disjoint evidence classes; LLM block labelled not fact | PASS |
| All candidates appear in history | baseline, failed attempt 001, completed attempt 002, and rejected fixture proposals | PASS |
| STOP is not shown as successful optimization | schema rejects STOP+success; genuine report says `STOPPED`/false | PASS |
| Required 13 sections and history tables exist | Markdown plus `all_runs.tsv` and `all_parameters.tsv` | PASS |
| Absolute paths are redacted by default | recursive JSON/Markdown scan finds no workspace/home absolute path | PASS |
| Failed and V1 histories remain reportable | failed-attempt and `V1_COMPATIBILITY` tests | PASS |

The genuine report records DeepSeek model `deepseek-v4-pro`, response
`e7377a3b-312e-417a-9f2a-472f77feb665`, index SHA-256
`cdd442ce8fa0321e66cea9aa3bc42b79786c16b6ba9a2eddb22830f152c03bbe`, prompt SHA-256
`a99856e853ec287ba19348a874cc2e56d65678b36dbe5bcb1597a10cf4a4bf16`, and 7,970
tokens. DeepSeek returned zero raw proposals; the deterministic rule candidate remained authoritative.

## Stage 11 acceptance matrix

| Requirement | Observed evidence | Result |
|---|---|---|
| Schema/contract/arbiter/comparator/stopping tests | full portable suite and five V2 safety scenarios | PASS |
| State transition and three-round tests | round 1–3, interruption, idempotence, budget, and duplicate tests | PASS |
| Nextflow compile and resume | Java 21 / Nextflow 25.04.7 workflow gates | PASS |
| Mock LLM, injection, and authority tests | structured client, malicious document, whitelist, and Safety Arbiter tests | PASS |
| Repaired real single-variable candidate | failed attempt 001 retained; `disable_post_join=true` attempt 002 contract PASS | PASS |
| Second real sample | complete Drosophila `SRR33554835` FASTQ hash/header/stats verified | PASS |
| CPU, walltime, disk, and LLM costs | trace/receipt/inventory plus live DeepSeek token receipt | PASS |
| A–D ablation | all four required configurations and common metrics emitted | PASS |

## Genuine data results

| Sample | Accession | Bytes | Reads | Bases | Full SHA-256 |
|---|---|---:|---:|---:|---|
| Candida albicans | SRR23724250 | 9,685,432,968 | 324,036 | 4,829,675,432 | PASS |
| Drosophila melanogaster | SRR33554835 | 34,915,862,206 | 2,430,495 | 17,357,574,041 | PASS |

Candida candidate metrics remained identical to baseline, so material-improvement and
hard-regression rates were both 0, and plateau-stop accuracy was 1.0. The genuine cost includes
the publish-collision failure and repaired retry: 8.223183 actual CPU hours, 0.748806 elapsed
hours, and 35,383,983,567 retained bytes. Average assembly attempts including baseline were 3.

The A baseline group performs no adaptive stop. B rules-only, C rules+RAG explanation, and D hybrid
all retained candidate legality 1.0, safety-scenario rejection accuracy 1.0, duplicate rate 0,
and plateau accuracy 1.0. D made one genuine DeepSeek call (5,855 prompt and 2,115 completion
tokens), with zero LLM proposals and zero fallback rate; no biological gain is attributed to it.
The human-review agreement field uses the predeclared acceptance labels, not a blinded external
review panel.

## Quality gates

```text
Stage 10/11 focused portable acceptance: 26 passed
Full portable pytest: 350 passed, 17 skipped
Configured coverage: 87.10% (required 85%)
V2 report module coverage: 92%
V2 benchmark module coverage: 99%
Genuine Candida + Drosophila acceptance: 1 passed in 35.02s
Ruff check: PASS
Ruff format --check: PASS
mypy strict: PASS
Nextflow 25.04.7 with Java 21: PASS
```

The biological inputs and generated real reports remain ignored under `Data/` and `results/`.
Committed tests and the versioned sample manifest reproduce the verification when retained data are
available.
