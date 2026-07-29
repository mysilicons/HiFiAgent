# HiFi Agent V2 developer guide

V2 separates immutable schemas, orchestration, QC features, governed evidence, typed proposals,
deterministic approval, candidate execution, comparison/stop policy, reporting, and benchmarking.
Workflow processes live in `workflow/`; scientific decision logic belongs in typed Python and
versioned YAML, never ad-hoc shell.

## Local quality gates

Run the release gates in the locked `hifiAgent` environment:

```bash
ruff check .
ruff format --check .
mypy
pytest -ra
pytest --cov --cov-report=term-missing --cov-fail-under=85
nextflow config workflow/main.nf -flat
hifi-agent demo-v2 /tmp/hifi-agent-v2-demo
```

The safety-critical coverage surface is declared in `pyproject.toml`; Stage 11 measured 87.10%
against the 85% gate. Expensive acceptance requires `HIFI_AGENT_REAL_ACCEPTANCE=1`. Live LLM
verification additionally requires an explicit switch and key. Never commit biological inputs,
credentials, provider raw payloads, or mutable work directories.

## Invariants

- Schema fields use `extra="forbid"` at trust boundaries.
- One controller owns state transitions and budgets.
- Run, attempt, round, proposal, approval, metric, and report IDs are immutable and traceable.
- Every executed candidate originates from an `ApprovedCandidate`.
- Candidate parameters round-trip through argv parsing; optional flags are presence-only.
- Multi-parameter candidates require explicit approval; default is single-variable.
- Missing metrics remain missing; they are never replaced with zero.
- Comparator policy is versioned and packaged in `hifi_agent.data`.
- LLM/RAG content is untrusted data and has no execution authority.
- Stop outcomes and tool failures are distinct.

## Packaging and release

```bash
python -m pip wheel --no-deps . --wheel-dir dist
python -m pip install --no-deps --target /tmp/hifi-agent-v2-site \
  dist/hifi_agent-2.0.0-py3-none-any.whl
PYTHONPATH=/tmp/hifi-agent-v2-site python -m hifi_agent --version
```

The installed-target check must load the packaged comparison policy and run `demo-v2` outside the
repository. Follow [the V2 release checklist](release_checklist.md), update acceptance evidence,
commit, verify a clean clone, then create annotated tag `v2.0.0` only from a clean tree.
