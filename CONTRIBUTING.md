# Contributing

Use Python 3.12 and create the environment from `environment.yml` or install `.[dev]`.
Keep scientific decisions deterministic, version thresholds and sources, and never add an
hifiasm parameter outside the audited whitelist without a design review and tests.

Before opening a change, run:

```bash
ruff check .
ruff format --check .
mypy
pytest --cov --cov-fail-under=85
python scripts/run_portable_demo.py --workspace /tmp/hifi-agent-portable --scenario three-rounds
```

Do not commit FASTQ/BAM/CRAM, assembly databases, BUSCO downloads, meryl databases, credentials,
or identifiable absolute paths. New rules require at least two positive and two negative tests.
