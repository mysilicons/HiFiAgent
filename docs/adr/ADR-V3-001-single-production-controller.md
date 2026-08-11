# ADR-V3-001：一个生产控制器和一个权威状态

- 状态：Accepted
- 日期：2026-08-10
- 决策范围：V3 orchestration

## 背景

V2 同时存在 Stage 3 `AssemblyController`、legacy Agent 和独立 `OptimizationLoop`。它们分别
拥有状态、恢复或轮次职责，导致公开 `assemble` 只运行到第一候选，后续比较和报告需要用户
手工拼接。

## 决策

V3 只允许 `hifi-agent assemble` 使用一个生产 `RunCoordinator` 和一个 `RunStateV3`：

1. `RunStateV3` 是 lifecycle 的唯一权威 snapshot；
2. event journal 和 budget ledger 是 append-only 审计记录，不是第二份可独立推进的 state；
3. 旧 `OptimizationLoop` 和独立持久化实现删除，后续能力只扩展 `RunCoordinatorV3`；
4. proposer、executor、post-QC、comparator 和 reporter 通过 typed ports 被 coordinator 调用；
5. V1/V2 控制器、reader、迁移器和过渡入口全部删除；
6. 阶段 2 先建立控制平面，阶段 5 再完成生产 coordinator 接管。

## 后果

- 优点：resume、预算、报告和 selected run 只有一个事实源；
- 代价：历史 run 不可由本包读取或迁移；
- 约束：不得通过增加 `V3OptimizationLoopState` 等第二权威状态规避整合。

## 验收

- 一个 V3 run 只有 `05_agent/run_state.json`；
- event/ledger 可从 state 对账但不能单独推进科学状态；
- round 2/3 的生产测试最终必须通过公开 `assemble`。
