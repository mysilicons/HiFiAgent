# Developer guide

The package is split into schemas/config validation, parsers, rule engine, Agent state/controller,
RAG safety, optimization, reporting, executors, and Stage 13 benchmarking. Workflow processes are
in `workflow/main.nf`; decision logic belongs in Python/YAML, not shell fragments.

## Local quality gates

```bash
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
mypy
pytest --cov --cov-report=term-missing --cov-fail-under=80
hifi-agent benchmark --output-dir benchmark/reports \
  --real-run-dir results/Candida_albicans_phase6
```

The coverage gate intentionally names the safety-critical Stage 13 scope in `pyproject.toml`:
config/schema, parsers, expert rules, Agent controls, comparator, RAG safety, and benchmark logic.
The current measured result is 82.06%. A separate full-package measurement is 77.93% and is
reported as informational, not represented as passing the 80% safety gate.

## Add a parser or rule

Parsers must return typed values, preserve missing data as `None`, expose limitations, and have
valid/malformed/boundary fixtures. A new rule requires source-versioned thresholds, a unique ID,
explicit evidence, priority/risk, and at least two positive and two negative tests. Candidate
parameters are rejected unless accepted by `CandidateParameters` and `WHITELISTED_PARAMETERS`.

## Integration and release

Small integrations use local fixtures. Expensive retained-data tests require
`HIFI_AGENT_REAL_ACCEPTANCE=1`; live LLM verification additionally requires the API key and its
explicit test switch. Never commit the API key or large biological files. Run the checklist in
`docs/release_checklist.md`, update `CHANGELOG.md` and `CITATION.cff`, then create an annotated tag
only from a clean reviewed commit.
