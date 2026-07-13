# Candida albicans Phase 3 Smoke Run

Use the local `Candida_albicans` FASTQ as the real input through the validated
CLI workflow entrypoint.

```bash
conda run -n hifiAgent hifi-agent run examples/candida_sample_config.yaml
```

Resume a stopped or completed run with:

```bash
conda run -n hifiAgent hifi-agent run --resume examples/candida_sample_config.yaml
```

Expected outputs:

- `results/Candida_albicans_phase2/00_metadata/resolved_config.yaml`
- `results/Candida_albicans_phase2/00_metadata/input_checksums.tsv`
- `results/Candida_albicans_phase2/00_metadata/hifi_reads.list`
- `results/Candida_albicans_phase2/00_metadata/run_manifest.json`
- `results/Candida_albicans_phase2/01_pre_qc/fastq_probe/fastq_probe.tsv`
- `results/Candida_albicans_phase2/01_pre_qc/seqkit/seqkit_stats.tsv`
- `results/Candida_albicans_phase2/01_pre_qc/nanoplot/NanoStats.txt`
- `results/Candida_albicans_phase2/01_pre_qc/nanoplot/NanoPlot-report.html`
- `results/Candida_albicans_phase2/01_pre_qc/kmer/read.meryl/`
- `results/Candida_albicans_phase2/01_pre_qc/kmer/kmer_histogram.tsv`
- `results/Candida_albicans_phase2/01_pre_qc/kmer/kmer_metrics.json`
- `results/Candida_albicans_phase2/01_pre_qc/raw_metrics.json`
- `results/Candida_albicans_phase2/logs/trace.txt`
- `results/Candida_albicans_phase2/logs/timeline.html`
- `results/Candida_albicans_phase2/logs/report.html`
- `results/Candida_albicans_phase2/logs/dag.html`
