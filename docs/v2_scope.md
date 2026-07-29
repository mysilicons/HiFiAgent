# HiFi Agent V2 scope freeze

Date: 2026-07-15. Status: frozen for stages 0 and 1.

## Objective

V2 will provide one resumable command that validates one PacBio HiFi sample, performs pre-QC,
runs a baseline hifiasm assembly, evaluates it, obtains bounded parameter proposals from expert
rules and optionally RAG/LLM, executes approved candidates, compares all results, and stops on
acceptance, plateau, safety, budget, tool failure, human review, or the three-round limit.

## Frozen terminology

- `baseline` is optimization round 0.
- At most three optimization rounds follow: `round_01` through `round_03`.
- Each optimization round may execute at most two candidates; the V2 default will be one.
- “No meaningful improvement” means no candidate passes hard quality protections while meeting at
  least one versioned material-change threshold.
- “Best” means the best-supported eligible candidate within the observed evidence, whitelist, and
  compute budget. It never means a globally optimal assembly.
- An incumbent is the accepted comparison reference entering a round.
- A tool retry retains the candidate identity but receives a new attempt identity.

## Frozen safety boundary

The initial V2 hifiasm whitelist remains `purge_level`, `purge_similarity`, `hom_cov`, and
`disable_post_join`. The LLM may propose only typed values for these fields. It may not emit a
shell command, choose threads or output paths, introduce flags, access arbitrary files, or execute
anything. Deterministic schema, evidence, risk, budget, fingerprint, and command-contract checks
must approve every candidate before execution.

## V2 non-goals

Hi-C, trio, ONT ultra-long integration, polyploid optimization, scaffolding, annotation, unbounded
search, arbitrary downloads, and direct LLM shell execution remain out of scope.

## Compatibility

Existing V1 run directories are read-only evidence. V2 must not silently migrate, rewrite, delete,
or treat them as V2-compliant. A future explicit migration command must default to dry-run. The
retained Candida artifacts are preserved in place; the invalid candidate command is registered in
`docs/v2_known_defects.md` and rejected by the V2 command contract.

## Stage dependency

No new real candidate may run until the stage 1 command contract passes. The LLM proposer may not
be connected to execution before the same contract and its negative tests pass.
