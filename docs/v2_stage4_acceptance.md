# V2 Stage 4 acceptance report

Date: 2026-07-15. Result: **PASS**.

## Acceptance matrix

| Requirement | Evidence | Result |
|---|---|---|
| Implement `QcFeatureBundle` | strict Pydantic models and round-trip tests | PASS |
| value/unit/source/confidence/limitations per metric | evidence completeness test | PASS |
| Stable output for identical input | two-build byte comparison | PASS |
| Expected/estimated genome-size rule | priority, conflict, unknown, failed-model tests | PASS |
| Independent versus same-data k-mer | source confidence and rule-boundary tests | PASS |
| Low peak, multiple peaks, model failure | parametrized negative authorization tests | PASS |
| User metadata provenance | ploidy/inbred/reference source assertions | PASS |
| Missing values remain `None` | schema invariant and unknown-size tests | PASS |
| LLM summary is sanitized | sensitive read/reference/server paths absent | PASS |
| Extreme coverage and low-quality reads | boundary warning tests | PASS |
| All numeric values carry units | every evidence item has a non-empty unit | PASS |
| BUSCO percentage is not scaled | 0.8 percent serialization regression | PASS |
| Unknown size does not require assembly-size ratio | core-metric rule-context test | PASS |
| Low-confidence peak cannot authorize `hom_cov` | feature and expert-rule integration tests | PASS |
| Complete baseline is not rerun for missing bundle | controller materialization test | PASS |

## Retained Candida read-only audit

The existing run was read and both generated outputs were redirected to `/tmp`. Observed result:

```text
sample_id: Candida_albicans
selected_genome_size: 6502719 bp
estimated_coverage: 742.7163055946289 x (low confidence; extreme-high warning)
k-mer peak confidence: low
hom_cov authorized: false
warnings: KMER_LOW_COVERAGE_PEAK, KMER_MULTIPLE_COMPARABLE_PEAKS,
          COVERAGE_EXTREME_HIGH
LLM summary contains /data/gw: false
```

No Stage 4 file was written under `Data/Candida_albicans/hifiAgent`.

## Quality gates

```text
Stage 4/rule/controller focused tests: 94 passed
Final full pytest: 259 passed, 13 skipped
Ruff check: PASS
Ruff format --check: PASS (92 files)
mypy strict: PASS (92 source files)
Coverage: 83.21% (required 80%)
```

The skipped tests are explicit retained-data/live-API gates. Stage 4 performs no LLM call and no
new biological assembly; it creates the evidence contract that later RAG/LLM stages will consume.
