# V3 阶段 2 严格验收报告

- 验收日期：2026-08-10
- 基线 commit：`1786dcd3cd5b8ecae20b767a5a0c7328656bac6a`
- 验收 worktree：`DIRTY`（阶段 0～2 实现尚未提交）
- 阶段结论：`ACCEPTED`

## 已验收控制平面

- immutable `RunIdentity` 与 snapshot hash/drift receipt；
- 完整 `RunState` phase enum、显式 transition graph、state control checksum；
- single-writer live lock 拒绝与显式 stale takeover 审计；
- pending → fsync → state replace → event append/fsync → pending remove 事务；
- append-only、连续 sequence、唯一 transaction ID 和合法状态链；
- `BudgetLedger` reserve/commit/release/adjust、disk floor、LLM round/global 上限与幂等结算；
- immutable attempt/round manifest 和 append-only history hash chain；
- input/environment pre-identity 失败只写 bootstrap receipt，不创建半成品 identity；
- 旧 schema 和旧 run 被拒绝，不存在 migration/reader 路径；
- 基础 `verify-run` 全程只读并检查 identity、state/event、budget、manifest history 和锁。

## 故障与篡改验收

测试覆盖 pending 后、state 后、event 后三处崩溃，恢复后均只得到一个 sequence=2 的确定状态；
live writer 被拒绝，dead writer 只有显式 takeover 才能接管；同 reservation/commit resume 不重复
扣费；event sequence、state control field、identity snapshot、budget balance 和 manifest 内容被人工
修改时均被拒绝。`verify-run --deep` 的只读测试比较执行前后全部文件 bytes/mtime，结果无变化。

阶段 2 验收控制平面基础设施；阶段 3 已将 pre-QC/baseline 接入唯一 production coordinator。
多轮比较与终态仍属于阶段 5，因此跨阶段 `V3-P0-02` 保持 `IN_PROGRESS`，没有提前宣称完整闭环。
