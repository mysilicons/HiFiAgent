# HiFi Agent V2 user guide

## Install and check

The full biological workflow requires Linux. The committed environment locks Python 3.12,
OpenJDK 21, Nextflow 25.04.7, hifiasm 0.25.0, and the QC tools:

```bash
conda env create -f environment.yml
conda activate hifiAgent
python -m pip install -e .
hifi-agent --version
nextflow -version
java -version
hifi-agent demo-v2 /tmp/hifi-agent-v2-demo
```

Expected package version is `2.0.0`; the demo must report `Scenarios passed: 5/5`. The demo uses no
biological data. A wheel installation also carries its own comparison policy, so it does not
depend on a source-tree `configs/` path.

## Configure and run

Copy `examples/candida_sample_config.yaml`, replace input/output paths, and set resource budgets.
V2 defaults to at most three rounds and one candidate per round. Validate before spending compute:

```bash
hifi-agent validate sample.yaml
hifi-agent assemble sample.yaml
```

The public V2 stages can also be invoked separately:

```bash
hifi-agent propose RUN_DIR
hifi-agent execute-candidate RUN_DIR APPROVED_CANDIDATE_JSON --execution-root HISTORY
hifi-agent compare-stage7 RUN_DIR ATTEMPT_DIR --output-dir OUT
hifi-agent report-v2 RUN_DIR --stage7-root HISTORY --comparison COMPARISON_JSON \
  --loop-state LOOP_STATE_JSON --proposal PROPOSAL_JSON --output-dir REPORT_DIR
```

Use each command's `--help` for required paths. `execute-candidate` accepts an
`ApprovedCandidate`, not an LLM proposal. Never hand-edit a proposal into an approval receipt.

## Optional governed DeepSeek

Build the local allowlisted index, then opt in:

```bash
hifi-agent rag-index
export DEEPSEEK_API_KEY='set-in-your-shell-not-in-a-file'
export DEEPSEEK_BASE_URL='https://api.deepseek.com'
export DEEPSEEK_MODEL='deepseek-v4-pro'
hifi-agent propose RUN_DIR --decision-mode hybrid
```

Use `--no-llm` for local deterministic proposals. DeepSeek may propose a typed whitelist candidate;
only the deterministic Safety Arbiter may approve it. API failure, malformed output, injected
parameters, missing evidence, or duplicates fall back safely. See
[LLM data privacy and cost](v2_llm_privacy_cost.md).

## Interpret outcomes

- `INCUMBENT_UPDATED`: one uniquely safe and materially better candidate became incumbent.
- `STOP_PLATEAU`: no material safe improvement; retaining the incumbent is correct.
- `STOP_CONFLICT`: nondominated candidates require human review.
- `STOP_INSUFFICIENT_METRICS`: protected evidence is missing.
- `STOP_BUDGET`: predicted or consumed resource budget blocks more work.
- `STOP_MAX_ROUNDS`: three completed rounds reached the hard limit.
- `FAILED_TOOL_EXECUTION`: engineering failure, kept separate from biological conclusions.

N50 is never sufficient by itself. Completeness, k-mer support, mapping, coverage variability, and
reference-supported structural errors are protected according to applicability and evidence
quality. Same-read Merqury is advisory.

## Audit the report

The V2 report includes baseline, every failed/completed attempt, proposal and approval origin,
parameter diffs, actual argv, parameter contract status, metrics, artifact/checksum provenance,
budgets, LLM token evidence, limitations, and terminal outcome. Verify:

```bash
rg 'parameter_contract_status|actual_argv|terminal_outcome' REPORT_DIR/v2_final_report.json
```

Large reads and result directories must not be committed. For V1 results, follow
[V1 → V2 migration](v2_migration.md); never share an `outdir` between versions.
