# HiFi Agent

HiFi Agent 是一个面向单样本 PacBio HiFi 真核基因组组装的受控分析助手。它把输入验证、组装前质控、hifiasm 组装、组装后评价、专家规则决策、有限候选比较和最终报告组织成可重复的命令行流程。

项目的核心目标是：在可审计的边界内帮助用户判断一次 HiFi-only 组装是否足够可靠，或者是否需要停止复核、有限重试或生成解释报告。规则引擎是参数决策的权威；可选 RAG/LLM 只用于解释和证据组织，不直接生成 shell 命令或越过参数白名单。

## 功能特性

- 单样本 PacBio HiFi FASTQ / FASTQ.GZ 输入验证。
- Nextflow DSL2 本地工作流，覆盖 pre-QC、k-mer 分析、hifiasm baseline 组装和 post-QC。
- 结构化解析 seqkit、NanoPlot、GenomeScope、QUAST、BUSCO、Merqury、mapping QC 和 hifiasm 日志。
- 基于版本化 YAML 规则的 `BASELINE`、`RETRY`、`STOP` 决策。
- 受预算限制的候选组装比较，只允许安全白名单参数。
- Markdown、JSON、TSV 等可读和可机器处理的报告产物。
- 可选 RAG/LLM 解释层，用于生成带来源的决策说明。
- 无需测序数据的便携 demo，可快速验证安装和规则流程。

## 适用范围

HiFi Agent V1 支持：

- 单个样本的一组或多组 PacBio HiFi reads。
- 真核基因组 HiFi-only contig 组装。
- 二倍体样本优先的保守评价流程。
- Linux 本地执行。
- CLI 优先的可重复运行。

V1 不支持：

- Hi-C 分相组装。
- trio / parental reads 分型。
- ONT ultra-long 辅助组装。
- 染色体级 scaffolding。
- 基因组注释或重复注释。
- 无边界参数搜索。
- 由 LLM 直接执行任意命令或决定参数。

## 安装

完整生物学工作流推荐使用 Conda 环境。该环境包含 Python、Nextflow、Java 和主要生物信息学工具。
Git remote（规范远程仓库）为 `https://github.com/mysilicons/HiFiAgent.git`。

```bash
git clone https://github.com/mysilicons/HiFiAgent.git
cd HiFiAgent

conda env create -f environment.yml
conda activate hifiAgent
python -m pip install -e .

hifi-agent --version
```

完整工作流需要 Linux。若只运行便携 demo，可以只使用 Python 3.12 虚拟环境：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
hifi-agent demo /tmp/hifi-agent-demo
```

## 快速开始

运行无需测序数据的 demo：

```bash
hifi-agent demo /tmp/hifi-agent-demo
sed -n '1,160p' /tmp/hifi-agent-demo/v1_benchmark.md
```

预期报告中包含：

```text
Scenarios passed: 9/9
```

该 demo 会执行真实 schema、规则引擎、参数白名单、停止策略和报告生成逻辑，但不会伪装成真实生物学组装。

## 配置样本

复制示例配置并修改为自己的样本路径：

```bash
cp examples/candida_sample_config.yaml sample.yaml
```

配置示例：

```yaml
sample_id: My_sample
hifi_reads:
  - /absolute/path/to/reads.fastq.gz
outdir: /absolute/path/to/results/My_sample
species_name: Example species
expected_genome_size: 14500000
ploidy: 2
busco_lineage: saccharomycetes_odb12
kmer_reads: null
reference_genome: null

resources:
  max_threads: 64
  max_memory_gb: 256

agent:
  max_retry_rounds: 1
  max_candidates_per_round: 2
  max_tool_retries: 1
  max_cpu_hours: 10000
  max_walltime_hours: 168
  objective: balanced

kmer:
  k: 21
  low_coverage_peak_threshold: 10.0

mapping_qc:
  min_read_length: 1000
  min_mean_qscore: 20.0
  coverage_window_size: 10000
```

如果 HiFi reads 和参考 genome 文件放在同一个数据目录中，可以直接分别指向这两个文件。例如：

```text
Data/Candida_albicans/
├── Candida_albicans_HiFi.fastq
├── Candida_albicans_gnome.fasta
└── hifiAgent/
    └── Candida_albicans_config.yaml
