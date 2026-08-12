# Result Interpretation

**English** | [简体中文](zh-CN/result-interpretation.md)

Establish engineering integrity before interpreting scientific metrics. “Selected” means the
incumbent chosen among executed, eligible candidates under the recorded policy—not a global optimum.

## Start with deep verification

```bash
hifi-agent verify-run results/sample_001 --deep
```

Deep verification recomputes identity and snapshots, state/events/transactions/budgets, proposal and
parameter round trips, attempt completion and inventory, comparison and incumbent history, report
agreement, and provenance hashes. Continue after `PASS`; investigate every `WARNING`; stop scientific
interpretation on `FAIL` and preserve the evidence.

## Six canonical reports

| File | Purpose |
|---|---|
| `final_report.md` | Human-readable terminal outcome, selection, rounds, limits, and recommendations |
| `final_summary.json` | Authoritative machine-readable outcome, exit, incumbent chain, budget, attempts |
| `all_runs.tsv` | Attempt status, eligibility, metrics, and resource use |
| `all_parameters.tsv` | Requested, approved, rendered, and realized parameter relationships |
| `provenance.tsv` | Relative paths and hashes for inputs, decisions, attempts, comparisons, and reports |
| `verification_report.json` | Checks, warnings, failures, and final verification status |

Do not publish `final_report.md` alone. Reproducible review requires at least the summary, parameter
table, provenance, and verification report.

## Terminal outcomes and exits

Normal scientific outcomes include `ACCEPTED_BASELINE`, `STOP_MAX_ROUNDS`, `STOP_PLATEAU`,
`STOP_NO_LEGAL_CANDIDATE`, `STOP_RULE_DECISION`, and `STOP_INSUFFICIENT_EVIDENCE` (exit 0).
`STOP_HUMAN_REVIEW`, `STOP_CONFIRMATION_REQUIRED`, and `STOP_BUDGET` require action (exit 3).
Tool, parameter-contract, and state-integrity failures use exit 4; a required provider failure uses
exit 5. A scientific zero does not imply commercial fitness or a universal quality threshold.

## Core metrics

| Metric | Direction | Interpretation and limitation |
|---|---|---|
| `assembly_size_ratio` | near 1 | Applicable only with a trusted expected size |
| `busco_complete` | higher | Gene-space completeness; lineage and database version matter |
| `busco_duplicated` | usually lower | Interpret with ploidy, assembly size, and biology |
| `kmer_completeness` | higher | Read k-mer support for the assembly |
| `kmer_qv` | higher | K-mer consistency estimate, not independent base validation |
| `mapped_read_fraction` | higher | Read support; high mapping alone is insufficient |
| `coverage_cv` | usually lower | Coverage uniformity affected by repeats and filtering |
| `contig_n50` | higher continuity | Secondary; cannot override correctness/completeness regressions |
| `quast_misassemblies` | lower | Applicable only with a trusted reference |

Without independent `kmer_reads`, Merqury evidence is `same_data_advisory` and cannot replace
independent reads, maps, Hi-C, or manual structural validation.

## Recommended audit sequence

1. Confirm integrity in the verification report.
2. Check terminal outcome, selected run, and incumbent chain in the summary.
3. Identify eligible attempts in `all_runs.tsv`.
4. Compare protected baseline and selected metrics.
5. Verify the single change and requested → realized round trip.
6. Trace proposal → approval → attempt → comparison in provenance.
7. Review limitations and tool failures.
8. Apply independent, project-specific biological acceptance.

External reports should state input class, tool versions, configuration hash, terminal outcome,
selected attempt, protected metrics, independent-evidence availability, candidate count, stop reason,
and limitations. Avoid unsupported claims such as “optimal,” “error-free,” or “commercial-grade.”
