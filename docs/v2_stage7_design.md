# V2 Stage 7 candidate execution design

Stage 7 is the only boundary that may turn a Stage 6 proposal into a biological assembly.
Its public executor accepts an `ApprovedCandidate`; arbitrary `AssemblyConfig`, shell text, and
unapproved parameters are not CLI inputs.

## Attempt layout

Each logical candidate has immutable attempts:

```text
02_assembly/round_NN/candidate_NN/attempt_NNN/
  attempt_identity.json
  approved_candidate.json
  preflight.json
  cache_compatibility.json
  stage7_execution.json
  workflow/
    00_metadata/
    02_assembly/<run_id>/
    03_post_qc/<run_id>/
    logs/
    .nextflow_work/
```

An interrupted RUNNING attempt may use `--resume`. A FAILED attempt is immutable; `--retry`
allocates the next attempt and a separate Nextflow work directory. Scientific and audit artifacts
from the failed attempt remain checksum-verifiable.

## Preflight and cache compatibility

Before Nextflow starts, the executor:

1. validates the resolved sample config and validation receipt;
2. re-hashes every recorded biological input;
3. enforces validated thread limits and explicit high-risk confirmation;
4. checks that only graph/output-stage whitelist parameters changed;
5. compares the runtime hifiasm version exactly with the baseline manifest;
6. hashes every baseline corrected-read/overlap `.bin`.

Any mismatch becomes a retained FAILED attempt with a reason. In particular, a hifiasm version
mismatch is rejected before a bin is passed to Nextflow.

## Parameter lineage

`ApprovedCandidate` itself guarantees requested equals approved and verifies the parameter
fingerprint. Stage 7 then records and compares:

```text
requested delta = approved delta
expanded execution parameters = rendered parameters = realized command parameters
```

The final `parameter_lineage.json` and `parameter_contract_check.json` must both be `PASS`.
The realized hifiasm command rejects unknown or duplicate flags, checks threads, input names, and
run-specific output prefix.

## Homologous post-QC

Candidate QUAST, BUSCO, Merqury, and mapping are invoked by the same Nextflow processes and with
the same configuration fields as baseline. After completion, Stage 7 requires:

- exact baseline/candidate hifiasm version equality;
- exact post-QC tool-version map equality;
- the same BUSCO lineage selection, mapping filters, and Merqury k-mer source;
- assembly and metrics run IDs bound to the attempt.

Tool failures are stored as `POST_QC_TOOL_FAILURE`; Stage 7 always records
`NOT_EVALUATED_IN_STAGE7` for biological-quality interpretation. Biological comparison belongs to
Stage 8.

## Retention

The successful inventory contains SHA-256, byte count, and relative path for every published GFA,
FASTA, bin, log, tool-version, resource report, and post-QC output. Failure inventory creation is
best-effort and happens before the attempt is frozen as FAILED.

