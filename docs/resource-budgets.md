# 资源与预算

所有昂贵操作在启动前由 append-only ledger 预留，并在完成或失败后 commit/release。

| 字段 | 含义 | 约束 |
|---|---|---:|
| `max_total_assemblies` | baseline 与全部 candidate 总数 | 1–7 |
| `max_tool_retries` | 每个逻辑坐标的额外工具重试 | 0–3 |
| `max_cpu_hours` | run 累计 CPU 小时 | 非负 |
| `max_walltime_hours` | run 累计 walltime | 非负 |
| `min_free_disk_gib` | 每次 launch 前最低可用磁盘 | 非负 |
| `max_llm_calls_per_round` | 每轮外部调用数 | 0–1 |
| `max_total_llm_calls` | 全 run 外部调用数 | 0–3 |

`max_rounds × max_candidates_per_round` 与 assembly 总预算共同限制实际可启动坐标。预算不足发生在
launch 前时，流程进入 `STOP_BUDGET`，退出码为 3；恢复已完成工作不会重复计费。

`06_report/final_summary.json` 分别记录：

- `budget_limits`：配置上限；
- `budget_reserved`：尚未结算的预留；
- `budget_committed`：已经消耗的预算；
- `budget_remaining`：可用余额。

建议为主机保留操作系统与文件缓存余量，不要把 `max_threads` 和 `max_memory_gb` 设置为物理极限。
环境预检会拒绝超过当前主机 CPU 或内存的配置，并在每次昂贵启动前重新检查磁盘保留线。
