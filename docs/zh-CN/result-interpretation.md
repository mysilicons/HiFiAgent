# 结果解释

[English](../result-interpretation.md) | **简体中文**

结果解释必须先通过工程完整性验收，再进入科学指标判断。报告中的“selected”只表示在已执行、合格的
候选中按当前策略选出的 incumbent。

## 第一步：深度验证

```bash
hifi-agent verify-run results/sample_001 --deep
```

`--deep` 会重新哈希 attempt inventory，并核对：

- run identity 与配置、输入、环境和策略 snapshot；
- state、event、transaction 和 budget ledger；
- proposal、approved config、argv 和 realized 参数合同；
- attempt 完成标记与文件 inventory；
- comparison 和 incumbent chain；
- JSON、TSV、Markdown 报告之间的一致性；
- provenance 中引用文件的 SHA-256。

`PASS` 可以继续解释；`WARNING` 必须阅读 reason codes；`FAIL` 表示证据链不完整或不一致，应停止科学
解读并保留现场。

## 六个规范报告

| 文件 | 主要用途 |
|---|---|
| `final_report.md` | 面向人的终态、选中结果、轮次、限制和建议 |
| `final_summary.json` | 权威机器可读终态、退出码、incumbent chain、预算和全部 attempt |
| `all_runs.tsv` | 每个 attempt 的状态、比较资格、指标和资源用量 |
| `all_parameters.tsv` | requested、approved、rendered、realized 参数往返关系 |
| `provenance.tsv` | 关键输入、决策、attempt、比较和报告的相对路径与 hash |
| `verification_report.json` | verifier 检查项、警告、失败和最终状态 |

不要只复制 `final_report.md`。可复核结论至少需要 summary、参数 TSV、provenance 和 verification report。

## 常见终态

| 终态 | 类别/退出码 | 含义 |
|---|---:|---|
| `ACCEPTED_BASELINE` | scientific / 0 | baseline 满足接受或无需继续搜索 |
| `STOP_MAX_ROUNDS` | scientific / 0 | 完成允许的最大轮数 |
| `STOP_PLATEAU` | scientific / 0 | 候选未提供受保护的实质改善 |
| `STOP_NO_LEGAL_CANDIDATE` | scientific / 0 | 没有证据充分且安全的候选 |
| `STOP_RULE_DECISION` | scientific / 0 | 确定性规则给出停止结论 |
| `STOP_INSUFFICIENT_EVIDENCE` | scientific / 0 | 证据不足，保守停止 |
| `STOP_HUMAN_REVIEW` | action required / 3 | 候选冲突需要人工复核 |
| `STOP_CONFIRMATION_REQUIRED` | action required / 3 | 风险策略要求显式确认 |
| `STOP_BUDGET` | action required / 3 | 预算或资源阻止继续启动 |
| `FAILED_TOOL` | failed / 4 | 外部工具或必需产物失败 |
| `FAILED_PARAMETER_CONTRACT` | failed / 4 | 批准参数与 argv/realized 参数不一致 |
| `FAILED_STATE_INTEGRITY` | failed / 4 | 权威状态或报告证据链失败 |
| `FAILED_REQUIRED_LLM` | failed / 5 | 必需外部模型没有返回有效结果 |

科学终态退出码 0 表示流程按策略正常终止，不表示组装达到任何领域通用“商业级”阈值。

## 核心指标

| 指标 | 方向 | 解释与限制 |
|---|---|---|
| `assembly_size_ratio` | 接近 1 | 仅在 `expected_genome_size` 可信时适用 |
| `busco_complete` | 越高越好 | 基因空间完整性；受 lineage 和数据库版本影响 |
| `busco_duplicated` | 越低通常越好 | 必须结合倍性、组装大小和生物学重复解释 |
| `kmer_completeness` | 越高越好 | reads 对 assembly 的 k-mer 支持 |
| `kmer_qv` | 越高越好 | k-mer 一致性估计，不等于独立碱基验证 |
| `mapped_read_fraction` | 越高越好 | reads 对 assembly 的支持，但高 mapping 不是充分条件 |
| `coverage_cv` | 越低通常越好 | 覆盖均一性，受重复和过滤策略影响 |
| `contig_n50` | 越高越连续 | 次级指标，不能覆盖完整性或正确性回退 |
| `quast_misassemblies` | 越低越好 | 仅在提供可信参考基因组时适用 |

如果 `kmer_reads: null`，Merqury 使用同一批 HiFi reads，属于 `same_data_advisory`；它不能替代独立
reads、光学图谱、遗传图谱、Hi-C 或人工结构验证。

## 比较逻辑

候选只有在 post-QC 合同一致、必需指标可用且不存在硬回退时才有比较资格。默认策略的关键保护线：

- BUSCO complete 下降 2 个百分点为硬回退；
- k-mer completeness 下降 2 个百分点为硬回退；
- k-mer QV 下降 2 为硬回退；
- mapped read fraction 下降 0.02 为硬回退；
- coverage CV 增加 0.25 为硬回退；
- 有参考时，QUAST misassemblies 相对增加 20% 为硬回退。

N50 相对提升至少 10% 才算实质变化，但即使提升更大，也不能覆盖上述硬回退。完整策略以
`configs/comparison_policy.yaml` 和 run 内 snapshot 为准。

## 推荐审计顺序

1. 在 verification report 确认完整性；
2. 在 `final_summary.json` 核对 `terminal_outcome`、`selected_run_ref` 和 `incumbent_chain`；
3. 在 `all_runs.tsv` 确认哪些 attempt 有比较资格；
4. 对照 baseline 和 selected 的受保护指标；
5. 在 `all_parameters.tsv` 核对唯一变量及 requested → realized 闭环；
6. 在 `provenance.tsv` 追踪 proposal → approved config → attempt → comparison；
7. 阅读科学限制和 tool failures；
8. 使用独立数据完成项目级生物学验收。

## 对外报告建议

对外描述应明确：输入数据、工具版本、配置 hash、终态、selected attempt、所有受保护指标、是否有
独立 k-mer reads、是否有参考、比较过的候选数量、停止原因和已知限制。避免使用“最优”“无错误”
或“已达到商业级”等无法由当前证据直接支持的表述。
