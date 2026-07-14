# V1.0.0 release checklist

## Local release candidate

- [x] Version is `1.0.0` in package metadata and CLI.
- [x] Changelog, MIT license, citation file, limitations, and release notes exist.
- [x] Ruff, formatting, mypy, and unit/integration tests pass.
- [x] Safety-critical coverage is at least 80% (measured: 82.06%).
- [x] Ten automated benchmark scenarios pass; nonexistent parameter rate is 0%.
- [x] Public Candida accessions and retained real-data outcome are documented.
- [x] Rules-only vs rules+RAG comparison and ablations are public.
- [x] Portable demo and 3–5 minute animated demo asset exist.
- [x] Repository contains no FASTQ/BAM/CRAM, meryl database, BUSCO database, or API key.
- [x] README quickstart, user/developer guides, architecture, rule catalog, and interview Q&A exist.

## External publication

- [x] Set the canonical repository URL in `CITATION.cff`.
- [x] Review and commit the current working tree.
- [x] Push the reviewed commit to `https://github.com/mysilicons/HiFiAgent.git`.
- [x] Create and push annotated tag `v1.0.0`.
- [ ] Create the GitHub Release page using `docs/releases/v1.0.0.md` (API timed out).
- [x] Verify the clean-clone README demo on Linux (9/9 scenarios passed).

The source branch and release tag are published. The remaining checkbox is limited to GitHub's
Release-page API/UI metadata; direct API connections timed out twice on 2026-07-14 while Git smart
HTTPS push and clean clone succeeded.
