# V1 expert rule catalog

The authoritative definitions are `rules/v1_rules.yaml`; thresholds and provenance are in
`configs/thresholds.yaml`. Higher priority controls lower priority. Equal-priority conflicts stop
and emit no candidate.

| Priority | Rule | Decision / action | Risk | Max candidates |
|---:|---|---|---|---:|
| 100 | INPUT_NOT_HIFI_STOP | STOP / STOP_UNSUPPORTED_INPUT | high | 0 |
| 99 | PLOIDY_OUTSIDE_DIPLOID_STOP | STOP / STOP_OUT_OF_SCOPE_PLOIDY | high | 0 |
| 98 | EVALUATION_TOOL_FAILURE_STOP | STOP / STOP_EVALUATION_INCOMPLETE | high | 0 |
| 95 | COVERAGE_INSUFFICIENT_STOP | STOP / STOP_LOW_COVERAGE_SEARCH | high | 0 |
| 90 | MULTI_METRIC_CONFLICT_STOP | STOP / REQUIRE_HUMAN_REVIEW | high | 0 |
| 85 | CORE_METRICS_MISSING_STOP | STOP / STOP_INSUFFICIENT_CORE_METRICS | high | 0 |
| 80 | ASM_SIZE_TOO_LARGE_AND_DUPLICATED | RETRY / PROPOSE_STRONGER_PURGE | medium-high | 1 |
| 75 | ASM_SIZE_LARGE_DUPLICATION_LOW_REVIEW | STOP / REVIEW_GENOME_SIZE_ESTIMATE | medium | 0 |
| 72 | HIGH_N50_STRUCTURAL_ERROR_DISABLE_JOIN | RETRY / PROPOSE_DISABLE_POST_JOIN | medium | 1 |
| 70 | HOM_COV_TRUSTED_KMER_CONFLICT | RETRY / PROPOSE_HOM_COV | medium-high | 1 |
| 65 | COVERAGE_WARNING_KEEP_BASELINE | BASELINE / KEEP_BASELINE_LOW_COVERAGE_WARNING | medium | 0 |
| 60 | GENOME_SIZE_UNKNOWN_KEEP_BASELINE | BASELINE / KEEP_BASELINE_REDUCED_COVERAGE_CONFIDENCE | medium | 0 |
| 55 | INBRED_ALLOW_DISABLE_PURGE | RETRY / PROPOSE_DISABLE_PURGE | medium | 1 |
| 20 | METRICS_NORMAL_ACCEPT_BASELINE | BASELINE / ACCEPT_DEFAULT_PARAMETERS | low | 0 |

These are conservative engineering defaults, not universal biological laws. Threshold updates
must change catalog versions and explain organism, ploidy, evidence source, and tradeoffs.
