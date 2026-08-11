# HiFi Agent V3 阶段 7 恢复矩阵

> 日期：2026-08-10
> 范围：唯一 `RunCoordinator`、common attempt executor、Nextflow runner、事务状态、预算、报告

## 昂贵步骤边界

| 故障边界 | 权威恢复依据 | 恢复行为 | 重复计费/覆盖保护 | 验收证据 |
|---|---|---|---|---|
| `before_pre_qc` | state=`PRE_QC` | 重启 pre-QC | 未启动则无 assembly 费用 | hook 集合断言 |
| `after_pre_qc` | checksummed pre-QC inventory | `resume=True` 验证并复用 | inventory drift 闭锁 | pre-QC resume/tamper test |
| `before_baseline_attempt` | state + 无 final manifest | 同 attempt 启动 | prelaunch ledger reservation | hook 集合断言 |
| `after_baseline_attempt` | attempt manifest + inventory + marker | 验证完成 attempt 后推进 | finalized attempt 不重跑 | coordinator terminal resume test |
| `before_proposal` | frozen decision context | 重放相同 provider controls | context/control hash 不同则拒绝 | proposal resume/idempotency test |
| `after_proposal` | immutable proposal decision/lineage | 直接加载 decision | LLM reservation/call receipt 幂等 | LLM budget resume test |
| `before_candidate_attempt` | approved full config + active attempt id | 启动/恢复该 coordinate | candidate cap 和预算先行 | hook 集合断言 |
| candidate 执行中 | attempt status + attempt-local Nextflow cache | 同 `attempt_001 -resume` | 相同 reservation ID；不新增 attempt | round-2 SIGTERM resume test |
| `after_candidate_attempt` | finalized candidate manifest | 不调用 runner，直接 post-QC/compare | 不重跑、不重复计费 | post-launch controller fault test |
| `before_round_comparison` | 全部 finalized attempt | 重算并独占写 comparison | 缺失/损坏 attempt 闭锁 | hook + evidence tests |
| `after_round_comparison` | immutable comparison JSON | 验证/加载后更新 incumbent | selection 不凭目录猜测 | comparison/incumbent verifier |
| `before/after_reporting` | state + manifest history | 原子重生成报告 | source facts 不修改 | report idempotency test |
| `before/after_deep_verification` | read-only verifier result | 重跑 deep verification | FAIL 覆盖科学成功 | integrity-failure test |
| terminal report finalization | terminal state + verification result | 补齐缺失 canonical report | 已存在报告不静默修复篡改 | missing-report recovery/tamper test |

## 破坏性场景

| 场景 | 预期 | 实际验收 |
|---|---|---|
| Nextflow cache 存在 | 同 attempt 加 `-resume` | PASS |
| Nextflow cache 缺失 | 明确 `InterruptedExecutionError`，不新建 attempt | PASS |
| 部分 post-QC | inventory hash/mtime/size 不符，禁止比较 | PASS |
| 截断 inventory | completion evidence 无效 | PASS |
| 缺失/损坏 marker | attempt 不可比较 | PASS |
| 两个 `assemble` 写者 | 第二个 writer 被 live lock 拒绝 | PASS |
| stale lock | 仅显式 resume/takeover 并归档旧锁 | PASS |
| 磁盘临界/低于保留线 | launch 前 `STOP_BUDGET` | PASS |
| resume 时磁盘观测自然变化 | 复用首次同 ID/同估算 reservation | PASS |
| state/event/ledger 人工篡改 | 明确 FAIL，不猜测修复 | PASS |
| LLM timeout（optional） | rules fallback；receipt 标记 FAILED | PASS |
| LLM timeout（required） | `FAILED_REQUIRED_LLM`，退出码 5 | PASS |
| provider 重复配置 | 保留 raw/rejected lineage，仅一份 executable config | PASS |
| completed candidate 后 controller 退出 | candidate 不重跑、不重复计费 | PASS |
| 失败报告再次生成 | canonical bytes 不变 | PASS |
| 报告 TSV 被改 | `TERMINAL_REPORTS=FAIL` | PASS |
| 关键 assembly artifact 被改 | `DEEP_ARTIFACTS=FAIL` | PASS |

## 闭锁原则

- final attempt manifest、artifact inventory、completion marker 和参数契约四者缺一，不得进入比较；
- resume 只能使用同一 run identity、effective config、policy/RAG snapshot 和 attempt cache；
- state、event、budget 或 history hash chain 无法证明连续性时直接失败；
- verifier 是只读的，只有显式 `assemble --resume` 可以补齐缺失报告；被修改而非缺失的事实不静默修复；
- 所有已启动 attempt 和 LLM call 按 reservation ID 幂等结算，恢复不伪造第二次消费。
