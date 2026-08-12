# 快速开始

本指南完成从安装验证、通用样本配置到终态验收的最短生产路径。所有命令均在仓库根目录执行。

## 1. 安装并确认环境

```bash
git clone https://github.com/mysilicons/HiFiAgent.git
cd HiFiAgent
conda env create -f environment.yml
conda activate hifiAgent
python -m pip install .
```

确认 Python 包和 CLI 可用：

```bash
python --version
hifi-agent --version
hifi-agent --help
```

Python 必须为 3.12。完整生产流程还需要 Java、Nextflow、hifiasm 和全部 QC 工具；不要只以
`hifi-agent --version` 成功判断环境已经可运行，`plan` 才会执行完整预检。

如果不希望激活环境，也可在后续命令前加：

```bash
conda run --no-capture-output -n hifiAgent hifi-agent --help
```

## 2. 准备输入数据

默认全局配置把数据根目录设为仓库下的 `Data/`。创建一个与通用模板匹配的目录：

```text
Data/
└── sample/
    └── reads.fastq.gz
```

支持一个或多个 `.fastq`、`.fq`、`.fastq.gz` 或 `.fq.gz` 文件。程序会验证：

- 文件存在且为普通文件；
- gzip 可以完整解压；
- 第一条记录符合 FASTQ 四行结构；
- 输入不位于输出目录内部；
- 输入路径不能是绝对路径，也不能包含 `..`；
- 每个输入都会记录字节数和完整 SHA-256。

输入较大时，首次 `validate` 的完整哈希会耗时，但这是后续恢复、审计和证据绑定的必要步骤。

## 3. 配置全局运行环境

编辑 `configs/runtime.yaml`。至少根据当前主机确认：

```yaml
resources:
  max_threads: 32
  max_memory_gb: 128

execution_budget:
  min_free_disk_gib: 100
```

`max_threads` 和 `max_memory_gb` 是整个 workflow 的上限，不应直接填写物理极限；需要为操作系统、
Nextflow 和文件缓存保留空间。`min_free_disk_gib` 会在昂贵操作启动前再次检查。

默认 `rules_only` 不调用外部模型。首次真实运行建议保留该模式，先确认工具链、资源估计、数据质量
和组装产物均正常，再决定是否启用 `hybrid`。完整字段见[配置参考](configuration-reference.md)。

## 4. 填写单样本配置

编辑 `configs/sample.yaml`：

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

配置原则：

- `sample_id` 用作默认输出目录名，只允许字母、数字、下划线和连字符；
- `hifi_reads` 相对于全局 `data_root`；
- 多个 reads 文件按列表继续添加；
- `kmer_reads` 仅在有独立 reads 时填写，否则保持 `null` 并明确接受 same-read advisory 限制；
- `reference_genome` 只在有可信参考时填写；
- `expected_genome_size`、`ploidy`、`inbred` 和 `busco_lineage` 未知时保持 `null`，不要推测。

如果要保留通用模板，可复制为另一个中性文件名，并在后续命令中使用该文件。

## 5. 验证输入

```bash
hifi-agent validate configs/sample.yaml
```

成功后会在目标输出目录的 `00_metadata/` 写入 resolved config、配置快照、输入清单、checksum TSV
和 validation receipt。失败时按错误中的字段名修正配置，不要手工修改已经生成的回执。

## 6. 执行只读规划

```bash
hifi-agent plan configs/sample.yaml
```

`plan` 不创建 run 状态，主要检查：

- 两层配置合并后的最大 assembly 数；
- CPU、内存、临时目录和输出目录可写性；
- 空闲磁盘是否高于保留线；
- 外部工具是否可发现且版本符合合同；
- coverage backend 是否可用；
- BUSCO lineage 是否已缓存或允许下载。

任何 `FAIL` 都应在启动真实组装前解决。`WARNING` 需要结合内容判断，例如允许按配置下载尚未缓存的
BUSCO lineage。

## 7. 启动或恢复

```bash
hifi-agent assemble configs/sample.yaml
```

默认 `resume_mode: auto`：

- 没有 run identity 时创建新 run；
- 已有一致 identity 时恢复原 run；
- 配置、输入、策略或治理证据漂移时拒绝恢复；
- 已完成 attempt 验证后复用，不重跑也不重复计费；
- 工具重试使用新的 `attempt_NNN`，不会覆盖失败证据。

中断后使用完全相同的命令。不要删除、复制或合并其他 attempt 的 Nextflow `work` 目录。详细语义见
[自动续跑与故障恢复](resume-and-recovery.md)。

## 8. 验收与阅读结果

流程报告终态后执行深度验证：

```bash
hifi-agent verify-run results/sample_001 --deep
```

建议按以下顺序阅读：

1. `06_report/verification_report.json`；
2. `06_report/final_summary.json`；
3. `06_report/final_report.md`；
4. `06_report/all_runs.tsv`；
5. `06_report/all_parameters.tsv`；
6. `06_report/provenance.tsv`。

verification 为 `FAIL` 时先处理完整性问题，不要解释 N50、BUSCO 或 k-mer 指标。科学终态退出码为 0
只表示流程按配置正常停止，不代表全局最优。详见[结果解释](result-interpretation.md)。

## 9. 无真实数据的功能演示

```bash
python scripts/run_portable_demo.py --workspace /tmp/hifi-agent-portable --scenario three-rounds
```

演示会在指定 workspace 内创建临时输入和 fixture 工具，验证进程、恢复、参数合同、比较和报告，不会
使用 `Data/`，也不能作为真实科学验收。

## 下一步

- 调整资源和候选预算：[资源与预算](resource-budgets.md)
- 启用或禁用外部模型：[配置与决策模式](decision-modes.md)
- 处理常见失败：[故障排查](troubleshooting.md)
- 对发行候选做真实数据验收：[真实数据验收](real-data-acceptance.md)
