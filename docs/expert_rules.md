# Expert Rule Standard

**English** | [简体中文](zh-CN/expert_rules.md)

Expert rules convert typed, applicable QC evidence into bounded actions. They are versioned policy,
not free-form advice, and cannot directly execute tools.

## Fundamental constraints

- Rules consume schema-validated features and explicit applicability states.
- A rule may stop, request review, or propose only an allowlisted single-variable change.
- Missing or conflicting evidence causes conservative behavior; it is never treated as success.
- N50 or assembly size alone cannot authorize a candidate or override a protected regression.
- Threshold, rationale, evidence source, supported tool version, and tests must be traceable.

## Actionable quality signals

Signals include expected-size agreement when a trusted size exists, BUSCO completeness and
duplication, k-mer completeness and QV, read mapping, coverage uniformity, contiguity, and
reference-based misassembly only when a trusted reference is supplied. Same-read k-mer evidence is
marked advisory. Rules must distinguish unavailable, inapplicable, warning, and failing evidence.

## Parameter allowlist

Only audited hifiasm parameters represented by the internal schema may change. Each candidate may
change one parameter, within declared type/range and risk limits, from the current incumbent. Unknown
flags, raw argv fragments, shell syntax, multiple simultaneous changes, and duplicate fingerprints
are rejected before execution. Adding a parameter requires design review, governed evidence, argv
round-trip support, and positive and negative tests.

## Governed retrieval

Knowledge snippets are packaged, indexed, source-diverse, checksum-bound, and mapped to permitted
parameters and tool versions. Retrieval does not grant authorization by itself. Unsupported versions,
missing provenance, prompt injection, or a snippet outside its declared parameter scope fails closed.

## Comparison policy

Eligible candidates must have the same post-QC contract and required metrics. Default hard
regressions include a 2-point BUSCO completeness drop, 2-point k-mer completeness drop, 2-point k-mer
QV drop, 0.02 mapped-read-fraction drop, 0.25 coverage-CV increase, and—when applicable—a 20%
relative QUAST misassembly increase. A 10% N50 gain is material only when no protected regression
exists. The authoritative values are the packaged comparison policy and its immutable run snapshot.

## Stop conditions

The coordinator stops explicitly when the baseline is accepted, evidence is insufficient, no legal
candidate exists, a rule requires stopping, human confirmation is required, budget is exhausted,
the comparison plateaus, or the configured maximum round is reached. Tool, contract, state, and
required-provider failures are engineering terminal states, not scientific comparisons.

## Audit requirements

Each action must trace context and typed metrics → matched rules and governed sources → requested
change → safety decision → approved full configuration → rendered and realized argv → attempt
inventory and metrics → comparison → incumbent update or stop. New rules require positive,
boundary, conflicting-evidence, missing-evidence, and unauthorized-action coverage.
