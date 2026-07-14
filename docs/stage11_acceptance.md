# 阶段 11 验收报告

验收日期：2026-07-13

## 任务完成情况

| 计划书任务 | 实现证据 | 结果 |
|---|---|---|
| baseline/candidate 命名 | `baseline`、`candidate_r01_c01` 格式与 Schema | PASS |
| candidate 配置生成 | 阶段 8 RETRY + Planner 白名单合并、指纹去重 | PASS |
| 参数差异报告 | `parameter_diff.tsv` 原值、新值、原因、风险、结果 | PASS |
| hifiasm `.bin` 复用 | SHA-256 manifest、candidate 前缀重命名 | PASS |
| 相同 post-QC | `CANDIDATE_ONLY` 调用五个 baseline 同源 process | PASS |
| comparison table | 九项指标 baseline/candidate/delta/assessment | PASS |
| 被支配判定 | baseline 与候选间及候选间 Pareto dominance | PASS |
| acceptance/retry/stop | 强类型 outcome 与硬回退策略 | PASS |
| 最多两个候选 | Planner 和 synthetic Schema 双层限制 | PASS |
| 默认一轮 | `AgentConfig.max_retry_rounds=1` 与 STOP 上限测试 | PASS |
| 指标冲突停止 | `STOP_METRIC_CONFLICT` | PASS |
| 保留所有结果 | `retained_run_ids` 及无删除执行路径 | PASS |

## 计划书验收条款

| 验收条款 | 证据 | 结果 |
|---|---|---|
| Agent 对人工异常生成合法候选 | Candida 真实派生场景产生唯一 `purge_similarity=0.50` | PASS |
| baseline/candidate 同评估流程 | workflow 静态契约、Nextflow 编译和 executor 测试 | PASS |
| 不因 N50 忽略质量退化 | N50 +50% 仍判 `REJECTED_REGRESSION` | PASS |
| 重试上限安全停止 | 一轮后 `STOP_RETRY_LIMIT` 且不选择 candidate | PASS |
| comparison 清晰显示差异 | 参数 JSON + 九项指标四列比较 | PASS |
| 最终报告说明选择代价 | 阶段 12 第 11 章与 `selection_tradeoffs.md` | PASS |

## Candida albicans 真实来源验收

场景源文件为真实 `resolved_config.yaml`、baseline `assembly_metrics.json` 和
`agent_state.json`，三者 SHA-256 在生成时记录并在运行时重新校验。人工触发 baseline 将
BUSCO duplicated 从真实 0.8% 变换为 12.0%，从而合法触发
`ASM_SIZE_TOO_LARGE_AND_DUPLICATED / PROPOSE_STRONGER_PURGE`。

候选把 N50 从 1,247,647 bp 提高到 1,871,470 bp，size ratio 从 1.5733 改善到 1.10，
但 BUSCO complete 降至 82.0%、k-mer QV 降至 12.0、k-mer completeness 降至 45.0%、
mapped fraction 降至 0.75、coverage CV 增至 1.20、misassemblies 增至 250。最终结果为：

```text
candidate: REJECTED_REGRESSION
outcome: STOP_METRIC_CONFLICT
selected_run: NONE
```

所有人工值均有 transformation、真实源值和理由，并在场景、优化输出和最终报告中明确标为
synthetic。

## 自动化结果

```text
阶段 11 核心/执行入口测试: 11 passed
阶段 11 Candida 真实数据: 3 passed
全项目回归: 187 passed, 12 gated skips
ruff format/check: PASS
mypy --strict: PASS
Nextflow CANDIDATE_ONLY 编译: PASS
```

12 个默认 skip 均由真实数据、真实 API 或保留 API 产物的显式环境开关保护。阶段 11 的
3 个真实数据测试已使用 `HIFI_AGENT_REAL_ACCEPTANCE=1` 单独执行并全部通过，不需要网络或
API 密钥。
