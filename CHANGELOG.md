# Changelog

All notable changes are documented here. This project follows Semantic Versioning.

## [2.0.0] - 2026-07-29

### Added

- Immutable V2 run/attempt/round schemas and a single orchestration controller.
- Typed QC features, evidence-governed RAG, strict DeepSeek proposal parsing, and deterministic
  Safety Arbiter approval.
- Candidate argv round-trip contracts, unique attempt directories, and real execution receipts.
- Versioned multi-metric comparison policy with hard-regression, plateau, conflict, budget, and
  maximum-three-round stop outcomes.
- V2 JSON/Markdown/TSV reports tracing approved parameters to actual argv and artifacts.
- Genuine Candida closed-loop acceptance, full-checksum Candida/Drosophila input audit, five
  comparator safety scenarios, and A/B/C/D ablation.
- Data-free `demo-v2`, V1→V2 migration guide, privacy/cost disclosure, three-round example, and
  clean-clone release verification.

### Changed

- LLM is now permitted to propose schema-valid whitelist candidates, but only the deterministic
  Safety Arbiter can issue an `ApprovedCandidate`; the execution boundary remains non-LLM.
- Default optimization is one candidate per round and at most three rounds.
- The V2 comparison policy is packaged into the wheel instead of being read from the source tree.

### Known limitations

- The genuine Candida candidate completed and passed its parameter contract, then stopped at a
  material plateau; no biological improvement is claimed.
- Drosophila is a genuine full-FASTQ integrity/scale audit, not a completed assembly claim.
- Same-read Merqury evidence remains advisory; independent reads are preferred.
- DeepSeek monetary price is not frozen. The retained live acceptance records token counts, model,
  endpoint class, and response hash, but no API key or raw private prompt.

## [1.0.0] - 2026-07-14

### Added

- Validated single-sample PacBio HiFi configuration and provenance receipts.
- Nextflow DSL2 pre-QC, hifiasm baseline, post-QC, and resume workflow.
- Versioned expert rules with bounded parameter whitelist and explicit stop states.
- Budgeted Agent controller, local RAG index, and constrained DeepSeek explanation layer.
- One-round closed-loop candidate comparison with multi-metric hard gates.
- Markdown/JSON/TSV reporting with sensitive-path redaction.
- Ten-scenario Stage 13 benchmark, A/B/C/D comparison, ablations, and Agent metrics.
- Portable demo, user/developer guides, rule catalog, release checklist, and citation metadata.

### Known limitations

- V1 supports one diploid-oriented HiFi-only sample; it does not support Hi-C, trio, ONT,
  polyploid optimization, scaffolding, annotation, or unbounded search.
- Same-read k-mer evaluation is advisory rather than independent validation.
- RAG/LLM explanations never authorize parameters or shell execution.
- The retained Candida Stage 11 candidate is explicitly synthetic and not a scientific result.
