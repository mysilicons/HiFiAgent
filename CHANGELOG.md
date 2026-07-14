# Changelog

All notable changes are documented here. This project follows Semantic Versioning.

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
