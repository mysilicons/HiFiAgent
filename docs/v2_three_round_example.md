# V2 three-round optimization example

This example demonstrates the maximum-round state machine with deterministic fixtures. It is not a
biological result. The genuine Candida run stopped safely after round 1 at `STOP_PLATEAU`, so
inventing three real rounds would be misleading.

## Fixture sequence

| Step | Immutable ID | Approved change | Comparison outcome | Next state |
|---|---|---|---|---|
| baseline | `baseline` | default hifiasm parameters | incumbent created | round 1 |
| round 1 | `candidate_r01_c01` | one whitelist variable | `INCUMBENT_UPDATED` | round 2 |
| round 2 | `candidate_r02_c01` | one different whitelist variable | `INCUMBENT_UPDATED` | round 3 |
| round 3 | `candidate_r03_c01` | one different whitelist variable | material improvement observed | `STOP_MAX_ROUNDS` |

Each transition writes the round index, incumbent ID, proposal/approval evidence, budget before and
after, actual argv, metrics paths, comparison policy version, and stop reason. A fourth round is
rejected before execution.

Run the exact regression proof:

```bash
pytest -q tests/test_stage9_optimization_loop.py -k three
```

The proof uses the production `OptimizationLoop`, `RoundComparator`, typed models, and stop policy.
Only assembly/QC runners are deterministic fixtures.

## Genuine result kept separate

The real Candida acceptance executed one repaired single-variable candidate, verified the exact
hifiasm argv/manifest contract, evaluated genuine QC artifacts, and observed no material safe
improvement. The correct terminal result was `STOP_PLATEAU`. This is evidence that early stopping
works; it is not evidence for a three-round biological improvement.
