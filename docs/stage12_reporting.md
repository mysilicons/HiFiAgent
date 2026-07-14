# 阶段 12 报告系统

## 设计目标

阶段 12 只汇总已有结构化事实，不重新解释工具日志，也不让 RAG/LLM 改写规则结论。报告
采集器以容错方式读取阶段 1～10 产物；关键文件缺失或损坏时仍输出报告，同时保留失败状态、
错误原因和缺失值。

## 命令与输出

```text
hifi-agent report RUN_DIR
hifi-agent report RUN_DIR --output-dir OUTPUT_DIR
hifi-agent report RUN_DIR --show-absolute-paths
```

默认输出到 `RUN_DIR/05_report/`：

| 文件 | 内容 |
|---|---|
| `final_report.md` | Jinja2 生成的 14 章节人类可读报告 |
| `final_summary.json` | 经过 Pydantic 校验的完整结构化报告 |
| `comparison.tsv` | baseline、真实候选和显式 synthetic 候选的同列指标 |
| `parameter_diff.tsv` | 每次参数变化的原因、证据、风险和结果 |
| `provenance.tsv` | 输入产物状态、SHA-256 和字节数 |
| `software_versions.tsv` | 软件版本及版本来源文件 |
| `reproducible_commands.txt` | 可复现的安全命令清单 |
| `figures/` | GenomeScope 与 Merqury 关键图的统一副本 |

所有展示指标由 `MetricRecord` 包装，包含 `source_file` 与 JSON pointer。真实 0 原样保留；
不可用值在 JSON 中为 `null`、Markdown 中为 `NA (not available)`、TSV 中为空字段。

## 路径与失败处理

报告默认把运行目录替换为 `${RUN_DIR}`，外部输入替换为 `${EXTERNAL}/<basename>`，复现命令
中的 reads 替换为 `${INPUT}/<basename>`。只有显式传入 `--show-absolute-paths` 才展示绝对
路径。

关键输入验证、pre-QC、baseline assembly 或聚合 post-QC 缺失/损坏时，报告状态为
`FAILED`。非关键模块缺失或出现限制时状态为 `WARNING`，未执行模块为 `NOT_RUN`。这些状态
始终出现在第 14 章，不会因为报告渲染成功而改成成功。

## Candida albicans 人工异常

```text
hifi-agent synthesize-report-anomaly results/Candida_albicans_phase6
```

该命令读取真实 Candida baseline 的配置、`assembly_metrics.json` 和 Agent 状态，记录三份
源文件 SHA-256，再生成
`benchmark/perturbations/candida_albicans_quality_regression.json`。人工候选故意把 N50 提高
50%，同时降低 BUSCO complete、k-mer QV/completeness 和 mapped-read fraction，并增加
coverage CV 与 QUAST misassemblies，以验证系统不会只按 N50 选组装。

该文件不是 hifiasm 或 QC 工具输出。Schema 强制 `synthetic=true`，disclaimer 必须包含
`SYNTHETIC_DO_NOT_USE_FOR_SCIENCE`；最终报告再次显示醒目警告，选择结果固定为
`NO_AUTOMATIC_SELECTION`。源指标、变换方式、理由和源文件哈希均保留，机器特定路径已脱敏。
