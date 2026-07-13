# 阶段 9 Agent 控制器标准

## 执行边界

阶段 9 将阶段 1～8 的真实产物组合为显式状态机，不使用 LLM，也不接受自由文本命令。
控制器通过 `AgentTools` 接口调用输入验证、pre-QC、baseline 规划、组装产物、post-QC、
规则评价、候选规划和执行摘要。当前真实适配器接管已完成的 workflow 产物；产物缺失时
明确报 `ToolExecutionError`，绝不模拟成功。候选组装的 Nextflow 执行与多候选比较属于
计划书阶段 11。

## 状态与终态

主路径为：

```text
INPUT_VALIDATION → PRE_QC → QC_REVIEW → ASSEMBLY_BASELINE
→ POST_QC → EVALUATE → ACCEPTED / PLAN_RETRY / 安全停止
```

`PLAN_RETRY` 只能进入预算允许的 `ASSEMBLY_CANDIDATE`，候选随后使用相同的
`POST_QC → EVALUATE` 状态。合法业务终态为 `ACCEPTED`、`FAILED_INPUT`、
`STOP_LOW_QUALITY`、`STOP_INSUFFICIENT_METADATA`、`STOP_UNCERTAIN`、
`STOP_BUDGET_EXCEEDED` 和 `FAILED_TOOL_EXECUTION`；最终均进入 `REPORT` 保存阶段 9 摘要。
任何不在转移表中的跳转都会抛出 `IllegalStateTransitionError`。

## 预算标准

`SampleConfig.agent` 包含以下硬上限：

| 字段 | 默认值 | 含义 |
|---|---:|---|
| `max_retry_rounds` | 1 | 参数优化轮数 |
| `max_candidates_per_round` | 2 | 每轮不同参数候选数 |
| `max_tool_retries` | 1 | 同一工具步骤失败后的重试数 |
| `max_cpu_hours` | 10000 | 累计组装 CPU-hour |
| `max_walltime_hours` | 168 | 累计组装 walltime 小时 |

候选启动前用上一组装的真实资源消耗作为保守估计；若预计会越过 CPU-hour 或 walltime
上限，则不启动。baseline 和候选成功后的实际 `cpu_seconds`、`real_time_seconds` 从
`assembly_manifest.json` 计入账本，并按 `run_id` 保证只计一次。

工具失败重试使用 `retry_kind=TOOL_FAILURE`，允许以相同参数重试，但不会增加参数优化轮数。
生物学参数重试使用 `retry_kind=PARAMETER_OPTIMIZATION`，必须经过白名单 Schema、轮数预算、
候选数预算和参数 SHA-256 指纹去重。

## 恢复与审计

每次状态变化先原子替换 `agent_state.json`，再追加并 `fsync` 一条
`decision_trace.jsonl`。快照保留最后一个完整事件；如果进程恰好在两次写入之间中断，
恢复时可补写唯一缺失的末尾事件。多条缺失、非连续 sequence 或 trace 超前均拒绝自动恢复。

`--resume` 从快照继续；已进入 `REPORT` 的运行重复 resume 不会重跑组装或追加状态。

## 真实数据验收

Candida albicans 保留数据中的 baseline hifiasm 资源用量为约 21.56 CPU-hour、0.334
walltime-hour。控制器读取真实 checksum、pre-QC、assembly manifest、阶段 7 指标和阶段 8
规则结果，最终保守停止为 `STOP_UNCERTAIN / REVIEW_GENOME_SIZE_ESTIMATE`，不启动候选组装。
