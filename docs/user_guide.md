# User guide

## Install

Linux is required for the full biological workflow. Create the pinned Conda environment:

```bash
conda env create -f environment.yml
conda activate hifiAgent
python -m pip install -e .
hifi-agent --version
```

The portable decision demo only needs Python 3.12:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
hifi-agent demo /tmp/hifi-agent-demo
```

## Configure and run

Copy `examples/candida_sample_config.yaml`, replace every input/output path, and choose resource
limits your machine can actually provide. Validate before spending compute:

```bash
hifi-agent validate sample.yaml
hifi-agent run sample.yaml
hifi-agent evaluate results/MY_SAMPLE
hifi-agent decide results/MY_SAMPLE
hifi-agent agent results/MY_SAMPLE
hifi-agent report results/MY_SAMPLE
```

Use `--resume` after an interruption. Never point `outdir` inside an input directory. The input
receipt and checksums are generated before workflow execution.

## Optional RAG explanation

Put the allowlisted source documents in `document/`, build the local index, then explain:

```bash
hifi-agent rag-index
export DEEPSEEK_API_KEY='set-in-your-shell-not-in-a-file'
export DEEPSEEK_BASE_URL='https://api.deepseek.com'
export DEEPSEEK_MODEL='deepseek-v4-flash'
hifi-agent explain results/MY_SAMPLE --llm
```

Use `--no-llm` for a fully local sourced explanation. The LLM cannot add parameters, candidates,
or commands. A failed API request falls back safely and does not alter the rule decision.

## Interpret outcomes

- `BASELINE`: evidence supports retaining the default assembly.
- `RETRY`: one or two validated candidates may be proposed within the configured budget.
- `STOP`: input, evidence, tool execution, or metric conflicts require review.

A STOP can be the scientifically correct success. N50 is never used alone; completeness,
duplication, k-mer, mapping, coverage, and reference-supported structural errors are protected.

## Outputs and troubleshooting

- `00_metadata`: resolved config, checksums, environment and validation receipt.
- `01_pre_qc`: read and k-mer metrics.
- `02_assembly`: hifiasm outputs and command manifest.
- `03_post_qc`: per-tool and aggregate metrics.
- `04_decisions`: rules, RAG evidence, and immutable comparisons.
- `05_agent`: state, trace, budget, and candidate comparison.
- `05_report`: final readable and machine-readable report.

If a tool fails, read its workflow log and structured `tool_failures`; do not replace a missing
metric with zero. If no rule matches, review input assumptions and evidence rather than expanding
the search. See `docs/rule_catalog.md` and `docs/technical_baseline.md`.
