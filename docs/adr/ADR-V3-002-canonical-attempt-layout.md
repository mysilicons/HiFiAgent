# ADR-V3-002：自包含 canonical attempt 布局

- 状态：Accepted
- 日期：2026-08-10
- 决策范围：V3 assembly/post-QC artifacts

## 背景

当前 Stage 3 主控制器把真实 candidate 产物发布到 V1 平铺目录，而 attempt 目录只保存引用；
独立 `CandidateExecutor` 则已经实现隔离 workflow。两种布局导致不可覆盖语义和报告发现规则不一致。

## 决策

V3 baseline/candidate 都以 attempt 为 canonical 审计单元：

```text
02_assembly/<logical-run>/attempt_NNN/
├── metadata/
├── contract/
├── workflow/
├── assembly/
├── post_qc/
├── artifacts_manifest.json
└── COMPLETED.json
```

补充规则：

1. baseline 采用 `baseline/attempt_001`，不再拥有较弱契约；
2. interruption 恢复同一 attempt，确定性 retry 创建新 attempt；
3. 完成 marker 最后写；
4. report/comparator 通过 manifest 查找产物；
5. `03_post_qc` 只提供索引，不复制大文件；
6. 不实现 V1/V2 目录 reader 或兼容视图。

## 后果

- 每次执行可以独立 checksum、归档和离线验证；
- Nextflow publish/work/resume 路径需要在阶段 3 统一调整；
- 历史消费者不属于 V3 包的支持范围。

## 验收

- 任一 attempt 不覆盖先前 attempt；
- 没有完成 marker 的 attempt 不参与比较；
- baseline 和 candidate 生成相同等级的参数契约和 inventory。
