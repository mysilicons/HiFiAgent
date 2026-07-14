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
- [ ] Review and commit the current working tree.
- [ ] Push the reviewed commit to a configured Git remote.
- [ ] Create annotated tag `v1.0.0` and GitHub Release using `docs/releases/v1.0.0.md`.
- [ ] Verify the clean-clone README demo on Linux.

External publication remains intentionally unchecked until the repository owner supplies and
authorizes a remote; local code must not invent or push to a destination.
