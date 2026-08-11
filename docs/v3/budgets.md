# V3 预算

所有昂贵操作在启动前由一个 append-only ledger 预留，并在完成/失败后 commit 或 release。核心配置：

| 字段 | 含义 | V3 上限 |
|---|---|---:|
| `max_total_assemblies` | baseline 与全部 candidate 总数 | 7 |
| `max_tool_retries` | 每个逻辑坐标的额外工具重试 | 3 |
| `max_cpu_hours` | run 累计 CPU 小时 | 用户配置 |
| `max_walltime_hours` | run 累计 walltime | 用户配置 |
| `min_free_disk_gib` | 每次 launch 前最低可用磁盘 | 用户配置 |
| `max_llm_calls_per_round` | 每轮 LLM 调用 | 1 |
| `max_total_llm_calls` | 全 run LLM 调用 | 3 |

`max_rounds × max_candidates_per_round` 与 assembly 总预算共同限制可启动坐标。预算在 launch 前失败时
终态为 `STOP_BUDGET`、退出码 3；已完成的工作不会因 resume 再计费。`final_summary.json` 分别显示
limits、reserved、committed 和 remaining，reserved 不等于实际消耗。
