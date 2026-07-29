# V1 → V2 migration

## Safety rule

V2 never rewrites a V1 result directory. Migration is an inspection-and-new-run workflow:

1. preserve the V1 directory and its checksums;
2. inspect it with `hifi-agent migrate-v1 V1_RUN_DIR`;
3. create a new V2 output root and configuration;
4. run V2 baseline/candidates there;
5. keep V1 and V2 provenance independently addressable.

`migrate-v1` is intentionally read-only. An `--execute` mode is rejected because silently
converting mutable historical files would break auditability.

## Configuration mapping

| V1 | V2 | Action |
|---|---|---|
| `agent.max_retry_rounds` | `optimization.max_rounds` | choose `1..3`; default V2 is `3` |
| `agent.max_candidates_per_round` | `optimization.max_candidates_per_round` | default `1` |
| implicit multi-parameter retry | `optimization.allow_multi_parameter_candidates` | default `false`; require explicit approval |
| baseline/candidate folders | immutable `run_id` + `attempt_id` + round records | do not copy old attempt folders |
| rule explanation | typed proposal + evidence + arbiter result | proposal is not approval |

V1 keys remain readable where compatibility is declared, but they do not grant V2 execution
authority. Validate the new file before any workflow:

```bash
hifi-agent validate sample-v2.yaml
hifi-agent assemble sample-v2.yaml
```

## Result interpretation changes

- V2 distinguishes `CandidateProposal`, `ApprovedCandidate`, execution attempt, comparison, and
  terminal outcome.
- `STOP_PLATEAU`, `STOP_CONFLICT`, `STOP_BUDGET`, `STOP_INSUFFICIENT_METRICS`, and
  `STOP_MAX_ROUNDS` are safe terminal outcomes, not generic failures.
- A report must show proposed parameters, approved parameters, actual hifiasm argv, parameter
  contract status, metrics, artifacts, and stop evidence.
- LLM text is advisory evidence. It does not authorize execution.

## Rollback

Rollback means selecting the untouched V1 directory and V1 package/tag. Do not point V1 and V2 at
the same `outdir`. Because migration performs no in-place write, rollback requires no reverse
conversion.