```

此时配置文件位于 `hifiAgent/` 子目录，路径应写成：

```yaml
hifi_reads:
  - ../Candida_albicans_HiFi.fastq
reference_genome: ../Candida_albicans_gnome.fasta
outdir: .
```

相对路径会以配置文件所在目录为基准解析；不要再额外写一层重复的数据目录名。

常用字段说明：

| 字段 | 说明 |
| --- | --- |
| `sample_id` | 样本 ID，只允许字母、数字、下划线和短横线 |
| `hifi_reads` | HiFi FASTQ / FASTQ.GZ 输入，可以是一条路径或路径列表 |
| `outdir` | 当前样本的结果目录 |
| `expected_genome_size` | 预期基因组大小，单位 bp |
| `busco_lineage` | BUSCO lineage；缺失时可由 BUSCO 自动推断 |
| `kmer_reads` | 可选独立 k-mer reads；缺失时复用 `hifi_reads` 并标记为 advisory |
| `reference_genome` | 可选参考基因组，用于 reference-based 评价 |
| `resources` | 本次运行允许使用的线程和内存上限 |
| `agent` | 候选比较预算和目标偏好 |

## 运行流程

### 1. 验证输入

```bash
hifi-agent validate sample.yaml
```

验证会检查配置 schema、输入路径、FASTQ/GZIP 基本完整性、资源预算和 V1 禁止字段，并写入：

```text
<outdir>/00_metadata/resolved_config.yaml
<outdir>/00_metadata/input_checksums.tsv
<outdir>/00_metadata/validation_receipt.json
```

### 2. 运行 baseline 组装和质控

```bash
hifi-agent run --resume sample.yaml
```

该命令会运行验证后的 Nextflow 工作流，生成组装前 QC、k-mer 指标、hifiasm baseline 组装和组装后 QC 结果。中断后可继续使用 `--resume` 复用 Nextflow 缓存。

### 3. 单独重新执行组装后评价

如果已有 baseline 组装结果，可单独重新评价：

```bash
hifi-agent evaluate /absolute/path/to/results/My_sample
```

### 4. 运行专家规则决策

```bash
hifi-agent decide /absolute/path/to/results/My_sample
```

决策结果写入：

```text
<outdir>/04_decisions/baseline/rule_decision.json
```

### 5. 运行受控 Agent

```bash
hifi-agent agent --resume /absolute/path/to/results/My_sample
```

Agent 会读取已验证的输入、baseline 指标和规则决策，在预算范围内给出终态结果，并记录状态和决策轨迹。

### 6. 可选候选比较

默认只规划和比较受控候选，不执行真实候选工作流：

```bash
hifi-agent optimize /absolute/path/to/results/My_sample
```

如需执行真实候选工作流，必须显式授权：

```bash
hifi-agent optimize /absolute/path/to/results/My_sample --execute
```

中高风险候选需要额外确认：

```bash
hifi-agent optimize /absolute/path/to/results/My_sample \
  --execute \
  --confirm-medium-high-risk
```

### 7. 可选 RAG/LLM 解释

先构建本地知识索引：

```bash
hifi-agent rag-index
```

生成不调用 LLM 的本地解释：

```bash
hifi-agent explain /absolute/path/to/results/My_sample --no-llm
```

如需使用 DeepSeek OpenAI-compatible API，可设置环境变量后启用 `--llm`：

```bash
export DEEPSEEK_API_KEY=...
export DEEPSEEK_BASE_URL=https://api.deepseek.com
export DEEPSEEK_MODEL=deepseek-v4-pro

