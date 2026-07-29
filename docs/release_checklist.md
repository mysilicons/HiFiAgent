# V2.0.0 release checklist

## Code and scientific gates

- [x] P0 optional-flag argv bug is fixed and covered by forward/reverse contract tests.
- [x] P0 LLM authority is constrained by typed Schema, whitelist, evidence validation, and Safety
  Arbiter; only `ApprovedCandidate` reaches Stage 7.
- [x] P0 history overwrite is blocked by unique immutable attempt directories/checksums.
- [x] P1 budget, same-read evidence, genome-size trust, reference applicability, Pareto conflict,
  and resume protections have explicit tests.
- [x] Ruff, Ruff format, strict mypy, pytest, safety coverage ≥85%, and Nextflow validation pass.
- [x] Three-round production loop fixture reaches `STOP_MAX_ROUNDS`.
- [x] Five production-comparator safety scenarios pass.

## Genuine-data gates

- [x] Genuine Candida baseline and repaired single-variable `disable_post_join=true` candidate ran.
- [x] Completed Candida candidate parameter contract is `PASS`.
- [x] Report argv lineage matches the execution manifest.
- [x] Genuine Candida terminal outcome is `STOP_PLATEAU`; no improvement is claimed.
- [x] Full Candida and Drosophila FASTQ SHA-256, size, and header checks pass.
- [x] Drosophila is labeled input/scale audit only, not an assembly result.
- [x] Real DeepSeek call succeeded; token counts and hashes are retained without credentials.

## Documentation and package gates

- [x] README ten-minute V2 quickstart and data-free `demo-v2` exist.
- [x] User/developer/architecture/rule documents describe actual V2 authority.
- [x] V1→V2 non-mutating migration guide exists.
- [x] LLM data privacy, provider boundary, failure fallback, and token-based cost evidence exist.
- [x] Fixture three-round example is separated from genuine one-round Candida evidence.
- [x] Environment and install checks are documented with locked tool versions.
- [x] `CHANGELOG.md`, `CITATION.cff`, release notes, and license are present.
- [x] Comparison policy is included in the wheel and loads outside the source tree.
- [x] Real report visual contains result/contract/argv/limitations and is labeled genuine.
- [x] Repository tracks no FASTQ/BAM/CRAM/meryl data or API key.

## Release mechanics

- [x] Build `hifi_agent-2.0.0-py3-none-any.whl` from the reviewed source.
- [x] Record SHA-256 in `release/v2.0.0/SHA256SUMS`.
- [x] Install the wheel into an isolated target outside the repository.
- [x] Run `--version`, packaged policy load, `--help`, and `demo-v2` from that target.
- [x] Clone the reviewed commit into a clean temporary directory and run public read-only/help
  commands plus the quickstart.
- [x] Commit the Stage 12 acceptance record and verify the worktree is clean.
- [x] Create local annotated tag `v2.0.0`.

Pushing the commit/tag and creating a GitHub Release are external publication actions and are not
claimed by this local checklist.
