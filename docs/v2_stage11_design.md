# V2 Stage 11 design: benchmark and ablation

`run_v2_benchmark` combines production comparator scenarios, genuine input audits, observed
Candida execution costs, and the four required ablation groups.

## Safety scenarios

Five deterministic metric fixtures exercise the production `RoundComparator`:

1. safe material improvement;
2. N50 gain with protected BUSCO/k-mer regression;
3. material plateau;
4. missing required metric;
5. unresolved non-dominated tradeoff.

They are controller/scientific-policy tests, not biological assemblies. Existing repository gates
add schema, command contract, arbiter, stopping, prompt-injection, state-transition, three-round,
Nextflow compile, and resume coverage.

## Genuine datasets

The versioned sample manifest contains:

- Candida albicans `SRR23724250`, the complete baseline/candidate/closed-loop case;
- Drosophila melanogaster `SRR33554835`, a materially larger independent HiFi input.

Real acceptance reads and SHA-256 hashes both complete FASTQ files and checks the accession-bearing
FASTQ header, byte count, retained read count, and total bases. Drosophila is an input/scale
acceptance sample; no Drosophila assembly or heterozygosity estimate is claimed.

## Cost and A–D ablation

CPU hours are calculated from every completed Nextflow process's `realtime × %cpu`. Walltime comes
from immutable attempt receipts. Disk cost is the sum of retained artifact inventories. Failed
attempts remain costs and are not erased from the totals. LLM cost records call and token counts;
monetary price is intentionally not frozen because provider prices can change.

Groups A–D share one metric schema covering candidate legality, safety rejection, material
improvement, hard regression, plateau accuracy, duplicate candidates, assembly count, CPU,
walltime, disk, LLM calls/fallback, and human-review agreement. In the genuine run DeepSeek
returned zero proposals, so groups B–D have the same biological execution and terminal outcome;
group D adds one governed LLM call, not a claimed quality gain.

Human-review agreement is measured against predeclared acceptance labels in the reviewed scenario
registry. It is not presented as a blinded external-review study.
