# V2 Stage 3 unified controller

## CLI boundary

The primary V2 entry is:

```bash
hifi-agent assemble sample.yaml --resume
```

`run`, `agent`, and `optimize` remain available as advanced V1 step commands. The Stage 3 controller
supports baseline acceptance/stop and one rule-authorized candidate execution. Candidate comparison,
incumbent replacement, and rounds 2–3 remain intentionally deferred to Stages 8–9.

## State graph

```text
INPUT_VALIDATION
  → BASELINE_EXECUTION
  → BASELINE_EVALUATION
  → REPORT
       or
  → CANDIDATE_EXECUTION
  → REPORT
```

The baseline Nextflow entry already includes pre-QC, hifiasm, and common post-QC. Evaluation only
loads the completed metrics and never invokes post-QC again. A RETRY rule produces a typed Planner
candidate and the executing adapter calls `run_candidate_workflow` directly.

## Resume and retries

- state is atomically replaced before its event is appended and fsynced;
- a one-event state/trace crash window is repairable;
- config checksum and every completed attempt artifact are verified on resume;
- completed baseline/candidate artifacts are not executed again;
- an incomplete resumed workflow receives Nextflow `resume=True`;
- a tool failure keeps its failed attempt and retries the same parameters as `attempt_002`;
- REPORT resume returns without rendering or appending another event;
- `max_steps` exists only as an internal test hook and is not a public CLI option.

## Scientific artifact publication

All scientific `publishDir` declarations now use `params.publish_overwrite`, which defaults to
`false`. Timeline/report/trace/DAG metadata may still replace their own diagnostic files, but FASTQ
QC, assembly, post-QC, and manifest outputs do not opt into overwrite. The V2 controller's
idempotence check is the normal resume path.
