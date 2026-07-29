# V2 LLM data privacy and cost

## Authority boundary

DeepSeek is optional. It may return a typed candidate proposal, rationale, and evidence IDs. It
cannot authorize a proposal, create an `ApprovedCandidate`, invoke a workflow, produce arbitrary
shell commands, alter budgets, or override a stop result. Strict schema validation and the
deterministic Safety Arbiter are the execution boundary.

If the API is missing, times out, returns malformed JSON, cites unavailable evidence, injects an
unknown parameter, or duplicates an existing candidate, V2 records the failure and continues with
the deterministic rule path.

## Data sent

The request contains only the minimum structured decision surface:

- normalized QC feature names and scalar values;
- allowed parameter names, bounds, and current values;
- sanitized RAG excerpts with evidence identifiers;
- round/budget status needed to reject duplicates or excess work.

The request must not contain raw FASTQ/FASTA sequence, read names, local absolute paths, API keys,
environment dumps, arbitrary document instructions, or full private reports. Retrieved documents
are treated as untrusted quoted data, not prompt instructions. Logs redact credential-shaped values
and do not persist the raw API key.

## Retention and provider policy

Network use sends the structured request to the configured OpenAI-compatible provider. Provider
retention, training, region, and contractual controls are outside this repository and must be
reviewed by the deployer before enabling `--llm`. For sensitive samples, use `--no-llm` or a
locally governed compatible endpoint.

## Cost evidence

The live Stage 6 acceptance used real DeepSeek and retained:

- status `SUCCESS`;
- one API call;
- 7,970 total tokens (prompt plus completion);
- model/endpoint class, latency, and response SHA-256;
- zero executable candidates from that response.

The repository does not freeze a monetary estimate because provider pricing can change. Calculate
cost at run time from the recorded prompt/completion token counts and the provider's current
contract price. Biological compute cost is reported separately as assembly count, CPU hours,
walltime, and disk bytes.

The acceptance record is
[`benchmark/reports/v2_stage6_live_deepseek_acceptance.json`](../benchmark/reports/v2_stage6_live_deepseek_acceptance.json).
It contains no API key.
