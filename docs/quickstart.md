# 快速开始

## 1. 安装环境

```bash
git clone https://github.com/mysilicons/HiFiAgent.git
cd HiFiAgent
conda env create -f environment.yml
conda activate hifiAgent
python -m pip install .
```

## 2. 准备数据

输入应放在全局配置 `paths.data_root` 下：

```text
Data/
└── New_species/
    ├── reads.part1.fastq.gz
    └── reads.part2.fastq.gz
```

## 3. 配置运行环境

通常只需修改一次 `configs/runtime.yaml`：

```yaml
schema_id: hifi-agent-runtime
paths:
  data_root: ../Data
  output_root: ../results
  cache_root: ../cache/hifi-agent
resources:
  max_threads: 128
  max_memory_gb: 960
runtime:
  resume_mode: auto
  retention: standard
```

资源、优化、预算、工具和 QC 的完整字段见仓库中的实际配置文件。

## 4. 新建物种配置

创建 `configs/samples/New_species.yaml`：

```yaml
schema_id: hifi-agent-sample
runtime_config: ../runtime.yaml
sample_id: New_species
read_technology: pacbio_hifi
hifi_reads:
  - New_species/reads.part1.fastq.gz
  - New_species/reads.part2.fastq.gz
species_name: New species
expected_genome_size: 500000000
ploidy: 2
inbred: null
busco_lineage: eukaryota_odb12
kmer_reads: null
reference_genome: null
```

`hifi_reads`、`kmer_reads` 和 `reference_genome` 只能使用 `data_root` 下的相对路径。未知的科学字段可
设为 `null`；不要猜测倍性、基因组大小或近交状态。

## 5. 预检与运行

```bash
hifi-agent plan configs/samples/New_species.yaml
hifi-agent assemble configs/samples/New_species.yaml
```

默认启用自动恢复。中断后原样执行第二条命令，不要复制其他 attempt 的 Nextflow cache。

## 6. 验收结果

```bash
hifi-agent verify-run results/New_species --deep
```

只有 verification 未出现 `FAIL` 时才继续解释科学指标。详见[结果解释](result-interpretation.md)。

## 可移植演示

开发者可在不使用真实数据和付费 API 的情况下验证完整 wiring：

```bash
python scripts/run_portable_demo.py \
  --workspace /tmp/hifi-agent-portable \
  --scenario three-rounds
```

fixture 结果只证明进程、文件、恢复、合同和报告边界有效，不能作为生物学结论。
