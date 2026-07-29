# ADR 0002: V2 optimization-round semantics

- Status: accepted
- Date: 2026-07-15

## Context

V1 uses `max_retry_rounds` with a schema upper bound of two, while its real optimization runner
implements one baseline-relative candidate round. The V2 requirement says to stop after no
meaningful improvement or after three iterations. Counting baseline as an iteration would make
configuration, run IDs, reports, and user expectations ambiguous.

## Decision

Baseline is round 0 and does not consume an optimization round. V2 may then start at most three
optimization rounds, numbered 1, 2, and 3. Every round compares its candidates with the incumbent
that entered that round. A uniquely eligible, materially improved candidate becomes the next
incumbent. One round with no eligible material improvement stops as a plateau; the system does not
run extra rounds merely to reach three.

Each round has a hard maximum of two candidates and a default of one. Across a complete run, the
theoretical hard maximum is one baseline plus six candidates. Tool retries are attempts, not new
optimization rounds, and must not change biological parameters.

## Consequences

- V2 schemas need `max_rounds` in the range 0–3.
- Run IDs, output paths, state, reports, and budgets must carry explicit round and attempt identity.
- The loop must persist the incumbent and global parameter fingerprints.
- A second invocation with `--resume` must continue the persisted round instead of restarting at 1.
- V1 run directories remain readable but do not acquire V2 semantics implicitly.
