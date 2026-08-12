# Quick Start

**English** | [简体中文](zh-CN/quickstart.md)

This guide covers a first production run from installation through deep verification. See
[troubleshooting](troubleshooting.md) before modifying an interrupted run.

## 1. Install and verify the environment

```bash
git clone https://github.com/mysilicons/HiFiAgent.git
cd HiFiAgent
conda env create -f environment.yml
conda activate hifiAgent
python -m pip install .
hifi-agent --version
```

Confirm that Java, Nextflow, and core tools resolve from the active environment:

```bash
java -version
nextflow -version
command -v hifiasm
command -v busco
```

The Python wheel does not bundle third-party bioinformatics executables.

## 2. Prepare input data

Keep reads under the `data_root` declared by `configs/runtime.yaml`:

```text
Data/
└── sample/
    └── reads.fastq.gz
```

Perform basic checks before creating run identity:

```bash
gzip -t Data/sample/reads.fastq.gz
seqkit stats Data/sample/reads.fastq.gz
```

Do not modify or recompress an input after a run begins; identity includes byte size and SHA-256.

## 3. Configure the runtime

Copy or edit `configs/runtime.yaml`. Set `data_root`, `output_root`, and `cache_root`, then choose
resource values that leave capacity for the OS, Nextflow, filesystem cache, and concurrent QC.
Relative runtime paths are resolved from the runtime file's directory.

The conservative template uses 32 threads and 128 GB, but those are not sizing recommendations for
every dataset. Review [resource budgets](resource-budgets.md).

## 4. Configure the sample

Edit `configs/sample.yaml`:

```yaml
schema_id: hifi-agent-sample
runtime_config: runtime.yaml
sample_id: sample_001
read_technology: pacbio_hifi
hifi_reads:
  - sample/reads.fastq.gz
species_name: null
expected_genome_size: null
ploidy: null
inbred: null
busco_lineage: null
kmer_reads: null
reference_genome: null
```

Paths are relative to `data_root`, must not contain `..`, and must remain inside it after symlink
resolution. Fill facts you know and leave unknown scientific fields as `null`.

## 5. Validate inputs

```bash
hifi-agent validate configs/sample.yaml
```

Validation checks schema, safe paths, file format, gzip integrity, and full hashes. Keep the emitted
validation receipt with the project record.

## 6. Run the read-only plan

```bash
hifi-agent plan configs/sample.yaml
```

`plan` resolves the effective configuration and checks executables, versions, CPU, physical memory,
free disk, cache permissions, coverage backend, and BUSCO lineage availability. A pending lineage
download may be a warning when downloads are explicitly enabled; missing offline data is a failure.

## 7. Start or resume

```bash
hifi-agent assemble configs/sample.yaml
```

With `resume_mode: auto`, the same command resumes an interrupted run. With `explicit`, add
`--resume`. Never delete the lock, agent journal, attempt directory, or Nextflow cache to make a run
resume. Identity drift requires a new output name and a new run.

## 8. Verify and inspect results

```bash
hifi-agent verify-run results/sample_001 --deep
```

Read `06_report/verification_report.json` first, then `final_summary.json`, `all_runs.tsv`,
`all_parameters.tsv`, `provenance.tsv`, and `final_report.md`. A scientific exit code of zero means
the configured policy terminated normally; it is not a universal quality certification.

## 9. Run the portable demonstration

```bash
python scripts/run_portable_demo.py --workspace /tmp/hifi-agent-portable --scenario three-rounds
```

The fixture workflow passes through the real control and audit boundaries without biological data.
Use it to verify installation and recovery wiring, not assembly science.

## Next steps

- [Configuration reference](configuration-reference.md)
- [CLI reference](cli-reference.md)
- [Decision modes](decision-modes.md)
- [Resume and recovery](resume-and-recovery.md)
- [Result interpretation](result-interpretation.md)
