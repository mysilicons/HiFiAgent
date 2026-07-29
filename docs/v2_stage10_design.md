# V2 Stage 10 design: cross-stage final report

`render_v2_report` consumes the immutable evidence produced by Stages 0–9. It does not infer a
successful optimization from the existence of an assembly. The machine schema distinguishes:

- `optimization_selected_run_id`: a candidate selected by the comparator;
- `final_run_id`: the incumbent recommended after the terminal decision;
- `outcome_class`: accepted, stopped, failed, or incomplete;
- `optimization_succeeded`: always false for every `STOP_*` outcome.

For the genuine Candida plateau, no candidate was selected, while `baseline` remains the final
recommended incumbent. This distinction lets a user determine the final action from the report
without misreading a safe stop as a quality improvement.

## Evidence boundaries

Every explanatory block has one explicit class:

- `FACT`: measured input or tool output;
- `DERIVED`: comparison or normalized calculation;
- `RULE_CONCLUSION`: deterministic policy result;
- `LLM_TEXT`: untrusted proposal/explanation content, never presented as fact.

The LLM record exposes provider, model, response ID, knowledge-index SHA-256, prompt SHA-256,
proposal-output SHA-256, token counts, and proposal/rejection counts. Approved and rejected
proposals remain separate.

## Complete history and parameter truth

`all_runs.tsv` contains baseline, every immutable attempt, and every rejected proposal. Failed
attempts retain failure category, error, resource use, partial metrics, and disk inventory.
`all_parameters.tsv` aligns requested, approved, rendered, realized, and actual Nextflow argv
values. A completed candidate is marked `PASS` only when the Stage 7 contract passed.

The Markdown report has the 13 sections required by the V2 plan. Absolute paths are recursively
redacted by default, including paths embedded inside commands, errors, and nested tool metadata.
The old report collector remains available; calling the V2 renderer without immutable Stage 7
history produces an explicit `V1_COMPATIBILITY` report rather than fabricating V2 lineage.
