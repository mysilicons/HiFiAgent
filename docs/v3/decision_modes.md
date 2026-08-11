# V3 决策模式

| 模式 | 规则 | RAG | LLM | 失败语义 |
|---|---|---|---|---|
| `rules_only` | 启用 | 仅授权规则候选证据 | 不调用 | 无合法候选时科学停止 |
| `llm_disabled` | 启用 | 仅授权规则候选证据 | 明确禁用 | 与在线服务完全解耦 |
| `hybrid` + `require_llm: false` | 启用 | 治理后证据 | 可选 | provider 失败时规则 fallback |
| `hybrid` + `require_llm: true` | 启用 | 治理后证据 | 必需 | 失败终态，退出码 5 |

LLM 只能返回严格 JSON proposal。所有 proposal 都必须经过白名单、严格类型/范围、单变量、来源、
指标方向、风险、预算、全局指纹和预渲染契约；LLM 无 executor port，不能改变 incumbent。

## Recorded replay

高级离线审计可设置：

```yaml
optimization:
  decision_mode: hybrid
  require_llm: true
  llm_replay_transcript: /absolute/path/recorded_llm_transcript.json
```

transcript 是被输入 checksum 和 immutable config 绑定的原生 V3 JSON。每条 response 必须唯一绑定
`round_index`；运行时 receipt 仍记录 context、prompt、Schema、index 和 output SHA-256。重复 round、
缺失 round、错误 JSON 或错误 Schema 均 fail closed。它用于无网络重放，不是 live LLM 验收。
