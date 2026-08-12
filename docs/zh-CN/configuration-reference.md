# 配置参考

[English](../configuration-reference.md) | **简体中文**

HiFi Agent 使用两个严格且互不重叠的 YAML Schema。未知字段会被拒绝，避免拼写错误被静默忽略。

## 路径解析规则

- 全局配置中的 `paths.*`、`tools.executable_overrides` 和 replay transcript 相对于全局配置文件；
- `tools.busco_cache` 的相对路径位于 `cache_root` 下；
- 样本配置的 `runtime_config` 相对于样本配置文件；
- `hifi_reads`、`kmer_reads` 和 `reference_genome` 必须是 `data_root` 下的安全相对路径；
- 样本输入禁止绝对路径和 `..`，符号链接解析后也不能逃逸 `data_root`；
- 输出目录为 `output_root / (output_name 或 sample_id)`，不能包含任何输入文件。

## 全局配置

### `paths`

| 字段 | 类型 | 说明 |
|---|---|---|
| `data_root` | path | 所有样本输入的唯一根目录 |
| `output_root` | path | 每个 run 输出目录的父目录 |
| `cache_root` | path | BUSCO 等共享、可再生缓存的根目录 |

### `resources`

| 字段 | 类型与范围 | 默认值 | 说明 |
|---|---|---:|---|
| `max_threads` | integer，`>=1` | `32` | workflow 和 assembly 的 CPU 上限 |
| `max_memory_gb` | integer，`>=1` | `128` | workflow 的内存上限，单位 GB |

环境预检会拒绝超过当前主机逻辑 CPU 或物理内存的请求。默认值是通用保守起点，不是容量建议。

### `optimization`

| 字段 | 允许值 | 默认值 | 说明 |
|---|---|---|---|
| `enabled` | boolean | `true` | 是否允许 baseline 后生成候选 |
| `max_rounds` | `0..3` | `3` | 最大优化轮数 |
| `max_candidates_per_round` | `1..2` | `1` | 每轮最大候选数 |
| `minimum_candidate_runs` | `0..1` | `0` | 要求首轮至少执行一个受控候选 |
| `max_parameter_changes_per_candidate` | 固定 `1` | `1` | 单候选只改一个参数 |
| `plateau_rounds` | 固定 `1` | `1` | 连续一个无改进轮次即停止 |
| `decision_mode` | `rules_only`、`llm_disabled`、`hybrid` | `rules_only` | 候选提案来源策略 |
| `require_llm` | boolean | `false` | hybrid 服务失败是否成为失败终态 |
| `llm_replay_transcript` | path/null | `null` | 逐轮绑定的离线响应记录 |
| `confirm_risk_level` | `medium_high`、`high` | `medium_high` | 哪些风险等级需要显式确认 |
| `retain_all_attempts` | 固定 `true` | `true` | 所有 attempt 均保留为审计证据 |

约束：`require_llm: true` 和 `llm_replay_transcript` 只允许用于 `hybrid`；
`minimum_candidate_runs: 1` 要求优化启用且至少允许一轮。

### `execution_budget`

| 字段 | 范围 | 默认值 | 说明 |
|---|---:|---:|---|
| `max_total_assemblies` | `1..7` | `7` | baseline 加全部候选的总上限 |
| `max_tool_retries` | `0..3` | `1` | 工具失败后的额外 attempt 数 |
| `max_cpu_hours` | `>=0` | `10000` | run 累计 CPU 小时上限 |
| `max_walltime_hours` | `>=0` | `168` | run 累计 walltime 小时上限 |
| `min_free_disk_gib` | `>=0` | `100` | 每次昂贵启动前最低空闲磁盘 |
| `max_llm_calls_per_round` | `0..1` | `1` | 单轮外部模型调用上限 |
| `max_total_llm_calls` | `0..3` | `3` | 整个 run 的外部调用上限 |

总调用上限不能小于单轮上限。更多账本语义见[资源与预算](resource-budgets.md)。

### `tools`

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `executable_overrides` | mapping | `{}` | 显式工具路径，仅用于受控环境 |
| `busco_cache` | path | `busco` | 相对于 `cache_root` 的 lineage 缓存 |
| `coverage_backend` | `auto`、`mosdepth`、`bedtools` | `auto` | coverage 实现 |
| `download_missing_busco` | boolean | `true` | 是否加锁下载缺失 lineage |

可覆盖的工具名为 `java`、`nextflow`、`hifiasm`、`gfatools`、`seqkit`、`nanoplot`、`meryl`、
`quast`、`busco`、`merqury`、`minimap2`、`samtools`、`bedtools`、`mosdepth`、`rscript` 和
`genomescope`。常规 Conda 安装不需要 overrides。

### `kmer`、`mapping_qc` 与 `runtime`

| 字段 | 范围/允许值 | 默认值 |
|---|---|---:|
| `kmer.k` | `15..31` | `21` |
| `kmer.low_coverage_peak_threshold` | `1..100` | `10.0` |
| `mapping_qc.min_read_length` | `>=0` | `1000` |
| `mapping_qc.min_mean_qscore` | `0..60` | `20.0` |
| `mapping_qc.coverage_window_size` | `>=100` | `10000` |
| `runtime.resume_mode` | `auto`、`explicit` | 双配置默认 `auto` |
| `runtime.retention` | `full`、`standard` | 双配置默认 `standard` |

`standard` 只在终态 deep verification 成功后删除可再生 work；`full` 保留所有工作目录。

## 样本配置

| 字段 | 必需 | 类型 | 说明 |
|---|---|---|---|
| `schema_id` | 是 | 固定 `hifi-agent-sample` | 配置 Schema |
| `runtime_config` | 是 | path | 全局配置路径 |
| `sample_id` | 是 | string | workflow-safe ID |
| `output_name` | 否 | string/null | 覆盖默认输出目录名 |
| `read_technology` | 是 | 固定 `pacbio_hifi` | 必须显式声明，不做推断 |
| `hifi_reads` | 是 | path/list | 一个或多个 HiFi FASTQ |
| `species_name` | 否 | string/null | 已知科学名称 |
| `expected_genome_size` | 否 | positive integer/null | 可信单倍体基因组大小，单位 bp |
| `ploidy` | 否 | positive integer/null | 已知倍性 |
| `inbred` | 否 | boolean/null | 已知近交状态 |
| `busco_lineage` | 否 | string/null | BUSCO lineage ID |
| `kmer_reads` | 否 | path/list/null | 独立 k-mer reads；空时复用 HiFi reads |
| `reference_genome` | 否 | path/null | 可选可信参考 FASTA |

未知科学字段应保持 `null`。缺失字段会降低部分指标的适用性，例如没有可信 genome size 时不会用
assembly-size ratio 决策，没有参考时 QUAST misassembly 不适用。

## 完整通用示例

全局配置：

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

样本配置：

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

## 验证策略

修改配置后先运行：

```bash
hifi-agent validate configs/sample.yaml
hifi-agent plan configs/sample.yaml
```

已经存在 run identity 时，不要原地更改配置后强行恢复。需要改变不可变配置时，应使用新的
`output_name` 创建独立 run，并保留旧 run 作为审计记录。
