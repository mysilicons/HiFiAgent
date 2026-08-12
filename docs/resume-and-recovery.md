# 自动续跑与故障恢复

共享环境配置默认使用 `resume_mode: auto`。同一个 `hifi-agent assemble SAMPLE.yaml` 命令首次创建
run；再次执行时恢复既有 immutable run。

恢复前会验证：

- 原始样本配置与全局配置快照；
- resolved/effective config；
- 输入文件大小与 SHA-256；
- environment、comparison policy 与治理知识快照；
- state/event、budget 和 manifest hash chain；
- attempt inventory、completion marker 与参数合同。

任一不可变证据发生漂移时拒绝继续，不会猜测或静默修复。

## 常见故障语义

| 场景 | 恢复行为 |
|---|---|
| SIGINT/SIGTERM | 保留当前 attempt 与 Nextflow cache；同命令恢复 |
| 确定性工具失败 | 在重试预算内创建新的 `attempt_NNN`，不覆盖旧目录 |
| attempt 已完成 | 验证后复用，不重跑、不重复计费 |
| manifest 已写但控制器退出 | 由状态、事件和 history 对账后推进 |
| 报告缺失 | 从终态与 manifests 幂等重建 |
| 报告或 inventory 被修改 | verifier 失败，不覆盖篡改证据 |
| 另一个 writer 正在运行 | 单写者锁拒绝第二个进程 |
| stale lock | 自动或显式 resume 验证后接管并归档旧锁 |
| Nextflow cache 缺失 | 明确失败；不得复制其他 attempt 的 cache |

如果全局设置为 `resume_mode: explicit`，恢复命令为：

```bash
hifi-agent assemble configs/samples/New_species.yaml --resume
```

## 保留策略

- `full`：保留全部工作目录；
- `standard`：仅在终态 deep verification 为 `PASS` 后删除可再生的 pre-QC/workflow work 目录。

标准策略不会删除 assembly、post-QC、参数合同、日志、Nextflow metadata、报告或审计记录，并会写入
`00_metadata/retention_receipt.json`。
