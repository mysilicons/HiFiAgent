# Architecture

HiFi Agent separates execution, scientific evidence, decisions, explanations, and reports.

```mermaid
flowchart LR
  U[Sample YAML + HiFi FASTQ] --> V[Schema and input validator]
  V --> N[Nextflow DSL2]
  N --> P[Pre-QC: seqkit / NanoPlot / meryl]
  N --> A[hifiasm baseline]
  A --> Q[Post-QC: QUAST / BUSCO / Merqury / mapping]
  P --> M[Normalized JSON metrics]
  Q --> M
  M --> R[Versioned expert rules]
  R -->|BASELINE / STOP / <=2 candidates| C[Budgeted Agent controller]
  C --> O[Bounded candidate comparator]
  R --> G[Local RAG + optional DeepSeek explanation]
  G -. cannot change decision .-> C
  O --> F[Markdown / JSON / TSV report and provenance]
  C --> F
```

The trust boundary is deliberate: Nextflow executes fixed commands; parsers normalize outputs;
rules alone authorize actions; the controller enforces state and compute budgets; the LLM only
explains an already legal outcome. The four V1 hifiasm knobs are `purge_level`,
`purge_similarity`, `hom_cov`, and `disable_post_join`.

Data flows through immutable artifacts under `00_metadata` to `05_report`. Engineering failures
enter `FAILED_TOOL_EXECUTION`; evidence conflicts or missing metrics stop automation instead of
being silently converted to biological conclusions.
