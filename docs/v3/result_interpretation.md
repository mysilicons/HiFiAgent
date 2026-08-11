# V3 结果解释

先检查 `06_report/verification_report.json`。只有 `PASS`/允许的 `WARNING` 才适合继续解释；`FAIL`
表示身份、日志、账本、inventory、参数契约或报告一致性存在问题。

常见终态：

| 终态类别 | 退出码 | 含义 |
|---|---:|---|
| `ACCEPTED_BASELINE` / `STOP_MAX_ROUNDS` / `STOP_PLATEAU` | 0 | 科学流程正常停止，不等于全局最优 |
| `STOP_NO_LEGAL_CANDIDATE` / `STOP_INSUFFICIENT_EVIDENCE` | 0 | 无可安全执行候选或证据不足 |
| `STOP_HUMAN_REVIEW` / `STOP_BUDGET` / confirmation | 3 | 需要操作者决策，未自动选择冲突候选 |
| `FAILED_TOOL` / contract / integrity | 4 | 工具或审计完整性失败 |
| `FAILED_REQUIRED_LLM` | 5 | 配置要求的外部决策服务失败 |

`selected_run_ref` 必须等于 `incumbent_chain` 尾部；每次接受只能来自 protected multi-metric 比较。
N50 不可覆盖 BUSCO、k-mer、mapping 或 coverage 的硬回退。`all_parameters.tsv` 对照 requested、
approved、rendered 和 realized；`provenance.tsv` 追踪 proposal→attempt→comparison。

fixture、same-read k-mer 和缺少 reference 的指标都有明确 limitation。报告只声称“在已执行候选中证据
最佳”，不声称找到全局最优参数或完成阶段 9 的真实数据验收。
