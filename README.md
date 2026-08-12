<div align="center">

# HiFi Agent

**面向单样本 PacBio HiFi 数据的受约束、可恢复、可审计基因组组装助手**

从 FASTQ 到组装、质量评估、有限参数优化和终态报告：一个样本配置，一条运行命令。

[![CI](https://github.com/mysilicons/HiFiAgent/actions/workflows/ci.yml/badge.svg)](https://github.com/mysilicons/HiFiAgent/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/mysilicons/HiFiAgent?display_name=tag&sort=semver)](https://github.com/mysilicons/HiFiAgent/releases/latest)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/github/license/mysilicons/HiFiAgent)](LICENSE)

[快速开始](#快速开始) · [配置](#两层配置) · [结果验收](#结果与验收) · [文档](#文档) · [贡献](CONTRIBUTING.md)

</div>

---

HiFi Agent 将输入校验、环境预检、pre-QC、hifiasm 组装、post-QC、受控参数搜索、
多指标比较和审计报告组织为一个确定性控制面。模型没有命令执行能力；所有候选都必须通过
固定 Schema、证据授权、安全仲裁、预算和参数合同。

> [!IMPORTANT]
> 当前支持 Linux x86_64 上的单样本 PacBio HiFi 组装。Hi-C、ONT、trio、scaffolding、
> 注释、群体分析和临床用途不在支持范围内。最终结果是“已执行候选中的最佳证据”，不代表
> 全局参数最优，也不能替代独立生物学验证。

## 为什么使用 HiFi Agent

| 能力 | 行为保证 |
|---|---|
| 单命令闭环 | `assemble` 首次创建 run，再次执行按策略安全恢复 |
| 两层严格配置 | 全局运行环境与单样本科学事实分离，未知字段直接拒绝 |
| 输入与环境门禁 | 检查 FASTQ/gzip、SHA-256、工具版本、CPU、内存、磁盘和 BUSCO 缓存 |
| 统一执行边界 | baseline 与 candidate 使用同一执行器、Nextflow entry 和 post-QC 合同 |
| 有界参数优化 | 最多三轮、每轮最多两个候选、每个候选只改变一个白名单参数 |
| 受保护指标比较 | BUSCO、k-mer、mapping 和 coverage 回退不能被 N50 提升覆盖 |
| 事务化恢复 | immutable identity、append-only 日志、单写者锁、幂等预算和 attempt cache |
| 完整可审计性 | 记录 requested → approved → argv → realized 参数和 incumbent 演进链 |
| 深度验收 | 重算哈希并验证日志、预算、参数合同、inventory、报告和 provenance |

## 工作流程

```mermaid
flowchart LR
    S[样本配置] --> V[输入验证]
    R[全局配置] --> V
    V --> E[环境预检]
    E --> Q1[Pre-QC]
    Q1 --> A[Baseline 组装]
    A --> Q2[Post-QC]
    Q2 --> D{质量评审}
    D -->|需要且合规| C[单变量候选]
    C --> A2[同源组装与 QC]
    A2 --> M[受保护多指标比较]
    M --> D
    D -->|接受或停止| T[终态报告与深度验收]
```

## 系统要求

- Linux x86_64；
- Python `3.12`；
- Java `21` 与 Nextflow `25.04.7`；
- hifiasm、gfatools、SeqKit、NanoPlot、meryl、QUAST、BUSCO、Merqury；
- minimap2、samtools、bedtools 或 mosdepth、R、GenomeScope。

仓库的 [Conda 环境](environment.yml) 固定了经验证的工具版本。真实项目的资源需求取决于基因组
大小、覆盖度、杂合度和候选数量；运行前应根据主机能力修改全局配置，`plan` 会拒绝超过主机
CPU、内存或磁盘保留线的请求。

## 安装

推荐创建完整 Conda 环境：

```bash
git clone https://github.com/mysilicons/HiFiAgent.git
cd HiFiAgent
conda env create -f environment.yml
conda activate hifiAgent
python -m pip install .
hifi-agent --version
```

也可以从 [GitHub Releases](https://github.com/mysilicons/HiFiAgent/releases/latest) 下载 wheel 后安装：

```bash
python -m pip install ./hifi_agent-*.whl
```

wheel 只包含 Python 包、生产 Nextflow 流程、比较策略和治理知识；外部生物信息学工具仍需通过
Conda 或系统环境提供。安装和工具排查见[快速开始](docs/quickstart.md)与
[故障排查](docs/troubleshooting.md)。

## 快速开始

仓库只提供一个通用样本模板。将输入放到全局 `data_root` 下：

```text
Data/
└── sample/
    └── reads.fastq.gz
```

根据主机资源修改 `configs/runtime.yaml`，再按真实样本信息修改 `configs/sample.yaml`。先验证
配置与输入：

```bash
hifi-agent validate configs/sample.yaml
```

执行只读规划和完整环境预检：

```bash
hifi-agent plan configs/sample.yaml
```

预检通过后启动或自动恢复完整流程：

```bash
hifi-agent assemble configs/sample.yaml
```

默认 `resume_mode: auto`。进程中断后重新执行同一条 `assemble` 命令；程序会先验证配置快照、
输入 checksum、run identity、事务日志和 attempt cache，存在漂移时拒绝恢复。

### 无真实数据的可移植演示

以下命令使用临时 FASTQ 和隔离 fixture 工具链，经真实 CLI、控制器、文件合同、比较器和报告边界
执行 baseline 加三轮候选：

```bash
python scripts/run_portable_demo.py --workspace /tmp/hifi-agent-portable --scenario three-rounds
```

该演示验证软件 wiring、恢复和审计边界，不产生可解释的生物学结论。

## 两层配置

### 1. 全局运行配置

`configs/runtime.yaml` 维护所有样本共享的路径、资源、优化、预算、工具和恢复策略。相对路径以该
文件所在目录为基准解析。

```yaml
schema_id: hifi-agent-runtime

paths:
  data_root: ../Data
  output_root: ../results
  cache_root: ../cache/hifi-agent

resources:
  max_threads: 32
  max_memory_gb: 128

optimization:
  enabled: true
  max_rounds: 1
  max_candidates_per_round: 1
  minimum_candidate_runs: 1
  max_parameter_changes_per_candidate: 1
  plateau_rounds: 1
  decision_mode: rules_only
  require_llm: false
  confirm_risk_level: medium_high
  retain_all_attempts: true

execution_budget:
  max_total_assemblies: 2
  max_tool_retries: 1
  max_cpu_hours: 10000
  max_walltime_hours: 168
  min_free_disk_gib: 100
  max_llm_calls_per_round: 0
  max_total_llm_calls: 0

tools:
  busco_cache: busco
  coverage_backend: bedtools
  download_missing_busco: true

kmer:
  k: 21
  low_coverage_peak_threshold: 10.0

mapping_qc:
  min_read_length: 1000
  min_mean_qscore: 20.0
  coverage_window_size: 10000

runtime:
  resume_mode: auto
  retention: standard
```

### 2. 单样本配置

`configs/sample.yaml` 只描述输入位置和科学事实。输入必须使用 `data_root` 下的安全相对路径。

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

已知科学事实应填写，未知字段保持 `null`，不要猜测倍性、基因组大小或近交状态。多个 HiFi 文件
可按列表列出；独立 k-mer reads 和参考基因组为可选输入。字段、范围、路径解析和完整范例见
[配置参考](docs/configuration-reference.md)。

## 命令行

| 命令 | 用途 |
|---|---|
| `hifi-agent validate SAMPLE.yaml` | 验证配置和输入，生成 checksum 与 validation receipt |
| `hifi-agent plan SAMPLE.yaml` | 只读解析配置并执行完整环境预检 |
| `hifi-agent assemble SAMPLE.yaml` | 创建或恢复生产组装闭环 |
| `hifi-agent verify-run RUN_DIR --deep` | 验证 identity、日志、预算、合同、inventory 和报告 |
| `hifi-agent check-dataset REGISTRY ID` | 解析并完整哈希一个外部真实数据集 |
| `hifi-agent verify-real RUN_DIR REGISTRY ID` | 对真实 run 执行严格科学与工程验收 |
| `hifi-agent live-smoke RUN_DIR OUTPUT_DIR` | 对已治理上下文执行一次外部服务烟雾测试 |
| `hifi-agent build-evidence ...` | 构建与提交、wheel、真实 run 绑定的发行证据包 |

常用操作只需要前三个命令。高级参数、环境变量和稳定退出码见 [CLI 参考](docs/cli-reference.md)。

## 输出目录

```text
results/sample_001/
├── 00_metadata/       # 配置快照、输入 checksum、identity、环境和保留策略回执
├── 01_pre_qc/         # reads 与 k-mer 预评估
├── 02_assembly/       # baseline 和所有 candidate attempt
├── 03_post_qc/        # 统一 post-QC 产物
├── 04_decisions/      # 规则、证据、proposal、安全决定和比较
├── 05_agent/          # 权威状态、事件、预算、manifest history 和单写者锁
└── 06_report/         # Markdown、JSON、TSV 与 verification report
```

`retention: standard` 只在进入终态且 deep verification 通过后删除可再生的 workflow work 目录；
assembly、QC、参数、日志和审计证据会保留。完整目录所有权见[系统架构](docs/architecture.md)。

## 结果与验收

终态后执行：

```bash
hifi-agent verify-run results/sample_001 --deep
```

只有 verification 为 `PASS` 或可解释的 `WARNING` 时，才继续解释科学指标。优先阅读：

- `06_report/final_report.md`：面向人的终态总结；
- `06_report/final_summary.json`：权威机器可读终态与 incumbent chain；
- `06_report/all_runs.tsv`：全部 attempt、资格和核心指标；
- `06_report/all_parameters.tsv`：requested、approved、rendered、realized 参数；
- `06_report/provenance.tsv`：输入、提案、attempt、比较和报告哈希来源；
- `06_report/verification_report.json`：完整性验收结果。

| 退出码 | 含义 |
|---:|---|
| `0` | 科学流程按策略接受或停止，不表示全局最优 |
| `2` | 配置或输入验证失败 |
| `3` | 需要人工动作，例如预算或风险确认 |
| `4` | 工具、参数合同、状态或完整性失败 |
| `5` | 配置为必需的外部决策服务失败 |

详细指标解释、终态和审计顺序见[结果解释](docs/result-interpretation.md)。

## 文档

### 使用与运维

- [快速开始](docs/quickstart.md)
- [配置参考](docs/configuration-reference.md)
- [CLI 参考](docs/cli-reference.md)
- [资源与预算](docs/resource-budgets.md)
- [自动续跑与故障恢复](docs/resume-and-recovery.md)
- [故障排查](docs/troubleshooting.md)
- [结果解释](docs/result-interpretation.md)

### 决策、架构与验收

- [配置与决策模式](docs/decision-modes.md)
- [专家规则标准](docs/expert_rules.md)
- [系统架构](docs/architecture.md)
- [真实数据验收](docs/real-data-acceptance.md)

## 项目结构

```text
HiFiAgent/
├── configs/           # 通用全局配置、单样本模板与比较策略
├── docs/              # 用户、运维、架构和验收文档
├── scripts/           # 可移植闭环演示
├── src/hifi_agent/    # Python 包、生产流程和治理知识
├── tests/             # 单元、集成、恢复和工作流测试
├── environment.yml    # 推荐 Conda 环境
└── pyproject.toml     # Python 包与质量门禁
```

## 参与贡献

欢迎提交 issue 和 pull request。开始开发前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)，并确保变更
通过 Ruff、MyPy、pytest、覆盖率、恢复验收和可移植闭环测试。请勿提交 FASTQ、BAM/CRAM、组装
数据库、BUSCO 下载、API key、运行结果或个人绝对路径。

## 引用

项目信息位于 [CITATION.cff](CITATION.cff)。GitHub 页面可通过 **Cite this repository** 导出引用。

## 许可证

本项目采用 [MIT License](LICENSE)。第三方生物信息学工具与数据遵循各自的许可证和使用条款。
