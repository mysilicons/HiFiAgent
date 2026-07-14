# 3–5 minute demo

The portable demo exercises the real schemas and rule engine without shipping sequencing data:

```bash
hifi-agent demo /tmp/hifi-agent-demo
sed -n '1,160p' /tmp/hifi-agent-demo/v1_benchmark.md
```

The accompanying animated asset is `docs/assets/hifi_agent_demo.gif`; one playback is 3 minutes
36 seconds. It shows install/version, normal baseline retention, low-coverage stop, bounded purge
candidate, metric-conflict stop, real Candida evidence, rules-vs-RAG safety, and final acceptance.

The real report snapshot is `docs/assets/candida_report_snapshot.png`. Its values come from
`results/Candida_albicans_phase6/05_report/final_report.md`: SRR23724250-derived reads, 22,812,604
bp assembly, N50 1,247,647 bp, BUSCO 98.2% complete, and the safe
`REVIEW_GENOME_SIZE_ESTIMATE` action. It is a rendered summary, not an untracked biological result.
