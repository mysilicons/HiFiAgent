# Resume summary and interview Q&A

## Resume summary

Built a production-style PacBio HiFi assembly Agent using Python, Pydantic, Nextflow DSL2,
hifiasm, multi-dimensional QC, deterministic expert rules, bounded optimization, local RAG, and
DeepSeek-compatible structured explanations. Implemented provenance, failure recovery, safety
budgets, 10 automated benchmark scenarios, 82.06% safety-critical test coverage, and a real
Candida albicans retained-data demonstration.

## Questions

**Why is this an Agent rather than a wrapper script?**  It has explicit state, tool contracts,
budget accounting, evidence-conditioned decisions, bounded action proposals, retry/stop policies,
and an auditable trace. It still delegates execution to a deterministic workflow.

**Why not let the LLM choose hifiasm parameters?**  Model output is nondeterministic and may invent
options. Rules own authority; RAG adds source-grounded explanation and is verified not to change
the decision or candidate set.

**Why can STOP count as success?**  Scientific automation should refuse unsafe inference. Low
coverage, missing QC, contradictory metrics, or unsupported ploidy are correctly handled by a
terminal stop rather than blind tuning.

**Why is N50 insufficient?**  It can improve while BUSCO completeness, k-mer quality, mapping, or
structural correctness regress. The Stage 11 ablation intentionally reproduces that trap.

**What is the biggest V1 limitation?**  It is intentionally single-sample and diploid-oriented,
and same-read k-mer evaluation is advisory. V2 should add independent evidence and broader data
types only with new schemas, rules, and benchmarks.
