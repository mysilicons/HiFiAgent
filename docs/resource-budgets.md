# Resources and Budgets

**English** | [简体中文](zh-CN/resource-budgets.md)

Resource settings describe the maximum host capacity a workflow may request. Execution budgets cap
the assemblies, retries, time, disk reserve, and provider calls consumed across an entire run. Both
are checked before an expensive operation starts.

## Host resources

```yaml
resources:
  max_threads: 32
  max_memory_gb: 128
```

`max_threads` is the assembly ceiling and the total boundary from which QC process limits are
derived. `max_memory_gb` is the assembly ceiling; other processes use the lower of this value and
their own cap. Preflight compares both against logical CPUs and physical memory. Leave capacity for
the OS, Nextflow, filesystem cache, and concurrent QC. The template is a conservative generic
starting point, not a universal sizing recommendation.

## Execution budget fields

| Field | Constraint | Accounting |
|---|---:|---|
| `max_total_assemblies` | `1..7` | Baseline plus all launched candidates |
| `max_tool_retries` | `0..3` | Additional attempts after tool failures |
| `max_cpu_hours` | `>=0` | Cumulative reported CPU hours |
| `max_walltime_hours` | `>=0` | Cumulative reported wall time |
| `min_free_disk_gib` | `>=0` | Observed free-space floor before each launch |
| `max_llm_calls_per_round` | `0..1` | Provider calls in one round |
| `max_total_llm_calls` | `0..3` | Provider calls in the entire run |

The theoretical assembly maximum is:

```text
min(max_total_assemblies,
    1 + max_rounds × max_candidates_per_round)
```

Evidence, risk confirmation, duplicate fingerprints, plateaus, and stop conditions may reduce it.

## Budget ledger

`05_agent/budget_ledger.jsonl` records append-only `RESERVE`, `COMMIT`, `RELEASE`, and controlled
`ADJUST` operations. Reservation IDs are idempotent. Reusing a verified completed attempt does not
consume assembly budget again; a tool retry creates and accounts for a new attempt. Disk is a launch
gate, not a cumulative counter. Terminal `final_summary.json` records limits, reserved, committed,
and remaining amounts.

## Common profiles

For baseline only, disable optimization, set `max_rounds: 0`, `minimum_candidate_runs: 0`,
`max_total_assemblies: 1`, and provider budgets to zero. For baseline plus one controlled candidate,
use one round, one candidate, one minimum candidate run, and `max_total_assemblies: 2`. Do not require
a candidate merely to consume budget; it means the run must obtain a legal real comparison even if
the baseline appears acceptable.

## Stop and recovery semantics

Insufficient launch budget yields `STOP_BUDGET` and exit code 3. A disk reserve violation prevents a
new expensive launch. Verified completed attempts resume without duplicate charging; pending
reservations are reconciled against transaction and artifact state. Budgets are part of immutable
configuration, so increasing them requires a new output directory and run rather than editing an
existing run.
