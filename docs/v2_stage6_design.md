# V2 Stage 6 controlled parameter proposal design

## Authority boundary

Stage 6 generates and approves candidate descriptions. It never executes an assembler. Stage 7 may
consume only a validated `ApprovedCandidate`; raw provider output, prose, retrieval chunks, and
`LLMProposalBundle` objects are not executable inputs.

The authority order is:

1. deterministic STOP decisions;
2. schema, whitelist, range, evidence, risk, budget, and deduplication checks;
3. deterministic rule candidates;
4. optional structured LLM candidates;
5. Stage 7 execution, which remains outside this stage.

An arbiter either preserves a proposal exactly or rejects it. It cannot repair, clamp, rename, or
silently truncate parameter values.

## Models

- `ProposedParameter`: one typed value with source IDs, metric IDs, applicability, risks,
  uncertainty, rationale, and confidence;
- `LLMParameterProposal`: one candidate with unique parameter names;
- `LLMProposalBundle`: the only accepted provider JSON envelope;
- `ApprovedCandidate`: requested and approved values must be identical and its SHA-256 fingerprint
  must match those values;
- `RejectedProposal`: proposal identity, requested values, and deterministic reason codes;
- `ProposalDecisionBundle`: complete mode, provider, prompt/output hashes, retrieval evidence,
  approvals, rejections, safety checks, and non-secret token metadata.

The whitelist remains `purge_level`, `purge_similarity`, `hom_cov`, and `disable_post_join`.
Integer, float, and boolean values use strict types so `true` cannot become an integer.

## Modes and failures

| Mode | Provider call | Candidate source |
|---|---:|---|
| `rules_only` | never | deterministic rules |
| `hybrid` | only after RETRY and authorized retrieval | rules plus safe LLM proposals |
| `llm_disabled` | never | deterministic rules |

In hybrid mode, provider timeout, 429, 5xx, malformed JSON, or schema failure falls back to
deterministic candidates unless `require_llm=true`. With `require_llm=true`, the result is
`STOP_LLM_REQUIRED` and no candidate is approved.

## Safety arbitration

Every LLM parameter must:

- be relevant to the deterministic RETRY parameter scope;
- cite a retrieved source that authorizes that exact parameter;
- cite only available QC, assembly, or rule metric IDs;
- stay within the schema range and strict scalar type;
- keep confidence at or below deterministic, source-version, and QC-confidence caps;
- pass the `hom_cov` independent high-confidence k-mer authorization;
- contain no shell flag, command, path, environment-variable, or secret-bearing text;
- differ from every seen parameter fingerprint;
- fit the candidate, compute, and risk-confirmation budgets.

Quarantined RAG chunks are removed before prompt construction. The prompt contains only sanitized QC
facts and post-QC metrics; absolute source paths and tool metadata paths are excluded.

## Artifacts

`hifi-agent propose RUN_DIR` writes:

```text
04_decisions/baseline/proposals/
├── context/
│   ├── qc_feature_bundle.json
│   └── qc_llm_summary.json
├── proposal_decision.json
├── retrieval_trace.json
└── proposal_trace.jsonl
```

An alternate `--output-dir` keeps retained real-data runs read-only during acceptance.
