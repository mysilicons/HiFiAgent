# 故障排查

排查时优先保留证据，不要删除 run 目录、锁、attempt 或 manifest。先记录命令、退出码、终态和
reason codes，再决定恢复还是创建新 run。

## 配置与输入

### `Sample configuration failed validation`

检查错误中的完整字段路径。常见原因：未知字段、错误 Schema ID、数字越界、`require_llm` 与模式不
一致。对照[配置参考](configuration-reference.md)，不要通过删除不理解的字段绕过问题。

### 输入文件不存在或逃逸 `data_root`

样本配置只接受相对于全局 `data_root` 的路径：

```yaml
hifi_reads:
  - sample/reads.fastq.gz
```

禁止绝对路径和 `..`。检查符号链接最终目标仍位于 `data_root` 内。

### gzip 或 FASTQ 失败

```bash
gzip -t Data/sample/reads.fastq.gz
seqkit stats Data/sample/reads.fastq.gz
```

不要重新压缩后恢复旧 run，因为输入 bytes 和 SHA-256 已改变。修复数据后使用新输出目录创建 run。

## 环境预检

### `TOOL_NOT_FOUND`

确认已激活正确环境：

```bash
conda activate hifiAgent
command -v nextflow
command -v hifiasm
hifi-agent plan configs/sample.yaml
```

程序优先使用当前 Conda 环境的 `bin/`。只有受控安装位置确实无法进入环境时才使用
`tools.executable_overrides`。

### 版本不符合合同

用 `environment.yml` 重建环境，避免在同一个 run 中原地升级工具。工具版本是 environment manifest
的一部分；升级后应新建 run。

### CPU 或内存超过主机

降低 `resources.max_threads` 或 `resources.max_memory_gb`，同时保留系统和文件缓存余量。修改配置后
重新执行 `plan`。不能用修改后的配置恢复已经创建 identity 的 run。

### 空闲磁盘不足

清理 run 之外的可再生缓存或将 `output_root` 指向容量充足的文件系统。不要在运行中删除当前 attempt
的 `work`。只有基于真实容量评估后才调整 `min_free_disk_gib`。

## BUSCO

### lineage 尚未缓存

`download_missing_busco: true` 时预检可以给出 pending warning，assemble 会在共享 cache 上加锁下载。
确认计算节点允许访问数据源且 `cache_root` 可写。

### 离线环境

预先把完整 lineage 数据放到 `cache_root/busco/`，确认包含有效 `dataset.cfg`，然后设置：

```yaml
tools:
  busco_cache: busco
  download_missing_busco: false
```

错误或不完整的 lineage metadata 会被拒绝，不能用空目录占位。

## Nextflow 与工具执行

### SIGINT/SIGTERM

等待原进程退出，确认没有第二个 writer，然后原样重跑 `assemble`。不要手工追加 `-resume` 给内部
Nextflow；控制器会为当前 attempt 选择正确 cache。

### `FAILED_TOOL`

检查对应 attempt 的 workflow 日志、stderr、exit code 和 completion marker。修复系统级问题后在重试
预算内恢复；如果需要改变输入、资源合同或工具版本，创建新 run。

### 参数合同失败

`FAILED_PARAMETER_CONTRACT` 表示 requested、approved、rendered argv 或 realized 参数不一致。这不是
普通工具重试问题，应保留全部文件并检查 hifiasm banner、argv receipt 和参数解析器。

## 锁与恢复

### 已有 writer

同一 run 只允许一个控制器。检查原进程是否仍在运行，不要直接删除 lock。真正 stale 的锁会在验证
身份和进程状态后受控接管。

### 配置或 checksum 漂移

恢复拒绝是预期安全行为。恢复必须使用创建 identity 时完全一致的配置和输入。确实需要更改时，通过
新的 `output_name` 创建独立 run。

### Nextflow cache 缺失

不能从其他 attempt 复制 cache。保留原 attempt 作为失败证据；根据终态和重试预算创建新 attempt 或新
run。

## 决策服务

### `DEEPSEEK_API_KEY is not set`

`rules_only` 和 `llm_disabled` 不需要 key。只有 `hybrid` 在线调用需要：

```bash
export DEEPSEEK_API_KEY='set-in-your-secret-manager'
```

如果 `require_llm: false`，服务失败应确定性降级；如果为 `true`，预期终态是
`FAILED_REQUIRED_LLM`，退出码 5。

### proposal 被拒绝

查看 `04_decisions/` 下 rejected proposal 的 reason codes。Schema、未授权参数、多变量改变、错误指标
方向、重复 fingerprint 或风险不足都应 fail closed，不要直接执行模型返回文本。

## Verification 失败

```bash
hifi-agent verify-run results/sample_001 --deep
```

保存 `verification_report.json`，定位第一个失败检查。不要编辑 manifest 或报告让其“通过”；应从
provenance 反查被修改、缺失或 hash 不一致的源文件。若证据无法恢复，当前 run 不应继续用于科学结论。

## 获取可复现诊断

报告问题时提供：

- `hifi-agent --version`；
- 操作系统和 Conda 环境导出；
- 使用的命令与退出码；
- terminal outcome 和 reason codes；
- 已脱敏的 environment/verification manifest；
- 最小可复现配置。

不要提供 reads、序列、API key、个人绝对路径或未经授权的真实运行产物。
