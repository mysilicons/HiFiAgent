# 资源与预算

[English](../resource-budgets.md) | **简体中文**

资源配置描述单次 workflow 可以请求的主机上限；执行预算限制整个 run 可以消耗的 assembly、重试、
时间和外部调用。二者都会在昂贵操作启动前检查。

## 主机资源

```yaml
resources:
  max_threads: 32
  max_memory_gb: 128
```

- `max_threads`：assembly 的最大线程数，也是各 QC process 计算自身上限的总边界；
- `max_memory_gb`：assembly 的最大内存，其他 process 取该值与自身 cap 的较小值；
- 预检会读取主机逻辑 CPU 和物理内存，配置超过主机能力时失败；
- 不应把两个值设置为物理极限，应为操作系统、Nextflow、文件缓存和并发 QC 留余量。

默认 32 线程和 128 GB 只是通用保守起点。修改后先运行 `plan`，再结合输入规模、覆盖度、杂合度和
历史工具峰值决定是否启动。

## 执行预算字段

| 字段 | 约束 | 计量方式 |
|---|---:|---|
| `max_total_assemblies` | `1..7` | baseline 与所有候选启动总数 |
| `max_tool_retries` | `0..3` | 工具失败后的额外 attempt 数 |
| `max_cpu_hours` | `>=0` | 完成 attempt 报告的累计 CPU 小时 |
| `max_walltime_hours` | `>=0` | 完成 attempt 报告的累计 walltime |
| `min_free_disk_gib` | `>=0` | 每次 launch 前观察到的空闲 GiB 下限 |
| `max_llm_calls_per_round` | `0..1` | 单轮模型调用次数 |
| `max_total_llm_calls` | `0..3` | 整个 run 模型调用次数 |

最大理论 assembly 数为：

```text
min(max_total_assemblies,
    1 + max_rounds × max_candidates_per_round)
```

其中 `1` 是 baseline。实际数量还会受证据、风险确认、重复 fingerprint、plateau 和科学停止条件限制。

## 预算账本

所有可消费预算由 `05_agent/budget_ledger.jsonl` 记录 append-only 操作：

1. `RESERVE`：启动前原子预留；
2. `COMMIT`：操作实际发生后结算；
3. `RELEASE`：未启动或安全撤销时释放；
4. `ADJUST`：受控调整，保留原始限制和原因。

reservation ID 幂等。恢复同一个已经完成的 attempt 不会再次消费 assembly 预算；工具重试创建新
attempt 并按合同计费。磁盘不是累加消费量，而是在每次 launch 前把当前可用容量与保留线比较。

终态 `final_summary.json` 提供：

- `budget_limits`：初始配置上限；
- `budget_reserved`：仍未结算的预留；
- `budget_committed`：已实际消耗；
- `budget_remaining`：当前余额。

## 通用配置方案

### 仅运行 baseline

```yaml
optimization:
  enabled: false
  max_rounds: 0
  max_candidates_per_round: 1
  minimum_candidate_runs: 0
  max_parameter_changes_per_candidate: 1
  plateau_rounds: 1
  decision_mode: rules_only
  require_llm: false
  confirm_risk_level: medium_high
  retain_all_attempts: true
execution_budget:
  max_total_assemblies: 1
  max_tool_retries: 1
  max_cpu_hours: 10000
  max_walltime_hours: 168
  min_free_disk_gib: 100
  max_llm_calls_per_round: 0
  max_total_llm_calls: 0
```

### Baseline 加一个受控候选

```yaml
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
```

不要仅为“用完预算”而设置 `minimum_candidate_runs: 1`。它表示即使 baseline 看起来可接受，也要求
获得至少一个合法的真实比较证据。

## 停止与恢复

- launch 前余额不足：`STOP_BUDGET`，退出码 3；
- 空闲磁盘低于保留线：不启动新昂贵操作；
- 已完成 attempt 恢复：验证后复用，不重复计费；
- pending reservation：恢复时结合事务日志和产物状态对账；
- 修改预算配置不能用于恢复原 run，因为配置 snapshot 属于 immutable identity。

需要扩大预算时，应使用新的输出目录创建独立 run，而不是编辑原 run 的配置或账本。
