# V2 stage 0 regression baseline

Captured: 2026-07-15, Asia/Shanghai.

## Repository baseline

- Branch: `main`
- Commit: `f52e4cdfbbec83256e278f8b02c35527833d7c8a`
- Conda environment: `hifiAgent`
- Python requirement: 3.12
- The worktree was already dirty before V2 stage work. Existing edits to `.gitignore`, `README.md`,
  `executors/nextflow.py`, `optimization/comparator.py`, `rules/context.py`, and
  `workflow_tools.py` were treated as user-owned and preserved.

## Pre-stage-1 test observation

Command:

```bash
conda run -n hifiAgent pytest -q
```

Observed result:

```text
197 passed, 1 failed, 13 skipped
```

The failure was `test_readme_quickstart_uses_a_real_cli_command`, because the current README did not
contain the required `Git remote` phrase. The skipped tests were gated real-data, real-LLM, or
retained-artifact acceptance tests. Stage 1 must restore the portable suite to green; stage 11 will
separately require real gates to run without relying on skips.

## Scientific baseline defect

The retained Candida candidate command contains `--hom-cov true` although its planned config has
`hom_cov=null`. This candidate is preserved but is not valid selection evidence. Its command SHA and
data remain untouched; stage 1 adds a parser-level reproduction and runtime rejection.
