# CLI 参考

安装后入口为 `hifi-agent`，也可使用 `python -m hifi_agent`。所有命令使用稳定退出码，适合 shell、
调度器和 CI 判断。

## 全局选项

```bash
hifi-agent --version
hifi-agent --verbose COMMAND ...
hifi-agent --help
```

`--verbose` 输出调试日志，但不会打印 API key。提交日志前仍应检查样本 ID、目录和外部工具输出是否包含
项目敏感信息。

## `validate`

```bash
hifi-agent validate configs/sample.yaml
```

作用：

- 解析并合并两层配置；
- 验证 FASTQ、gzip、路径和可选参考；
- 完整计算输入 SHA-256；
- 写入 resolved config、input manifest 和 validation receipt。

该命令会写 `00_metadata/`，但不会启动 Nextflow 或 assembly。

## `plan`

```bash
hifi-agent plan configs/sample.yaml
```

只读解析有效配置并执行环境预检，打印最大计划 assembly 数、决策策略和资源结果，不创建 run 状态。

可审计地临时覆盖决策模式：

```bash
hifi-agent plan configs/sample.yaml --decision-mode llm_disabled
```

允许值为 `rules_only`、`hybrid`、`llm_disabled`。CLI override 会进入有效配置来源记录。

## `assemble`

```bash
hifi-agent assemble configs/sample.yaml
```

首次创建 run，之后根据 `runtime.resume_mode` 恢复。高级选项：

```bash
hifi-agent assemble configs/sample.yaml --resume
hifi-agent assemble configs/sample.yaml --decision-mode hybrid
hifi-agent assemble configs/sample.yaml --confirm-medium-high-risk
```

- `--resume`：当全局配置使用 `explicit` 时显式请求恢复；
- `--decision-mode`：覆盖本次 run 的决策模式，成为 identity 的一部分；
- `--confirm-medium-high-risk`：授权已被 Safety Arbiter 批准且策略要求确认的候选。

不要把确认参数理解为“忽略风险”。它不绕过 Schema、证据、参数范围、单变量、预算或 argv 合同。

## `verify-run`

```bash
hifi-agent verify-run results/sample_001
hifi-agent verify-run results/sample_001 --deep
```

默认验证控制状态、日志、预算和 manifests；`--deep` 额外重算 attempt inventory 中所有文件 hash，并
验证六个规范报告。生产终态和归档前应使用 `--deep`。

高级 RAG snapshot 覆盖：

```bash
hifi-agent verify-run results/sample_001 --deep --rag-index /path/to/index.json
```

只在调查明确冻结的外部 snapshot 时使用；正常 run 应验证 identity 已绑定的索引。

## 外部数据集命令

### `check-dataset`

```bash
hifi-agent check-dataset /path/to/datasets.yaml acceptance_dataset
```

读取版本化注册表，通过其中声明的 `HIFI_AGENT_*` 根目录变量定位外部文件，并验证字节数和完整
SHA-256。仓库不内置任何真实数据集注册表。

### `verify-real`

```bash
hifi-agent verify-real \
  results/sample_001 \
  /path/to/datasets.yaml \
  acceptance_dataset
```

除 deep verification 外，还验证：baseline/candidate 比较资格、单变量差异、相同 post-QC 合同、
approved/realized 参数一致性、真实输入 checksum 和 comparator 结果。

## 外部服务验收

### `live-smoke`

```bash
hifi-agent live-smoke results/sample_001 /path/to/live-smoke-output
```

从已完成真实 run 读取一个受治理 round context，执行一次 DeepSeek structured-output 调用，并在新的
输出目录写无密钥 receipt。要求环境中存在 `DEEPSEEK_API_KEY`，目标目录必须尚不存在。

### `build-evidence`

```bash
hifi-agent build-evidence \
  results/sample_001 \
  /path/to/datasets.yaml \
  acceptance_dataset \
  --source-config configs/sample.yaml \
  --wheel /path/to/hifi_agent.whl \
  --live-manifest /path/to/live-smoke-output/live_smoke_manifest.json \
  --real-suite-report /path/to/real-suite.xml \
  --output-dir /path/to/evidence-bundle
```

该命令要求真实 run、注册表、源配置、当前 wheel、live receipt 和零 skip JUnit 报告全部通过，随后写
小型 hash-bound 证据包，不复制大型 reads 或 assembly。

## 退出码

| 退出码 | 分类 | shell 处理建议 |
|---:|---|---|
| `0` | 科学接受或策略停止 | 继续读取 terminal outcome 和 verification |
| `2` | 输入/配置失败 | 修复 YAML、路径、FASTQ 或 checksum |
| `3` | 需要人工动作 | 检查风险、预算或候选冲突 |
| `4` | 工具/合同/完整性失败 | 保留现场，调查后恢复或新建 run |
| `5` | 必需外部服务失败 | 检查服务、凭据和响应 Schema |

示例：

```bash
if hifi-agent assemble configs/sample.yaml; then
  hifi-agent verify-run results/sample_001 --deep
else
  status=$?
  printf 'hifi-agent exited with status %s\n' "$status" >&2
  exit "$status"
fi
```

不要只依赖退出码 0 判断科学质量；必须同时读取 `terminal_outcome`、受保护指标和已知限制。
