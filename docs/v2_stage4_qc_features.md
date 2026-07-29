# V2 Stage 4 QC feature contract

`QcFeatureBundle` is the deterministic evidence boundary between pre-QC artifacts and later
rules, RAG retrieval, and LLM proposal stages. The controller writes:

- `01_pre_qc/qc_feature_bundle.json`: complete local evidence, including relative provenance and
  SHA-256 checksums;
- `01_pre_qc/qc_llm_summary.json`: path-free values, units, confidence, limitations, warnings, and
  missing/tool-failure lists.

No timestamp is included, lists are sorted, and JSON serialization is stable. Rebuilding from the
same inputs therefore produces identical bundle bytes. Missing observations remain JSON `null` and
use `unavailable` confidence.

## Evidence rules

Every feature records a stable metric ID, value, unit, one or more run-relative sources,
confidence, and limitations. User-declared ploidy, inbred status, expected genome size, and
reference availability point to `00_metadata/resolved_config.yaml`; the summary exports only
reference availability, never the reference or read path.

Expected genome size has priority because it is an explicit run assumption. A successful
GenomeScope estimate is retained as comparison evidence; a difference greater than 25% lowers the
selected size confidence and emits `GENOME_SIZE_ESTIMATES_CONFLICT`. Without an expected size, only
a successful GenomeScope estimate can be selected. Otherwise selected size and coverage remain
`null`; assembly-size ratio is not promoted to a core-required metric.

Coverage is recomputed from total bases and the selected genome size. Values below 15x or above
200x are retained but marked low-confidence with an explicit warning. Mean read Q score below 20 is
also surfaced as a warning.

## k-mer authorization boundary

Only `independent_high_confidence` evidence with a successful model, a peak at or above the trust
threshold, and no low/multiple/unclear-peak warning sets
`kmer_peak_authorizes_hom_cov=true`. Same-HiFi-read advisory evidence is always low-confidence and
cannot authorize `hom_cov`. The expert-rule context consumes this explicit authorization bit and
defaults to false when a legacy run has no feature bundle.

GenomeScope fitted values are `null` after model failure. Reported percentages are preserved in
their declared unit; no implicit fraction-to-percent conversion occurs.

## Controller and retention behavior

The unified controller materializes the feature bundle after baseline artifacts exist and before
the baseline attempt is sealed. A missing cheap bundle does not make an otherwise complete,
expensive baseline rerun. It is included in attempt artifact checksums once generated.

The retained Candida audit writes its derived Stage 4 outputs to `/tmp`; it neither backfills nor
rewrites retained V1 artifacts.
