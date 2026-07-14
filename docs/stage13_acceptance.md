# Stage 13 acceptance report

Date: 2026-07-14. Local environment: `hifiAgent`, Python 3.12.13.

## Result

**PASS** for every Stage 13 acceptance item.

| Acceptance item | Evidence | Result |
|---|---|---|
| Unit tests for schemas, parsers, formulas, rules, conflicts, paths, budgets, and state | `tests/`; 199 default tests passed | PASS |
| Required small integrations | FASTQ/Nextflow smoke, pre-QC/rules, GFA/FASTA, post-QC, closed loop, failure states | PASS |
| At least six automated boundary scenarios | 9 portable + 1 retained public-real scenario | PASS |
| Normal, low coverage, size/duplication, hom-cov, inbred, N50/conflict, tool failure | `benchmarking/scenarios.py`; all expected outcomes matched | PASS |
| Methods A/B/C/D | Default hifiasm, fixed pipeline, rules-only, rules+RAG are compared | PASS |
| Agent metrics | Legality, retries, stops, citations, consistency, candidates, compute note reported | PASS |
| No nonexistent hifiasm parameters | Measured rate 0.0% | PASS |
| No evidence means no forced tuning | `insufficient_evidence` produces safe STOP and zero candidates | PASS |
| Success and failure cases in report | BASELINE/RETRY/STOP and engineering failure are represented | PASS |
| Rules-only vs rules+LLM | Retained RAG comparison preserves decision/candidates and cites sources | PASS |
| Parser/rule/parameter-safety coverage about 80% | Safety-critical gate measured 82.06% | PASS |

Commands executed:

```text
pytest --cov --cov-report=term-missing --cov-fail-under=80 -q
# 199 passed, 12 skipped; coverage 82.06%

HIFI_AGENT_REAL_ACCEPTANCE=1 pytest tests/integration/... -q
# 10 passed, 2 live-LLM checks skipped

hifi-agent benchmark --output-dir benchmark/reports \
  --real-run-dir results/Candida_albicans_phase6
# Stage 13 benchmark: PASS; Scenarios: 10
```

The two skipped real Stage 10 checks require an explicit live API call or explicit retained-LLM
audit switch. Stage 13 does not require another paid API request; the retained successful RAG
comparison is validated by the benchmark. The full-package informational coverage was 77.93%; it
is not mislabeled as the 82.06% safety-critical acceptance measurement.

Artifacts: `benchmark/reports/v1_benchmark.{json,md}`, `v1_scenarios.tsv`, `v1_ablation.tsv`,
`safety_coverage.json`.
