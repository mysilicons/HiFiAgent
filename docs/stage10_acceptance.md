# 阶段 10 验收报告

验收日期：2026-07-13

## 任务完成情况

| 计划书任务 | 实现证据 | 结果 |
|---|---|---|
| URL、抓取日期、工具版本 | 16 项版本化来源清单 | PASS |
| 按参数和问题切片 | 四参数标签、八类问题标签、336 个真实切片 | PASS |
| 本地检索索引 | Markdown/HTML/PDF + BM25 | PASS |
| 结构化 LLM Schema | Pydantic `LLMExplanation`, extra forbid | PASS |
| 合法 action enum | 规则 decision 唯一映射 | PASS |
| LLM 不得增加参数 | 参数枚举、规则候选集合相等、flag 扫描 | PASS |
| 检索证据进入 trace | `rag_decision_trace.jsonl` source/chunk IDs | PASS |
| 无证据“不足以判断” | API 零调用测试 | PASS |
| rules-only 与 rules+RAG 对比 | `rag_comparison.json` 不变量 | PASS |
| 诱导编造参数安全测试 | extra 字段、未知参数、action/source 越权测试 | PASS |

## 阶段验收

| 验收条款 | 自动化证据 | 结果 |
|---|---|---|
| LLM 输出通过 Schema | 真实 DeepSeek JSON + Pydantic | PASS |
| 编造参数被拒绝 | Schema、参数集合和命令行 token 三层拒绝 | PASS |
| 不可绕过规则与预算 | action/候选对比始终不变 | PASS |
| 关闭 LLM 仍可运行 | Candida rules-only RAG 真实验收 | PASS |
| 报告区分事实与解释 | JSON 分区及 Markdown 独立章节 | PASS |
| 参数解释关联来源 | RETRY 参数来源测试 | PASS |

## 真实数据与真实 API

`document/` 的 15 份资料与 1 份项目规则成功解析为 336 个切片。Candida albicans 的本地检索命中项目规则、
hifiasm 参数/FAQ、BUSCO 手册、QUAST 手册和论文。rules-only 与 rules+RAG 均保留：

```text
Rule decision: STOP / REVIEW_GENOME_SIZE_ESTIMATE
RAG action: STOP_AND_REVIEW
Decision changed: false
Candidate parameters changed: false
```

真实 `deepseek-v4-pro` 输出最终通过全部安全检查。验收过程还发现并拒绝了三类真实模型
问题：仅引用项目规则、置信度高于规则、BUSCO 0.8% 被错误放大为 80%。增加硬约束后，最终
输出正确表述 BUSCO duplication 为 0.8%、引用外部官方来源，confidence 为 0.78（不高于
规则 0.86），且不产生参数候选。

## 自动化结果

```text
ruff format/check: PASS
mypy --strict: PASS
阶段 10 核心安全测试: 18 passed
阶段 10 + CLI 专项: 28 passed
全项目回归: 170 passed, 7 gated skips
阶段 6～10 真实本地数据: 5 passed
DeepSeek 真实 API + retained artifact 复验: PASS
```

默认跳过项全部由真实数据/API 环境开关保护，不是未实现功能。真实 API 测试需显式设置：

```text
HIFI_AGENT_REAL_LLM_ACCEPTANCE=1
DEEPSEEK_API_KEY=<secret environment value>
```
