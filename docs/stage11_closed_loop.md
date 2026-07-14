# 阶段 11 有限闭环优化

## 安全边界

阶段 11 只执行阶段 8 专家规则已经生成的白名单候选。候选仍只允许
`purge_level`、`purge_similarity`、`hom_cov` 和 `disable_post_join`，不得从 LLM、报告或
自由文本创建参数。默认 `max_retry_rounds=1`，每轮最多两个候选；配置 Schema 的绝对上限
分别为两轮和两个候选。

风险为 `medium_high/high` 的真实候选需要显式 `--confirm-medium-high-risk`。没有确认时保留
候选计划并停止，不启动 hifiasm。

## 真实候选执行

```text
hifi-agent optimize RUN_DIR --execute --confirm-medium-high-risk
```

`CANDIDATE_ONLY` Nextflow entry 执行以下步骤：

1. 校验 resolved config、validation receipt 和输入 checksum；
2. 校验 baseline `.bin` 的 SHA-256，并将同前缀文件重命名为 candidate 前缀；
3. 从 `AssemblyConfig` 生成固定 hifiasm 参数数组；
4. 运行 hifiasm 并保留全部 GFA、FASTA、bin、日志和 manifest；
5. 调用与 baseline 相同的 `QUAST`、`BUSCO_POST_QC`、`MERQURY_POST_QC`、
   `MAPPING_POST_QC` 和 `ASSEMBLY_METRICS` process；
6. 保留失败或被拒绝的 candidate 目录，不执行自动删除。

候选命名固定为 `candidate_r<round>_c<index>`，例如 `candidate_r01_c01`。候选配置持久化在
`05_agent/optimization/candidate_configs/`，真实 workflow 配置同时写入对应 assembly
metadata。

## 比较和选择标准

`comparison.tsv` 对每个候选同时记录 baseline 值、candidate 值、delta 和方向判断：

| 指标 | 优选方向 | 保护规则 |
|---|---|---|
| assembly size ratio | 接近 1 | 依赖可信 genome size |
| BUSCO complete | 高 | 下降超过 2 percentage points 为硬回退 |
| BUSCO duplicated | 结合 size/ploidy 降低 | 不单独决定 |
| k-mer completeness | 高 | 下降超过 2 points 为硬回退 |
| k-mer QV | 高 | 下降超过 2 为硬回退 |
| mapped-read fraction | 高 | 下降超过 0.02 为硬回退 |
| coverage CV | 低 | 增加超过 0.25 为硬回退 |
| N50 | 高 | 永远不能覆盖核心质量回退 |
| misassemblies | 低 | 增加至少 5 且超过 20% 为硬回退 |

严格 Pareto 被支配候选标记为 `DOMINATED`。一个候选只有在存在实质改进、没有保护指标
回退、没有工具失败且核心指标完整时才可 `ACCEPTED`。多个非支配候选存在未解决取舍或指标
方向冲突时输出 `STOP_METRIC_CONFLICT`；无可接受候选且达到轮数上限时输出
`STOP_RETRY_LIMIT`。

## 输出

```text
05_agent/optimization/
├── optimization_result.json
├── comparison.tsv
├── parameter_diff.tsv
├── provenance.tsv
├── selection_tradeoffs.md
└── candidate_configs/
```

阶段 12 会读取 `optimization_result.json`，在最终报告中展示触发规则、参数证据、候选指标、
最终选择和选择代价。真实 baseline 与 synthetic trigger baseline 使用不同记录，绝不混淆。

## Candida albicans 人工异常

`synthesize-stage11-anomaly` 读取真实 Candida 配置、baseline `assembly_metrics.json` 和 Agent
状态并记录 SHA-256。它合成一个 BUSCO duplicated 12% 的触发 baseline，使阶段 8 合法产生
`purge_similarity 0.55→0.50` 候选；候选 N50 提高 50%，同时注入 BUSCO、k-mer、mapping、
coverage 和 misassembly 回退。

场景 JSON、优化结果和最终报告均显示 `SYNTHETIC_DO_NOT_USE_FOR_SCIENCE`。这些指标没有由
候选 hifiasm 或 post-QC 实际产生，不能作为 Candida 科学结论。
