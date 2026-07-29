# HiFi Agent V2 known-defect register

Date opened: 2026-07-15.

| ID | Priority | Defect | Evidence | Stage 0/1 disposition |
|---|---:|---|---|---|
| V2-P0-001 | P0 | Optional `hom_cov=None` was passed as an empty Nextflow value and realized as `--hom-cov true`. | Retained Candida `hifiasm_command.txt` | Fixed by omission plus bidirectional command contract; historical result rejected |
| V2-P0-002 | P0 | Approved candidate config was not compared with the realized hifiasm command. | V1 candidate executor and metadata | Fixed with requested/approved/rendered/realized/check artifacts |
| V2-P0-003 | P0 | Optional Nextflow values used empty strings for missing reference and BUSCO lineage. | `executors/nextflow.py` | Fixed by a common omit-when-missing encoder |
| V2-P1-001 | P1 | Optimization runner always starts at round 1 and compares with baseline. | `optimization/runner.py` | Deferred to V2 stages 8–9 |
| V2-P1-002 | P1 | `RETRY` outcome has no controller loop that starts the next round. | `optimization/engine.py` | Deferred to V2 stage 9 |
| V2-P1-003 | P1 | Real Stage 9 adapter loads existing candidate artifacts but does not execute missing candidates. | `agent/tools.py` | Fixed for V2 in Stage 3 with a separate read/execute adapter; legacy adapter retained |
| V2-P1-004 | P1 | V1 schema allows at most two retry rounds. | `schemas/sample.py`, `agent/models.py` | Fixed for V2 in Stage 2 with `OptimizationConfig.max_rounds<=3`; V1 field remains compatible |
| V2-P1-005 | P1 | Reusing a candidate run ID can overwrite published artifacts and optimization summaries. | Nextflow `publishDir overwrite:true` | Fixed in Stage 2: scientific publish overwrite defaults false; immutable attempts prevent logical reuse |
| V2-P1-006 | P1 | Controller calls the post-QC tool in both POST_QC and EVALUATE states. | `agent/controller.py` | Fixed in Stage 3: POST_QC retains typed metrics and EVALUATE consumes them |
| V2-P2-001 | P2 | RAG/LLM explains immutable rule candidates but cannot propose V2 candidates. | `rag/explainer.py` | Deferred to V2 stages 5–6 |
| V2-P2-002 | P2 | The working-tree regression suite had one README release-asset failure. | Stage 0 pytest baseline | Fixed in stage 1 |

## Invalid retained Candida candidate

The retained real command was:

```text
hifiasm ... -l 3 -s 0.55 --hom-cov true -u0 ...
```

The approved candidate intended `hom_cov=null` and `disable_post_join=true`. The result is therefore
not a controlled test of post-join behavior. It must remain retained for audit, but it is marked
`PARAMETER_CONTRACT_VIOLATION` and cannot participate in automatic selection. The stage 1 parser
reproduces this exact failure without modifying the retained data directory.

## Closure rule

A defect is only “fixed” when a negative regression test exists and the relevant stage acceptance
gate passes. Documentation alone does not close a defect.
