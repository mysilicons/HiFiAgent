# 阶段 9 验收报告

验收日期：2026-07-13

## 任务完成情况

| 计划书任务 | 实现证据 | 结果 |
|---|---|---|
| 定义 `AgentState` | 16 个操作、业务终态及 REPORT 状态 | PASS |
| 状态转移 | `LEGAL_TRANSITIONS` 与逐跳校验 | PASS |
| `Planner` | baseline 配置、白名单候选合并与命名 | PASS |
| `Evaluator` | 阶段 8 规则评价及终态映射 | PASS |
| 候选去重 | 参数规范化后 SHA-256 指纹 | PASS |
| 重试轮数上限 | `max_retry_rounds` 硬限制 | PASS |
| 候选数上限 | `max_candidates_per_round` 硬限制 | PASS |
| 计算预算 | CPU-hour 与 walltime 实耗/预计消耗检查 | PASS |
| 两类重试区分 | `TOOL_FAILURE` 与 `PARAMETER_OPTIMIZATION` 独立账本 | PASS |
| `decision_trace.jsonl` | 每次状态变化追加、flush、fsync | PASS |
| 中断恢复 | 原子快照、trace 单事件修复、`--resume` | PASS |
| 非法转移异常 | `IllegalStateTransitionError` 包含来源、目标和允许状态 | PASS |

## 计划书验收条款

| 验收条款 | 自动化证据 | 结果 |
|---|---|---|
| 每次状态变化写入日志 | sequence 连续性与行数等于最终计数 | PASS |
| 达到预算后不继续启动组装 | CPU、walltime 和预计候选成本阻断测试 | PASS |
| 相同参数候选不会重复运行 | baseline 同参数及历史指纹测试 | PASS |
| workflow 失败不误判生物学质量 | 组装/post-QC 故障注入均终止为 `FAILED_TOOL_EXECUTION` | PASS |
| 无 LLM 完整执行 | baseline 接受路径及真实停止路径均贯通至 REPORT | PASS |
| 中断后从状态文件恢复 | 中断续跑不重复 baseline，trace 不重复 | PASS |

## 自动化结果

```text
ruff format/check: PASS
mypy --strict: PASS
阶段 9、CLI、配置专项: 52 passed
全项目回归: 150 passed, 4 gated skips
HIFI_AGENT_REAL_ACCEPTANCE=1 tests/integration: 4 passed
```

默认回归中的 4 个 skip 均是显式环境开关保护的真实数据测试；开启开关后阶段 6～9 的
4 个真实测试全部通过，不存在未验收项目。

## Candida albicans 真实数据结果

真实控制器核验并读取：

- 4,829,675,432 bp HiFi 输入及记录 checksum；
- baseline hifiasm manifest；
- 阶段 7 QUAST、BUSCO、Merqury 和 mapping 聚合指标；
- 阶段 8 规则决策。

资源账本记录 `21.561117` CPU-hour、`0.3335225` walltime-hour；最终为
`STOP_UNCERTAIN / REVIEW_GENOME_SIZE_ESTIMATE`。原因是 assembly-size ratio 为
`1.573283`，而 BUSCO duplicated 为 `0.8%`，不支持自动增强 purge。候选组装启动数为 0。

最终 `decision_trace.jsonl` 为 8 条连续事件。对完成状态执行 `--resume` 后仍为 8 条，
未重复运行 baseline、post-QC 或规则评价。
