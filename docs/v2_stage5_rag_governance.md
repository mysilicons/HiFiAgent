# V2 Stage 5 RAG governance contract

Stage 5 defines the only knowledge evidence later parameter-proposal stages may consume. It does
not authorize an LLM to invent candidates and does not implement the Stage 6 proposer.

## Catalog and source integrity

`configs/knowledge_sources.yaml` uses schema `2.0`. Every source declares:

- evidence level and authorization scope;
- local file path, expected SHA-256, canonical URL, version URL, and tool version;
- review deadline for stale-source checks;
- parameter, problem, and input-condition tags.

Index construction fails closed when a local checksum differs. HTTPS/local URL schemes are
validated, and a hifiasm version URL must identify the declared release version. A source beyond
its review deadline is retained for audit with `STALE_SOURCE` warning, but its chunks lose
parameter authorization.

Only official sources with `parameter_guidance` scope may declare parameter tags. The catalog and
the built index both require coverage for `purge_level`, `purge_similarity`, `hom_cov`, and
`disable_post_join` (the internal name for the hifiasm post-join switch).

## Index and retrieval boundaries

The V2 index embeds the catalog SHA-256, target hifiasm version, verified source receipts, source
IDs, tags, authorization tags, quarantine state, and warnings. `index_manifest.json` summarizes
source hashes and the official evidence set for each parameter.

The default index loader cross-checks its catalog checksum and exact source-ID set against the
current V2 catalog. The index schema independently rejects any chunk whose source ID is not in its
embedded source list.

Retrieval uses deterministic BM25 plus governed tag boosts. Evidence matching the actual hifiasm
version receives an exact-version boost; mismatched hifiasm evidence is multiplied by 0.5 and
emits `HIFIASM_VERSION_MISMATCH`. The explanation path first reads the executed assembly manifest
version. If unavailable, it records that the index target version was used as fallback.

`authorized_parameters(hits)` exposes only parameter tags supported by non-stale, official,
parameter-guidance chunks. If a requested parameter lacks such evidence, the pipeline produces
`INSUFFICIENT_EVIDENCE` and does not call the LLM.

## Prompt-injection handling and traces

Indexer security patterns detect instruction override, role override, and command-execution text.
Matching chunks are retained in the index for audit with security warnings but marked quarantined;
the retriever excludes them before scoring, prompting, or any later execution boundary.

Each explanation writes `retrieval_trace.json` with the query, requested tags, actual hifiasm
version, complete catalog source-ID allowlist, returned source/chunk IDs, and version/staleness
warnings. Returned IDs are therefore auditable as a subset of catalog IDs.
