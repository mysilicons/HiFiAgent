# 专家规则标准

规则服务只根据结构化、可追溯且适用于当前样本的质量证据生成确定性结论。它不执行命令，不允许
单一连续性指标覆盖完整性或正确性，也不会从未经授权的文本直接构造参数。

## 基本约束

所有候选必须满足：

- 基于当前 incumbent 的完整配置生成；
- 每个候选只改变一个受控参数；
- 每轮最多两个候选，整个 run 最多三轮；
- 参数类型和值在固定白名单范围内；
- 指标与提案方向一致；
- 治理证据明确授权参数；
- fingerprint 未在当前 run 执行；
- 风险确认和预算通过；
- baseline 与 candidate 使用同一执行和 post-QC 合同。

缺失值不会当作零，也不会自动触发候选。没有足够证据时保守停止。

## 可操作质量信号

确定性规则按顺序选择第一个适用缺陷：

| 信号 | 触发条件 | 适用前提 | 解释 |
|---|---:|---|---|
| BUSCO duplicated | `>2%` | BUSCO 指标有效 | 基因空间重复可能提示去冗余不足 |
| assembly-size ratio | 与 `1.0` 偏差 `>=0.05` | genome size 可信 | 组装规模偏离预期 |
| coverage CV | `>=0.35` | coverage 有效 | 覆盖不均一，需要保守处理 |
| k-mer completeness | `<90%` | k-mer 指标有效 | reads 支持的完整性不足 |
| BUSCO complete | `<95%` | BUSCO 指标有效 | 基因空间完整性不足 |

未命中可操作信号时返回 STOP。`minimum_candidate_runs: 1` 可以要求首轮生成一个受控候选，但仍不能
绕过证据、风险和参数合同。

## 参数白名单

| 参数 | 类型与范围 | baseline 默认值 | 说明 |
|---|---|---:|---|
| `purge_level` | integer，`0..3` | `3` | hifiasm purge 强度 |
| `purge_similarity` | float，`0..1` | `0.55` | purge similarity 阈值 |
| `hom_cov` | positive integer/null | `null` | 同型覆盖估计，证据要求更高 |
| `disable_post_join` | boolean | `false` | 禁用 post-join，属于高影响开关 |

确定性规则只直接产生：

- `purge_level`：当前值大于零时减一，否则设为一；
- `purge_similarity`：当前值不低于 `0.05` 时减 `0.05`，否则加 `0.05`。

`hom_cov` 和 `disable_post_join` 不由默认规则直接生成，只能在完整证据链和 Safety Arbiter 允许时进入
受控 proposal。任何未列出的 hifiasm 参数都不可由 Agent 修改。

## 治理检索

知识索引随 package 发布，记录 source ID、chunk ID、内容 hash、工具版本适配和授权参数。检索步骤：

1. 根据当前缺陷和候选参数筛选；
2. 检查来源与当前 hifiasm 版本兼容；
3. 保留来源多样性；
4. 过滤不授权当前参数的片段；
5. 将选中 evidence IDs 和 hash 写入 retrieval trace。

检索内容只提供参数含义和风险证据。即使文本包含命令或指令，也不会被执行；prompt injection fixture
用于验证这条边界。

## 比较策略

`configs/comparison_policy.yaml` 定义以下行为：

| 指标 | 实质变化 | 硬回退 | 接受下限/适用性 |
|---|---:|---:|---|
| assembly-size ratio | 向 1 改善 `0.05` | 无 | 仅可信 genome size |
| BUSCO complete | `1.0` | 下降 `2.0` | 至少 `95.0` |
| BUSCO duplicated | `1.0` | 无 | 结合倍性解释 |
| k-mer completeness | `1.0` | 下降 `2.0` | 至少 `90.0` |
| k-mer QV | `1.0` | 下降 `2.0` | 无固定下限 |
| mapped read fraction | `0.01` | 下降 `0.02` | 至少 `0.95` |
| coverage CV | `0.10` | 增加 `0.25` | 越低越好 |
| contig N50 | 相对 `10%` | 无 | 次级指标 |
| QUAST misassemblies | 相对 `10%` | 相对增加 `20%` | 仅有参考时 |

任何受保护指标命中硬回退时都不能接受候选。N50 只能作为次级改善证据。多个候选无法形成唯一安全
优胜者时进入人工复核或保留 incumbent。

## 停止条件

- baseline 已满足接受策略；
- 没有适用缺陷或合法候选；
- 候选 fingerprint 已执行；
- 证据不足或工具指标不可用；
- 候选触发硬回退或无实质改善；
- 一个连续无改进轮次达到 plateau；
- 达到最大轮数、assembly 预算或 LLM 预算；
- 风险/候选冲突要求人工复核；
- 必需工具、参数合同或状态完整性失败。

## 审计要求

每轮必须保留 decision context、rule directive、retrieval trace、模型调用回执或未调用原因、原始 proposal、
approved/rejected proposal、完整批准配置、attempt 链接和 comparison。报告只从这些不可变产物生成，
不得从日志文本反推已执行参数。
