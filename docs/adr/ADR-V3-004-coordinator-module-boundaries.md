# ADR-V3-004：保持单控制器并拆分生命周期职责

- 状态：Accepted
- 日期：2026-08-10
- 决策范围：V3 orchestration maintainability

## 背景

阶段 5～7 完成闭环后，`controller.py` 达到 1481 行，同时承载 phase ordering、round 科学逻辑、报告
恢复、artifact I/O 和 port 类型。继续在一个文件扩展会增加修改状态机时的审查风险。

## 决策

- 保留唯一公开 `RunCoordinatorV3` 与唯一 `RunStateV3`；不创建第二 controller/loop/state；
- phase ordering、锁、bootstrap、executor 调度和统一 reporting transition 留在 controller；
- baseline/round/comparison/incumbent 职责移到 `CoordinatorRoundsV3`；
- reporting/deep verification/recovery 移到 `CoordinatorTerminalV3`；
- create-once artifact helpers 与 ports/result 分别移到 support/models；
- 拆分后 `controller.py` 保持低于 1000 行，并用原阶段 5～7 全场景回归证明语义不变。

## 后果

模块边界与运行权威边界一致。round/terminal service 不能自行获取锁或启动独立 lifecycle，只能由
`RunCoordinatorV3` 调用，因此 ADR-V3-001 的单控制面约束保持不变。
