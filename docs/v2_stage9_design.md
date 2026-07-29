# V2 Stage 9 design: bounded optimization loop

`OptimizationLoop` is a persistent state machine with four phases: `DECIDE`, `EXECUTE`, `COMPARE`,
and `TERMINAL`. It consumes a typed proposal directive and Stage 8 comparison outcome until the
current incumbent is accepted or a bounded stop condition is reached.

## Round and candidate authority

Rounds are limited to one through three and candidates to one or two per round. Each proposal sees
the current incumbent metrics, all prior projected full-parameter fingerprints, and remaining CPU
and wall-time budgets. A `RETRY` directive must contain `ApprovedCandidate` objects; `ACCEPT` and
`STOP` cannot carry candidates.

The loop merges an approved delta onto the current incumbent before launch and fingerprints the
complete projected parameter set. Seen parameter sets are removed across all rounds. The runner
must return the canonical `candidate_rNN_cNN` run ID and the exact projected parameter fingerprint,
or the loop stops as an execution failure.

Budget sufficiency is checked and the launch reservation is persisted before invoking a candidate.
Actual CPU and wall time are accounted exactly once by run/attempt identity. The comparator's
selected candidate becomes the next incumbent. A third consecutive improvement terminates as
`STOP_MAX_ROUNDS` while retaining that round-3 run as the selected incumbent.

## Persistence and resume

`optimization_loop_state.json` is atomically replaced at each transition. The state binds the
sample ID, baseline run ID, baseline parameter fingerprint, baseline metrics hash, round limit, and
candidate limit. `optimization_loop_trace.jsonl` is rebuilt from a contiguous, typed event list.

The state is saved before a candidate launch and after post-QC. Therefore:

- interruption during a candidate resumes the same round/candidate with `resume=True`;
- interruption after post-QC resumes comparison without rerunning the candidate;
- completed round 1 remains persisted when round 2 resumes;
- a terminal rerun is idempotent and performs no proposal or execution call.

Controller tests drive the real state machine through canonical round-2 and round-3 run IDs. The
genuine Candida acceptance stops at round 1 because the retained candidate is a biological
plateau; it would be incorrect to manufacture further real candidates merely to exercise those
branches.
