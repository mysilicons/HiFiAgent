# V2 Stage 8 design: incumbent-based comparison

Stage 8 replaces the baseline-only comparison path with `RoundComparator`. A round accepts any
completed incumbent plus one or two candidate attempts. The comparator never executes scientific
tools; it consumes the immutable configuration, parameter-contract status, execution status, and
homologous post-QC metrics established by Stage 7.

## Versioned scientific policy

`configs/comparison_policy.yaml` is strict, versioned policy `2.0.0`. Each metric declares its
direction, material threshold and mode, required status, applicability, optional hard-regression
threshold, and optional acceptance boundary. N50 is intentionally secondary: it cannot compensate
for a protected BUSCO, k-mer, mapping, or coverage regression.

Applicability is fixed before comparison:

- reference-free runs mark QUAST misassemblies `NOT_APPLICABLE`;
- untrusted genome-size evidence marks assembly-size ratio `NOT_APPLICABLE`;
- a missing required applicable metric yields `STOP_INSUFFICIENT_METRICS`.

An acceptance failure is reported when a changed candidate metric crosses a policy boundary.
Unchanged retained evidence below a generic boundary is not relabelled as a candidate-caused
failure; this distinction is necessary for honest comparisons of existing biological runs.

## Selection

Each candidate is classified separately as eligible, plateau, tradeoff, hard regression,
acceptance failure, unavailable, invalid contract, execution failure, or dominated. Candidate
versus incumbent differences determine material improvement and safety. Candidate-versus-candidate
Pareto dominance then removes candidates that are no better on any applicable metric.

Only one safe, non-dominated candidate with a material improvement updates the incumbent. All
sub-threshold changes produce `STOP_PLATEAU`; unresolved tradeoffs or multiple non-dominated
candidates produce `STOP_CONFLICT`; unsafe or invalid candidates are never selected.

Every persisted comparison writes:

- `round_comparison.json`;
- `round_comparison.tsv`;
- `parameter_diff.tsv`;
- `selection_tradeoffs.md`.

The `compare-stage7` CLI loads a retained baseline and Stage 7 attempt through strict evidence
adapters and applies the same comparator.
