# 项目范围

## 一句话总结

HiFi Agent V1 是一个针对单个 PacBio HiFi 真核样本的质量控制、hifiasm 组装、组装评估和基于证据的有限参数重试的可重复、规则约束系统。

## 目标

- 在昂贵工作开始前验证明确的样本配置。
- 对 PacBio HiFi FASTQ 或 FASTQ.GZ 文件进行组装前质量控制。
- 将工具输出规范化为稳定的 JSON 模式。
- 使用默认生物参数运行基线 hifiasm。
- 使用多个指标（而不仅仅是 N50）评估组装。
- 对任何重试使用可审核的规则和 hifiasm 参数白名单。
- 当证据不足、输入超出范围或预算耗尽时安全停止。
- 生成保留工具版本、命令模板、指标、决策、警告和限制的报告。

## 支持的输入

必需：

- `sample_id`：仅限字母、数字、下划线和连字符。
- `hifi_reads`：一个或多个明确的 FASTQ 或 FASTQ.GZ 路径。
- `outdir`：输出目录。

推荐：

- `species_name`
- `expected_genome_size`
- `ploidy`
- `inbred`
- `busco_lineage`
- `kmer_reads`
- `reference_genome`
- `max_threads`
- `max_memory_gb`

## V1 运行时假设

- 主要开发和执行环境是 Linux。
- 工作流引擎是 Nextflow DSL2。
- Python 和工作流 conda 环境名为 `hifiAgent`。
- Nextflow 执行必须支持本地配置文件运行和 `-resume`。
- 大型 FASTQ 文件、数据库下载和组装输出不提交到 Git。

## 明确的非目标

V1 不实现：

- Hi-C 分相组装。
- 三联体分型。
- ONT 超长辅助组装。
- 多倍体自动优化。
- 染色体级支架构建。
- `purge_dups` 或其他第三方自动组装后去重。
- 基因组注释。
- 重复注释。
- 自动发现或下载任意数据集。
- 多用户网络平台功能。
- 无界网格搜索或贝叶斯参数优化。
- LLM 生成的 shell 执行。
- 仅按 N50 选择组装。

## hifiasm 参数安全边界

V1 中有资格进行自动处理的唯一 hifiasm 字段是：

- `threads`
- `output_prefix`
- `purge_level`
- `purge_similarity`
- `hom_cov`
- `disable_post_join`

任何新的自动参数都需要文档审查、模式定义、范围验证、测试、规则文档、风险说明和版本兼容性检查。

## 初始问题标签

本地标签的真实来源是 `.github/labels.yml`。

- `workflow`：Nextflow 模块、配置文件、执行行为。
- `parser`：工具输出解析和 JSON 规范化。
- `rule`：阈值、原因代码、参数候选规则。
- `agent`：状态机、规划器、评估器、预算、安全。
- `test`：固定装置、黄金输出、单元/集成/工作流测试。
- `docs`：README、用户指南、开发者指南、报告、ADR。

## 分支策略

- `main` 保持可发布状态。
- 功能分支使用简短名称，如 `feature/config-schema`、`feature/pre-qc` 或 `fix/busco-parser`。
- 仅在与更改相关的测试和文档更新后才合并。
- 基准数据和生成的分析结果保留在 Git 之外，除非它们是故意的小型固定装置。

## 项目板

使用四列：

- 待办
- 进行中
- 审查
- 完成

初始第 1 阶段卡片：

- 创建 `pyproject.toml`。
- 设置 `src/` 布局。
- 添加 pytest 和 ruff。
- 实现 `hifi-agent --help`。
- 添加 GitHub Actions 代码检查和单元测试工作流。
- 定义日志格式和退出代码。

## 第 0 阶段验收说明

- V1 可以用一句话总结。
- Hi-C、三联体、ONT、多倍体自动优化、支架构建和注释被明确排除。
- 一个小型公共固定装置计划和真实的基准候选记录在 `benchmark/datasets.yaml` 中。
- GitHub 标签和项目板结构在本地指定，但远程存储库、问题和项目板必须通过 GitHub 创建。