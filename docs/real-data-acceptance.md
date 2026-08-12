# Real-data Acceptance

**English** | [简体中文](zh-CN/real-data-acceptance.md)

Real-data acceptance binds external bytes, source policy, configuration, code, installed package,
run evidence, and optional provider receipts without putting biological data in Git. Run it only on
controlled storage after normal deep verification.

## Dataset registry

Maintain an external YAML registry with a stable dataset ID, authorized source paths, expected
checksums or immutable byte identity, usage/source policy, and the sample configuration used for the
run. Keep the registry and all data outside the repository. Paths may be absolute because this is an
operator-controlled acceptance interface, not the sample configuration schema.

The public CLI remains:

```bash
hifi-agent check-dataset REGISTRY.yaml DATASET_ID
hifi-agent verify-real RUN_DIR REGISTRY.yaml DATASET_ID
```

## 1. Validate external bytes

`check-dataset` resolves the selected entry, verifies required files, streams complete SHA-256 hashes,
and emits a receipt. Any mismatch is a hard failure. Do not substitute filename or metadata checks
for byte hashing.

## 2. Run and deeply verify

Execute the normal sample lifecycle and then:

```bash
hifi-agent verify-run RUN_DIR --deep
hifi-agent verify-real RUN_DIR REGISTRY.yaml DATASET_ID
```

Real verification requires the run's input manifest and immutable identity to bind to the registry,
canonical reports to agree, parameter and attempt contracts to pass, and configured scientific gates
to be applicable and satisfied. A pass applies only to that dataset, configuration, environment, and
commit.

## 3. External-provider smoke test

When authorized, set the key in the environment and send only governed, redacted aggregate context:

```bash
export DEEPSEEK_API_KEY='set-in-your-secret-manager'
hifi-agent live-smoke RUN_DIR OUTPUT_DIR
```

The receipt records endpoint class, model, status, token counts, response hash, and privacy checks.
Reads, sequence, absolute paths, and API keys must not be sent or persisted.

## 4. Enable release-only tests

Real tests skip by default. Enable them explicitly:

```bash
export HIFI_AGENT_REAL_REGISTRY=/controlled/path/datasets.yaml
export HIFI_AGENT_REAL_DATASET_ID=dataset_id
pytest -m real_acceptance tests/integration/test_real_acceptance.py
```

CI remains portable and does not assume access to private data or host paths.

## 5. Build a release evidence bundle

Use `hifi-agent build-evidence --help` for the installed command contract. The bundle verifies and
hash-binds the commit, source tree, built wheel, package version, production resources, registry,
source/resolved/effective configuration, input manifest, environment manifest, live receipt, test
report, and run evidence hash. Inspect the bundle before distributing it.

## Security and archival

- Keep reads, assemblies, and large intermediates on controlled storage.
- Publish only explicitly authorized, small, redacted evidence.
- Record truthful source and usage policy in the external registry.
- Never upload credentials, private paths, or unauthorized artifacts to issues, CI, or releases.
- Acceptance `PASS` proves the recorded gates for one dataset and commit, not universal suitability.
