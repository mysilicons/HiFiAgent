# 阶段 12 验收报告

验收日期：2026-07-13

## 任务完成情况

| 计划书任务 | 实现证据 | 结果 |
|---|---|---|
| Jinja2 模板 | 严格未定义变量模式、14 个规定章节 | PASS |
| Markdown 与 summary JSON | `final_report.md`、Pydantic `final_summary.json` | PASS |
| 关键图统一复制 | Candida GenomeScope 4 张、Merqury 6 张 | PASS |
| 指标比较表 | `comparison.tsv` 同列展示 baseline/候选 | PASS |
| 参数 diff | 原值、新值、原因、证据、风险、结果 | PASS |
| warning/limitation | 独立章节并汇总工具和 Agent 限制 | PASS |
| 可选路径隐藏 | 默认脱敏；`--show-absolute-paths` 显式关闭 | PASS |
| 可复现命令 | 独立文本文件及报告内代码块 | PASS |
| 失败运行报告 | 空运行目录自动验收，仍完整生成 14 章 | PASS |

## 计划书验收条款

| 验收条款 | 自动化或真实数据证据 | 结果 |
|---|---|---|
| 不读日志可理解分析 | 14 章涵盖输入、QC、规则、选择、限制、错误 | PASS |
| 所有数值回溯原始文件 | 每个 `MetricRecord` 有 source file + JSON pointer | PASS |
| 缺失指标不显示为 0 | JSON `null`、Markdown NA、TSV 空字段；真实 0 保留 | PASS |
| 参数修改有原因/证据/风险/结果 | Schema、Markdown 和 `parameter_diff.tsv` 三处验证 | PASS |
| 标注成功/警告/失败模块 | `SUCCESS/WARNING/FAILED/NOT_RUN` 状态表 | PASS |

## Candida albicans 真实数据验收

真实报告读取 `results/Candida_albicans_phase6` 的配置、输入 checksum、pre-QC、hifiasm
manifest、QUAST、BUSCO、Merqury、mapping、阶段 8 决策、阶段 9 状态和阶段 10 RAG/LLM
解释。报告状态为 `WARNING`，因为真实 Agent 安全停止为 `STOP_UNCERTAIN` 且没有启动候选；
这不是报告失败，也没有被掩盖为成功。

人工异常文件由同一真实 baseline 确定性派生并记录源 SHA-256。候选 N50 从 1,247,647 bp
提高到 1,871,470 bp，但 BUSCO complete 从 98.2% 降至 82.0%、k-mer QV 从 20.29 降至
12.0、k-mer completeness 从 61.1863% 降至 45.0%、mapped-read fraction 从 1.0 降至
0.75，QUAST misassemblies 从 163 增至 250。报告因此输出
`REJECTED_SYNTHETIC_QUALITY_REGRESSION / NO_AUTOMATIC_SELECTION`。

## 自动化结果

```text
阶段 12 单元与 CLI: 6 passed
阶段 12 Candida 真实数据: 2 passed
全项目回归（含阶段 11 联动）: 187 passed, 12 gated skips
ruff check: PASS
ruff format --check: PASS
mypy --strict: PASS
wheel 构建及 Jinja2 模板包内检查: PASS
```

12 个默认 skip 全部由真实数据、真实 API 或保留 API 产物的显式环境开关保护；阶段 12 的
2 个真实数据测试已通过 `HIFI_AGENT_REAL_ACCEPTANCE=1` 单独执行，不需要网络或 API 密钥。
