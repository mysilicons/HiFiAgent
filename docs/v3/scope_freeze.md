# V3.0 范围冻结

V3.0 只解决生产闭环、恢复、审计和发布证据，不扩展科学搜索空间。

## 冻结项

- 单样本 PacBio HiFi；
- Linux x86_64；
- hifiasm 单一 assembler；
- `purge_level`、`purge_similarity`、`hom_cov`、`disable_post_join` 四参数白名单；
- baseline 后 0～3 轮；
- 每轮默认 1、最多 2 candidates；
- V3.0 每个 candidate 只改变一个参数；
- 当前 comparison policy 的指标方向和阈值；
- LLM 只提议，规则、arbiter、预算和 executor 保有最终权限；
- 不提供 V1/V2 reader、迁移器、exporter 或命令兼容层；旧 schema fail closed。

## 变更门槛

assembler、白名单、轮次、候选数、硬回退、LLM 权限或 attempt 布局的变化必须新增 ADR、
任务书修订和真实验收。阶段 0～2 不接受上述范围扩张。
