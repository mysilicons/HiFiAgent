# V3 Resume 与恢复

共享环境配置默认使用 `resume_mode: auto`。`hifi-agent assemble sample.yaml` 首次创建 run；再次执行
完全相同的命令会恢复同一个 immutable run。样本配置、全局配置、CLI override、输入、环境 manifest、
比较策略或 RAG snapshot 漂移时拒绝继续。`resume_mode: explicit` 场景仍可使用 `--resume`。

恢复语义：

- SIGINT/SIGTERM：保留当前 attempt 和 Nextflow cache；恢复必须使用相同 attempt；
- 确定性工具失败：按 `max_tool_retries` 创建新的 `attempt_NNN`，不覆盖旧目录；
- 已完成 attempt：验证 inventory/marker/参数契约后复用，不重跑、不重复计费；
- 部分 post-QC、损坏 inventory/marker：不猜测完成状态，明确失败；
- 已写 manifest 但控制器退出：由 state/event/history 对账推进；
- 报告缺失：从 terminal state 与 manifests 幂等重建；报告被篡改则 verifier 失败。

恢复前先确认没有另一个 live writer。自动或显式 resume 都只允许接管 stale lock。若提示 Nextflow
cache 缺失，不要复制其他 attempt 的 cache；该 attempt 已无法安全恢复。

完整故障与期望动作见 [恢复矩阵](recovery_matrix.md)。
