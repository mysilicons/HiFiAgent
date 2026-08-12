# Configuration and Decision Modes

**English** | [简体中文](zh-CN/decision-modes.md)

Scientific control remains deterministic in every mode. Rules decide whether evidence justifies a
search; an optional provider may propose a structured candidate; only the Safety Arbiter can approve
a full executable configuration.

## Configuration ownership

`optimization.decision_mode`, `require_llm`, provider-call budgets, risk confirmation, and round
limits belong in the shared runtime configuration. Sample scientific facts remain in the sample
file. Provider credentials belong only in the process environment or a secret manager.

## Three decision modes

| Mode | Provider use | Behavior |
|---|---|---|
| `rules_only` | none | Deterministic rules and governed evidence generate or reject candidates |
| `llm_disabled` | none | Explicitly disables provider proposals while retaining deterministic control |
| `hybrid` | optional or required | Rules build a bounded context; a provider proposes JSON; safety policy authorizes or rejects it |

`rules_only` is the recommended default for reproducible or offline operation. `llm_disabled` is an
explicit operational declaration and never means “execute arbitrary defaults.” Hybrid mode does not
give the provider shell access, filesystem access, arbitrary retrieval, or authority over budgets.

## Hybrid configuration

```yaml
optimization:
  decision_mode: hybrid
  require_llm: false
execution_budget:
  max_llm_calls_per_round: 1
  max_total_llm_calls: 3
```

For online use:

```bash
export DEEPSEEK_API_KEY='set-in-your-secret-manager'
hifi-agent assemble configs/sample.yaml
```

With `require_llm: false`, transport, timeout, schema, or provider errors deterministically fall back
to safe local behavior and are recorded. With `true`, an unavailable or invalid required response
ends as `FAILED_REQUIRED_LLM` with exit code 5; it never silently degrades.

## Privacy boundary

The provider may receive only the current round, redacted aggregate QC, governed knowledge snippets,
the parameter allowlist, budgets, constraints, and existing candidate fingerprints. It must not
receive reads, sequences, assemblies, absolute paths, credentials, unredacted logs, or unrelated run
artifacts. Receipts retain model/endpoint class, token counts, status, and hashes—not the API key.

## Safety Arbiter

Every proposal must satisfy strict schema, parameter allowlist, evidence authorization, metric
direction, one-variable change, risk, budget, round binding, non-duplication, and argv-contract
checks. Rejection is fail-closed and persisted with reason codes. Provider prose is never executed.

## Risk confirmation

`confirm_risk_level` defines when an otherwise legal change requires explicit human confirmation.
The coordinator stops before spending assembly budget and preserves the proposal, evidence, and
reason. Confirmation cannot legalize an unknown parameter or bypass a hard safety rule.

## Offline transcript replay

Acceptance tests may replay a checksummed structured transcript bound to the exact decision context
and round. Replay exercises parsing, safety arbitration, execution, comparison, and reporting without
network variability. It is test evidence, not a substitute for production authorization.

## Choosing a mode

- Choose `rules_only` for maximum determinism, privacy, and offline use.
- Choose `llm_disabled` when policy must explicitly prohibit provider involvement.
- Choose `hybrid` only when credentials, privacy approval, budgets, fallback semantics, and provider
  governance are understood and recorded.
