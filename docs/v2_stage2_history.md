# V2 immutable history and directory contract

## Native V2 audit layout

V2 keeps large workflow products in their executor-owned V1-compatible locations during the
incremental migration. It adds immutable, checksum-bound attempt directories without copying large
FASTA/GFA/bin files:

```text
02_assembly/
├── baseline/attempt_001/
└── round_01/candidate_01/attempt_001/
03_post_qc/
├── baseline/attempt_001/
└── round_01/candidate_01/attempt_001/
04_decisions/rounds/round_00/round_record.json
05_agent/v2/
├── run_identity.json
├── history_manifest.json
├── run_state.json
└── event_trace.jsonl
```

Each attempt manifest contains absolute references, SHA-256, byte size, nanosecond mtime, role, and
schema version for its real artifacts. The post-QC mirror points back to the assembly manifest and
indexes post-QC records. This avoids duplicating multi-gigabyte data while making mutation
detectable.

## Identity rules

- baseline: `baseline/attempt_001`;
- candidate run: `candidate_r<round>_c<candidate>`;
- audit path: `round_<round>/candidate_<candidate>/attempt_<attempt>`;
- a biological-parameter retry receives a new candidate/round identity in later stages;
- a tool retry preserves run ID and parameter fingerprint but creates `attempt_002`, etc.

## Immutability and resume

- run identity uses exclusive creation;
- attempt reservation uses an exclusive logical-run lock;
- manifest and completion receipt use exclusive creation;
- completion binds the manifest SHA-256;
- resume verifies config identity, state/trace continuity, completion, manifest, and all referenced
  artifacts before continuing;
- an already completed logical run is reused and does not create another attempt;
- a failed tool attempt is retained and the retry receives the next attempt number.

## V1 compatibility

`hifi-agent migrate-v1 RUN_DIR --dry-run` only inspects V1 artifacts and reports what a future
migration would create. `--execute` is deliberately rejected in Stage 2. No command silently writes
V2 metadata into a retained V1 directory.
