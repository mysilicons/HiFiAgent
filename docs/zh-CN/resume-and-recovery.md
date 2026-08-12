# 自动续跑与故障恢复

[English](../resume-and-recovery.md) | **简体中文**

恢复目标是继续同一个已验证 run，而不是忽略变化后强行重跑。HiFi Agent 使用 immutable identity、
事务状态、append-only 事件、预算账本、单写者锁和 attempt-local Nextflow cache 共同保证恢复安全。

## 恢复模式

双配置默认：

```yaml
runtime:
  resume_mode: auto
  retention: standard
```

`auto` 模式下，首次执行创建 run，再次执行同一命令恢复：

```bash
hifi-agent assemble configs/sample.yaml
```

`explicit` 模式要求显式参数：

```bash
hifi-agent assemble configs/sample.yaml --resume
```

无论哪种模式，`--resume` 都不会绕过完整性验证。

## Immutable identity

恢复前会重新验证并绑定：

- 原始样本配置与全局配置 snapshot；
- resolved/effective config；
- 所有输入文件的字节数和 SHA-256；
- environment manifest；
- comparison policy 和治理知识 hash；
- package version 与代码提交；
- state/event、budget 和 manifest hash chain；
- attempt inventory、completion marker 和参数合同。

任一不可变事实漂移时 fail closed。常见漂移包括修改 FASTQ、替换符号链接目标、编辑配置、升级工具
后试图接续旧环境，以及手工修改报告或 manifest。

## Attempt 语义

- baseline 是 round 0 的独立 attempt；
- 每个候选由 round、candidate 和 attempt 编号唯一标识；
- 同一逻辑坐标的工具重试创建新的 `attempt_NNN`；
- 每个 attempt 拥有自己的 workflow 目录、日志、参数合同、inventory 和完成标记；
- 完成标记最后写入，只有合同和必需产物齐全时 attempt 才可复用；
- 不允许把另一个 attempt 的 Nextflow cache 复制过来。

## 常见故障行为

| 场景 | 恢复行为 |
|---|---|
| SIGINT/SIGTERM | 保留当前 attempt 与 cache；同命令恢复 |
| 确定性工具失败 | 在重试预算内创建新 attempt，不覆盖旧证据 |
| attempt 已完成 | 深度检查后复用，不重跑、不重复计费 |
| manifest 已写但控制器退出 | 用 transaction、event 和 history 对账后推进 |
| 报告尚未生成 | 从权威终态和 manifests 幂等重建 |
| 报告或 inventory 被修改 | verifier 失败，不自动覆盖被修改证据 |
| 第二个 writer 启动 | 单写者锁拒绝并发控制器 |
| stale lock | 验证原进程状态和 run identity 后接管并归档旧锁 |
| 当前 attempt cache 缺失 | 明确失败，不借用其他 attempt cache |
| 配置或输入 checksum 变化 | 拒绝恢复，要求新 run |

## 操作手册

### 进程被中断

1. 确认没有另一个 `assemble` 进程仍在运行；
2. 不删除 `02_assembly/`、`05_agent/` 或当前 work；
3. 使用原样本配置重新执行相同命令；
4. 到 `05_agent/` 和当前 attempt 日志确认恢复事件；
5. 终态后执行 `verify-run --deep`。

### 工具失败

1. 阅读终态 reason code 和 attempt stderr；
2. 修复外部环境问题，例如磁盘、可执行文件或系统资源；
3. 保持配置与输入不变；
4. 在重试预算允许时恢复；
5. 如果必须改变配置或工具合同，创建新的 `output_name`，不要恢复旧 run。

### 锁冲突

不要直接删除锁文件。先确认原 PID、主机和进程是否存活。只有控制器认定为 stale lock 时才允许受控
接管；强行删除可能产生两个 writer 和不可恢复的状态分叉。

### 完整性失败

运行：

```bash
hifi-agent verify-run results/sample_001 --deep
```

保存 verification report 和相关文件，不要让程序覆盖证据。输入、配置、日志、manifest、账本或报告
被修改时，应复制现有 run 做只读调查，并从干净输入创建新 run。

## 保留策略

### `full`

保留所有 workflow work、cache 和中间产物，适合故障调查和方法开发，但磁盘占用最大。

### `standard`

仅在以下条件全部满足后删除可再生 work：

1. run 已进入终态；
2. 六个规范报告存在；
3. deep verification 为 PASS；
4. retention inventory 明确列出可删除目标。

不会删除 assembly、post-QC、参数合同、日志、Nextflow metadata、报告或审计记录，并写入
`00_metadata/retention_receipt.json`。删除共享 `cache/` 不影响已完成报告，但未来运行可能需要重新
下载 BUSCO lineage。
