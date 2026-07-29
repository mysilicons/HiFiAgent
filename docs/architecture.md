# V2 architecture

```mermaid
flowchart LR
  I[Sample YAML + HiFi FASTQ] --> V[Validation + immutable receipt]
  V --> C[Single AssemblyController]
  C --> B[Baseline workflow]
  B --> Q[Typed QC features]
  Q --> R[Versioned expert rules]
  Q --> G[Governed RAG]
  R --> P[Typed proposals]
  G --> L[Optional DeepSeek proposal]
  L -. untrusted proposal .-> P
  P --> S[Deterministic Safety Arbiter]
  S -->|ApprovedCandidate only| E[CandidateExecutor]
  E --> A[Actual argv + contract + artifacts]
  A --> M[Protected multi-metric comparator]
  M -->|update / stop| C
  C -->|max 3 rounds| M
  M --> F[V2 JSON / Markdown / TSV report]
```

The trust boundary is deliberate. Nextflow executes fixed processes; parsers normalize evidence;
rules and the Safety Arbiter authorize candidates; the controller enforces state, round, and
resource budgets. DeepSeek can propose only typed whitelist changes. It cannot create an approval,
execute a process, change the incumbent, or override a stop.

Each round records immutable proposal, approval/rejection, attempt, actual argv, parsed parameter
contract, metrics, policy version, comparison, budget, and event lineage. Historical folders are
never overwritten. A unique safe material improvement may update the incumbent; hard regression,
plateau, conflict, insufficient evidence, budget, or the third-round limit stops automation.

Reports consume those artifacts rather than reconstructing intent. Therefore a reviewer can trace:

```text
proposal → arbiter decision → approved parameters → execution manifest/argv
        → parsed parameters → QC artifacts/metrics → comparison → terminal outcome
```

Biological files remain outside Git. Only small schemas, fixtures, policies, audit summaries,
checksums, and redacted reports are release assets.
