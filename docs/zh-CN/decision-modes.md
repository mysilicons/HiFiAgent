# 配置与决策模式

[English](../decision-modes.md) | **简体中文**

候选参数的产生与批准是两个独立步骤。规则或模型只能生成不可信 proposal；只有确定性的 Safety
Arbiter 能根据证据、白名单、风险和预算生成可执行的完整配置。

## 配置所有权

HiFi Agent 使用两个严格 Schema：

- `hifi-agent-runtime`：路径、资源、工具、预算、优化、恢复和保留策略；
- `hifi-agent-sample`：reads、样本 ID 和可选科学事实。

错误所有权、未知字段、输入绝对路径、`..` 路径和越过 `data_root` 的链接都会被拒绝。有效配置、
原始配置快照和字段来源会进入 run identity，恢复时不允许漂移。字段细节见
[配置参考](configuration-reference.md)。

## 三种决策模式

| 模式 | 确定性规则 | 治理知识 | 外部模型 | 服务失败语义 |
|---|---|---|---|---|
| `rules_only` | 启用 | 用于授权 | 不调用 | 无合法候选时科学停止 |
| `llm_disabled` | 启用 | 用于授权 | 显式禁用 | 与在线服务完全解耦 |
| `hybrid` + `require_llm: false` | 启用 | 过滤后发送 | 可选 | 失败时确定性降级 |
| `hybrid` + `require_llm: true` | 启用 | 过滤后发送 | 必需 | `FAILED_REQUIRED_LLM`，退出码 5 |

`rules_only` 是默认生产模式；`llm_disabled` 用于需要在配置层明确证明未允许模型调用的环境。两者都
不会读取 `DEEPSEEK_API_KEY`，也不会消耗 LLM 预算。

## Hybrid 配置

```yaml
optimization:
  enabled: true
  max_rounds: 1
  max_candidates_per_round: 1
  minimum_candidate_runs: 0
  max_parameter_changes_per_candidate: 1
  plateau_rounds: 1
  decision_mode: hybrid
  require_llm: false
  confirm_risk_level: medium_high
  retain_all_attempts: true

execution_budget:
  max_total_assemblies: 2
  max_tool_retries: 1
  max_cpu_hours: 10000
  max_walltime_hours: 168
  min_free_disk_gib: 100
  max_llm_calls_per_round: 1
  max_total_llm_calls: 1
```

在线调用使用以下环境变量：

| 变量 | 必需 | 默认值 | 说明 |
|---|---|---|---|
| `DEEPSEEK_API_KEY` | 是 | 无 | 只从进程环境读取，不写入报告 |
| `DEEPSEEK_BASE_URL` | 否 | `https://api.deepseek.com` | OpenAI-compatible endpoint 根地址 |
| `DEEPSEEK_MODEL` | 否 | `deepseek-chat` | 模型名称 |

```bash
export DEEPSEEK_API_KEY='set-in-your-secret-manager'
hifi-agent assemble configs/sample.yaml
```

不要把 key 写入 YAML、shell history、日志或 issue。生产环境应通过作业调度器或密钥管理系统注入。

## 发送边界与隐私

外部请求只包含经过净化的结构化上下文：

- `sample_id`、已知 genome size、是否有参考和是否有独立 k-mer reads；
- 当前受控 assembly 参数及其 fingerprint；
- 适用的聚合 QC 指标；
- 剩余预算、历史轮次结论和已知限制；
- 与可操作参数相关的治理知识片段；
- 严格 JSON 输出 Schema。

不会发送：

- FASTQ reads、组装序列、BAM 或原始 QC 大文件；
- 输入文件内容和绝对路径；
- API key 或 Authorization header；
- 任意 shell 执行端口。

净化器会替换路径样式和 secret 样式文本。`sample_id` 本身会进入上下文；若其包含敏感项目名称，
应在配置中使用不敏感 ID。治理知识是随包发布的固定快照，不会在运行时搜索互联网。

## Safety Arbiter

无论 proposal 来自规则、replay 还是在线模型，都必须同时满足：

1. 严格 JSON Schema，无未知字段；
2. 参数属于 `purge_level`、`purge_similarity`、`hom_cov`、`disable_post_join` 白名单；
3. 只改变当前 incumbent 的一个参数；
4. 类型、范围和指标方向有效；
5. 治理证据明确授权该参数；
6. 参数 fingerprint 未执行过；
7. 风险等级满足人工确认策略；
8. assembly、调用和资源预算仍有余额；
9. 渲染后的 argv 能通过参数合同往返验证。

模型不能批准自己的 proposal，也不能改变 incumbent。原始输出、Schema hash、prompt hash、token 计数、
安全结论和最终执行链接都会留在 `04_decisions/` 与报告中。

## 风险确认

配置要求确认且出现获批的中高风险候选时，流程进入 action-required 终态。确认后使用：

```bash
hifi-agent assemble configs/sample.yaml --confirm-medium-high-risk
```

该参数只授权已经被 Safety Arbiter 批准的候选，不会绕过证据、Schema、单变量、预算或参数合同。

## 离线 transcript replay

需要可重复审计时，可在 `hybrid` 模式使用逐轮记录：

```yaml
optimization:
  decision_mode: hybrid
  require_llm: true
  llm_replay_transcript: ../private/recorded_llm_transcript.json
```

路径相对于全局配置文件解析，并作为输入记录 checksum。每条 response 必须唯一绑定
`round_index`；重复、缺失、错误 JSON 或错误 Schema 均 fail closed。replay 证明同一记录可复现，
不等同于在线服务或真实生物数据验收。

## 选择建议

- 首次部署和常规可重复运行：`rules_only`；
- 网络隔离或合规要求明确禁用外部服务：`llm_disabled`；
- 需要受治理的补充 proposal 且允许发送脱敏聚合上下文：`hybrid`；
- 外部模型是验收必需项时才设置 `require_llm: true`。
