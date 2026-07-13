# 阶段 10 RAG 与受约束 LLM 标准

## 权限边界

阶段 10 遵循“规则决定、RAG 举证、LLM 只解释”。阶段 8 的 `RuleDecision` 和阶段 9 的
预算账本是唯一决策权威。RAG/LLM 不能修改 decision、action、候选、参数值、重试轮数、
预算或命令，也没有任何 shell/工作流执行接口。

解释 action 只有四种：`KEEP_BASELINE`、`STOP_AND_REVIEW`、
`RETRY_WHITELISTED_CANDIDATE` 和 `INSUFFICIENT_EVIDENCE`。前三种由规则 decision 唯一映射；
无证据时不调用模型，只能返回 `INSUFFICIENT_EVIDENCE`。

## 知识库与索引

知识源文件位于 `document/`，项目规则源位于 `docs/stage8_expert_rules.md`。版本化来源清单
`configs/knowledge_sources.yaml` 为每份资料保存：

- 稳定 `source_id`；
- 官方 URL 或 DOI；
- 2026-07-13 抓取日期；
- 工具/文档版本；
- V1 或超范围参考标记。

当前共 16 个来源：hifiasm 官方参数、FAQ、输出解释和模式文档，BUSCO/QUAST 官方手册，
BUSCO/QUAST/Merqury/GenomeScope 论文，Merqury/GenomeScope 官方仓库文档，以及项目规则。
Hi-C 和 trio 文档被索引为 `out_of_scope_reference`，默认检索排除。

`hifi-agent rag-index` 使用 Markdown 标题、HTML 标题和 PDF 页切片，按 1800 字符上限切分，
为参数与问题类型加标签，并记录每个文件 SHA-256。索引使用本地 BM25，不调用远程 embedding，
生成到被 Git 忽略的 `knowledge/index.json`。真实资料生成 336 个切片。

## DeepSeek 接口

默认配置采用用户提供的 OpenAI 兼容接口：

```text
base_url: https://api.deepseek.com
endpoint: /chat/completions
model: deepseek-v4-pro
api_key: DEEPSEEK_API_KEY 环境变量
```

请求使用 `temperature=0`、`response_format=json_object`，且只发送规则事实和被检索的局部
切片。FASTQ、完整知识库、状态文件和 API key 不进入请求或日志。客户端只依赖 Python
标准库；`pypdf` 仅用于本地论文解析。

## 结构化输出与安全校验

`LLMExplanation` 禁止额外字段，并限制：

- action 必须与规则 decision 唯一映射一致；
- supporting rule 必须来自实际 matched/controlling rules；
- source ID 必须来自本次检索，且至少引用一项外部官方资料或论文；
- 参数只能是四项白名单，且必须与规则候选参数集合完全相等；
- 每个参数解释至少引用一条本次检索来源；
- 自由文本不能新增命令行 flag；
- LLM confidence 不得高于规则 confidence；
- BUSCO 百分比不得再次乘 100；
- 解释不能违背 `BUSCO_DUPLICATION_NOT_HIGH/HIGH` 等确定性分类。

检索文本被视为不可信引用内容。即使文档含有 prompt injection，模型输出仍必须经过上述
Schema 和独立安全校验，失败即拒绝，不自动修补为“看似成功”。

## 输出与命令

```text
hifi-agent rag-index
hifi-agent explain results/<sample> --no-llm
hifi-agent explain results/<sample> --llm
```

输出位于 `04_decisions/<run_id>/`：

- `explanation.json`：分离 authoritative `rule_facts`、retrieval 和非权威 LLM 解释；
- `explanation.md`：明确区分“Rule facts”与“LLM explanation”；
- `rag_comparison.json`：rules-only 与 rules+RAG 不变量对比；
- `rag_decision_trace.jsonl`：记录 source ID、chunk ID、模型及安全结果。

关闭 LLM 时仍运行本地检索并产生完整解释产物。没有合格证据时不调用 API。
