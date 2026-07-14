# HiFi Agent V1 public benchmark

- Status: **PASS**
- Project version: `1.0.0`
- Scenarios: 10
- Pass rate: 100.0%
- Nonexistent parameter rate: 0.0%
- Repeat consistency: 100.0%
- Public accessions: SRR23724250, CP128823.1

## Scenario results

| Scenario | Data | Expected | Observed | Action | Candidates | Result |
|---|---|---|---|---|---:|---|
| normal_hifi_metrics | synthetic_fixture | BASELINE | BASELINE | ACCEPT_DEFAULT_PARAMETERS | 0 | PASS |
| low_coverage_downsample | real_derived_perturbation | STOP | STOP | STOP_LOW_COVERAGE_SEARCH | 0 | PASS |
| oversized_duplicated_assembly | real_derived_perturbation | RETRY | RETRY | PROPOSE_STRONGER_PURGE | 1 | PASS |
| hom_cov_peak_conflict | real_derived_perturbation | RETRY | RETRY | PROPOSE_HOM_COV | 1 | PASS |
| inbred_sample | synthetic_fixture | RETRY | RETRY | PROPOSE_DISABLE_PURGE | 1 | PASS |
| high_n50_structural_error | real_derived_perturbation | RETRY | RETRY | PROPOSE_DISABLE_POST_JOIN | 1 | PASS |
| evaluation_tool_failure | synthetic_fixture | STOP | STOP | STOP_EVALUATION_INCOMPLETE | 0 | PASS |
| multi_metric_conflict | real_derived_perturbation | STOP | STOP | REQUIRE_HUMAN_REVIEW | 0 | PASS |
| insufficient_evidence | synthetic_fixture | STOP | STOP | STOP_INSUFFICIENT_EVIDENCE | 0 | PASS |
| candida_albicans_srr23724250 | public_real | STOP | STOP | REVIEW_GENOME_SIZE_ESTIMATE | 0 | PASS |

## Required method comparison

| ID | Method | Decision authority | Safety | Interpretation |
|---|---|---|---|---|
| A | Default hifiasm baseline | None | NOT_APPLICABLE | Produces an assembly but has no evidence-aware stop or retry policy. |
| B | Fixed pipeline without Agent | Fixed workflow | NOT_APPLICABLE | Adds reproducible QC but no adaptive expert decision. |
| C | Rules only | Versioned deterministic expert rules | PASS | Controls all parameter and stopping decisions without an LLM. |
| D | Rules + RAG/LLM | Rules immutable; RAG adds sourced explanation | PASS | Adds provenance and prose while preserving the deterministic decision. |

## Ablation conclusions

| Ablation | Safety regression | Conclusion |
|---|---|---|
| remove_rag | no | RAG improves traceable explanation and is not an authority for tuning. |
| n50_only_selector | yes | N50-only selection misses completeness and structural-quality regressions. |
| remove_failure_gate | yes | Engineering failures must be separated from biological decisions. |

## Interpretation limits

- Perturbed scenarios are metric-level safety tests, not biological truth claims.
- Only the Candida case consumed retained real workflow artifacts.
- Candidate execution compute cost is not estimated when no new candidate was run.

A safe STOP is counted as success when it is the expert-reviewed expected outcome.
