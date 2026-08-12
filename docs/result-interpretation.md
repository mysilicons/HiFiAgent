# 结果解释

先检查 `06_report/verification_report.json`，或运行：

```bash
hifi-agent verify-run RUN_DIR --deep
```

只有 `PASS` 或允许的 `WARNING` 才适合继续解释。`FAIL` 表示身份、日志、账本、inventory、参数合同
或报告一致性存在问题。

## 常见终态

| 终态 | 退出码 | 含义 |
|---|---:|---|
| `ACCEPTED_BASELINE` | 0 | baseline 已满足配置的接受标准 |
| `STOP_MAX_ROUNDS` | 0 | 完成允许的最大优化轮数 |
| `STOP_PLATEAU` | 0 | 候选没有提供受保护的实质改善 |
| `STOP_NO_LEGAL_CANDIDATE` | 0 | 没有证据充分且安全的候选 |
| `STOP_INSUFFICIENT_EVIDENCE` | 0 | 证据不足，保守停止 |
| `STOP_HUMAN_REVIEW` | 3 | 风险或冲突需要人工确认 |
| `STOP_BUDGET` | 3 | 预算或资源保留线阻止继续运行 |
| `FAILED_TOOL` / contract / integrity | 4 | 工具、参数合同或审计完整性失败 |
| `FAILED_REQUIRED_LLM` | 5 | 配置为必需的外部决策服务失败 |

科学终态退出码为 0，只表示流程按策略正常停止，不代表找到全局最优参数。

## 解释顺序

1. 确认 verification 状态；
2. 在 `final_summary.json` 确认 `selected_run_ref` 与 incumbent chain；
3. 在 `all_runs.tsv` 比较所有已执行 attempt；
4. 在 `all_parameters.tsv` 核对 requested、approved、rendered 和 realized 参数；
5. 在 `provenance.tsv` 追踪 proposal → attempt → comparison；
6. 阅读 `final_report.md` 中的数据限制和停止原因。

N50 是次级指标，不能覆盖 BUSCO、k-mer、mapping 或 coverage 的硬回退。无参考时 QUAST
misassembly 不适用；使用同一批 HiFi reads 的 k-mer 指标属于 same-read 支持证据，不等于独立验证。
