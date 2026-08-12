# 配置与决策模式

## 配置所有权

HiFi Agent 使用两个互不重叠的配置 Schema：

- `hifi-agent-runtime`：路径根目录、资源、工具、预算、优化和恢复策略；
- `hifi-agent-sample`：reads、物种、基因组大小、倍性、BUSCO lineage 和可选参考。

未知字段、错误所有权和越过 `data_root` 的输入路径都会被拒绝。解析后的完整配置与两个原始配置
快照一起写入 run identity，恢复时不得漂移。

## 决策模式

| 模式 | 规则 | 治理知识 | LLM | 服务失败语义 |
|---|---|---|---|---|
| `rules_only` | 启用 | 用于证据授权 | 不调用 | 无合法候选时科学停止 |
| `llm_disabled` | 启用 | 用于证据授权 | 明确禁用 | 与在线服务完全解耦 |
| `hybrid` + `require_llm: false` | 启用 | 过滤后提供 | 可选 | 失败时使用确定性 fallback |
| `hybrid` + `require_llm: true` | 启用 | 过滤后提供 | 必需 | 失败终态，退出码 5 |

LLM 只能返回严格 JSON proposal。所有 proposal 都必须经过参数白名单、类型和范围、单变量约束、
来源、指标方向、风险、预算、重复指纹与预渲染合同检查。模型没有 executor port，不能直接运行命令
或改变 incumbent。

## 离线 transcript replay

高级审计可以在 `hybrid` 模式配置已记录的响应：

```yaml
optimization:
  decision_mode: hybrid
  require_llm: true
  llm_replay_transcript: ../../private/recorded_llm_transcript.json
```

路径相对于全局配置文件解析，并进入输入 checksum。每条 response 必须唯一绑定 `round_index`；重复、
缺失、错误 JSON 或错误 Schema 均 fail closed。replay 用于可重复审计，不等同于在线服务验收。
