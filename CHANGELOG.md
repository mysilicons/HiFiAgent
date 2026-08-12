# Changelog

All notable changes are documented here. This project follows Semantic Versioning.

## [3.0.0] - 2026-08-13

### Added

- Portable fixture toolchain that exercises the real CLI, subprocess boundary, workflow runner,
  parsers, parameter contracts, reports, and deep verifier without biological data.
- Checksummed, round-bound recorded LLM transcript replay for offline hybrid acceptance.
- Stable CLI exit and report contracts for scientific stops, human review, tool failures,
  required-provider failures, and interrupted-run recovery.
- Package-owned workflow, comparison policy, and governed knowledge resources so wheels run
  independently from a source checkout.
- Strictly separated shared runtime and single-sample configuration with one-command execution.
- Lock-protected BUSCO lineage caching, immutable source snapshots, automatic resume, and
  post-verification retention.
- Real-data registry, strict run verification, live-provider smoke test, and hash-bound evidence
  bundle interfaces that keep external data outside Git.

### Changed

- Consolidated production lifecycle ownership into one authoritative coordinator and one run
  state, with separate round, terminal, and typed artifact services.
- Governed retrieval preserves source diversity and checks tool-version evidence before parameter
  authorization.
- Baseline and candidate attempts share the same executor and post-QC protocol.
- Nextflow SIGINT and SIGTERM results are classified as resumable interruptions.
- Release distributions are checked through isolated-wheel portable execution.

### Removed

- Deprecated compatibility commands, migration readers, execution adapters, and aliases.
- Repository-bound real input paths and ungoverned development artifacts.

## [2.0.0] - 2026-07-29

### Added

- Immutable run, attempt, and round schemas with a single orchestration controller.
- Typed QC features, evidence-governed retrieval, strict structured proposal parsing, and a
  deterministic Safety Arbiter.
- Candidate argv round-trip contracts, unique attempt directories, and execution receipts.
- Multi-metric comparison policy with hard regressions, plateau, conflict, budget, and bounded
  round outcomes.
- JSON, Markdown, and TSV reports tracing approved parameters to actual argv and artifacts.
- Privacy and cost disclosure, repeatable three-round demonstration, and clean-build verification.

### Changed

- Structured providers may propose whitelist candidates, but only the deterministic Safety Arbiter
  can issue an approved full configuration.
- Default optimization is one candidate per round and at most three rounds.
- The comparison policy is packaged into the wheel instead of read from the source tree.

### Known limitations

- Same-read Merqury evidence is advisory; independent reads are preferred.
- External-provider prices are not frozen; receipts retain token counts, model, endpoint class, and
  response hash without retaining credentials.

## [1.0.0] - 2026-07-14

### Added

- Validated single-sample PacBio HiFi configuration and provenance receipts.
- Nextflow DSL2 pre-QC, hifiasm baseline, post-QC, and resume workflow.
- Bounded expert rules, explicit stop states, and a constrained explanation layer.
- One-round candidate comparison with multi-metric hard gates.
- Markdown, JSON, and TSV reporting with sensitive-path redaction.
- Portable demonstration, user and developer guides, rule catalog, and citation metadata.

### Known limitations

- Scope is HiFi-only single-sample assembly; Hi-C, trio, ONT, scaffolding, annotation, and
  unbounded parameter search are unsupported.
- Same-read k-mer evaluation is advisory rather than independent validation.
- Retrieval and model explanations never authorize parameters or shell execution.