hifi-agent explain /absolute/path/to/results/My_sample --llm
```

解释层不会改变规则决策，不会新增候选参数，也不会生成可执行命令。

### 8. 生成最终报告

```bash
hifi-agent report /absolute/path/to/results/My_sample
```

默认输出目录：

```text
<outdir>/05_report/
```

常见产物包括：

```text
final_report.md
final_summary.json
comparison.tsv
parameter_diff.tsv
provenance.tsv
software_versions.tsv
reproducible_commands.txt
figures/
```

## CLI 命令速查

```text
hifi-agent --version                         显示版本
hifi-agent validate CONFIG                   验证样本配置和输入
hifi-agent run [--resume] CONFIG             运行完整 baseline 工作流
hifi-agent evaluate RUN_DIR                  重新执行 post-QC
hifi-agent decide RUN_DIR                    运行专家规则决策
hifi-agent agent [--resume] RUN_DIR          运行或恢复受控 Agent
hifi-agent optimize RUN_DIR                  运行有限候选规划和比较
hifi-agent rag-index                         构建本地 RAG 知识索引
hifi-agent explain RUN_DIR [--no-llm]        生成规则和 RAG 解释
hifi-agent report RUN_DIR                    生成最终报告
hifi-agent benchmark --fixtures-only         运行便携 benchmark
hifi-agent demo OUTPUT_DIR                   运行无数据 demo
```

## 输出目录

一次典型运行会在 `outdir` 下生成以下目录：

```text
00_metadata/     解析后的配置、输入校验、校验 receipt、运行 manifest
01_pre_qc/       FASTQ、seqkit、NanoPlot、k-mer 和 GenomeScope 指标
02_assembly/     hifiasm baseline 组装、FASTA/GFA/bin、命令 manifest
03_post_qc/      QUAST、BUSCO、Merqury、mapping 和聚合评价指标
04_decisions/    专家规则决策、RAG 证据和解释
05_agent/        Agent 状态、轨迹、预算和候选比较
05_report/       最终 Markdown/JSON/TSV 报告
logs/            Nextflow trace、timeline、report 和 DAG
```

大型测序数据、工作流缓存和结果目录不应提交到 Git。

## 项目框架

```text
.
├── src/hifi_agent/          Python 主包和 CLI
│   ├── agent/               受控 Agent、状态和工具接口
│   ├── benchmarking/        便携 demo 与 benchmark 场景
│   ├── executors/           Nextflow 执行封装
│   ├── optimization/        有限候选规划和比较
│   ├── parsers/             生物信息学工具输出解析器
│   ├── rag/                 本地索引、检索和解释安全层
│   ├── reporting/           报告数据收集和渲染
│   ├── rules/               专家规则加载和决策
│   └── schemas/             样本配置和指标模型
├── workflow/                Nextflow DSL2 工作流与 profile
├── rules/                   V1 专家规则 YAML
├── configs/                 默认阈值和知识库配置
├── document/                RAG 可引用的工具文档和论文
├── examples/                示例样本配置
├── docs/                    用户说明、架构说明和演示材料
├── benchmark/               benchmark 数据集登记和报告目录
├── environment.yml          Conda 环境定义
├── pyproject.toml           Python 包配置
├── CITATION.cff             引用信息
├── LICENSE                  开源许可证
└── README.md                项目说明
```

## 主要依赖

完整工作流依赖 `environment.yml` 中固定的工具版本，主要包括：

- Python 3.12
- OpenJDK 21
- Nextflow
- seqkit
- NanoPlot
- meryl
- hifiasm
- gfatools
- QUAST
- BUSCO
- Merqury
- minimap2
- samtools
- bedtools

## 结果解读

规则决策只输出三类结果：

- `BASELINE`：当前 baseline 证据足够支持保留默认组装。
- `RETRY`：允许在预算内比较少量白名单参数候选。
- `STOP`：输入、指标、工具结果或证据冲突需要人工复核。

`STOP` 不是程序失败；在覆盖不足、指标冲突或证据不完整时，停止复核是预期的保守行为。

## 文档

- [用户指南](docs/user_guide.md)
- [架构说明](docs/architecture.md)
- [规则目录](docs/rule_catalog.md)
- [演示说明](docs/demo.md)

## 引用

如果你在研究或项目中使用 HiFi Agent，请引用本软件发布。引用元数据见 [CITATION.cff](CITATION.cff)。

```text
HiFi Agent contributors. HiFi Agent: a constrained PacBio HiFi assembly assistant. Version 1.0.0. 2026.
```

## 许可证

本项目使用 MIT License，详见 [LICENSE](LICENSE)。
