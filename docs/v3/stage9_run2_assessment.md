# 阶段 9 run2 严格验收报告

> 检查时间：2026-08-11
> 运行目录：`results/Drosophila_melanogaster_acceptance_run2`
> 结论：`RUN2_SCIENTIFIC_PASS_RELEASE_BLOCKED`，阶段 9 **未验收通过**

## 结论摘要

run2 使用冻结的 `Drosophila melanogaster` PacBio HiFi 数据完成了 baseline、一个单变量 candidate、
同源 post-QC、comparison 和终态报告。控制器以进程退出码 0 到达 `STOP_PLATEAU`；candidate 没有硬回归，
但也没有任何受保护指标达到实质改善阈值，因此 `KEEP_INCUMBENT` 是与冻结比较策略一致的科学结论。
`verify-run --deep` 和 `verify-real` 均通过，说明现有 run2 产物链完整且可复核。

阶段 9 仍不能标记为 `ACCEPTED`。run2 绑定的代码 commit 为
`1786dcd3cd5b8ecae20b767a5a0c7328656bac6a`，但运行是在未提交工作树上启动的；release evidence builder
按任务书要求拒绝 dirty source tree。live DeepSeek smoke 的本地受限网络尝试产生了失败 receipt，真正的
外部网络重试当时因尚未获得用户对数据披露范围的明确授权而没有执行。2026-08-11 用户已明确授权
任务书规定的脱敏范围，但 run3 尚未产生；为保证 receipt 与最终 release commit/run identity 一致，调用
将等待 run3 完成。故 0-skip real suite 和 release evidence bundle 也不能完成。

## 逐项验收

| 阶段 9 门禁 | run2 证据 | 结果 |
|---|---|---|
| 冻结真实 PacBio HiFi 样本 | SRR33554835；34,915,862,206 bytes；完整 SHA-256 一致 | PASS |
| dataset manifest 与授权元数据 | `benchmark/datasets.yaml`，外部 `HIFI_AGENT_DATA_ROOT` 契约 | PASS |
| 环境 manifest | 512 CPUs、1007.319 GiB RAM、128 threads/960 GB 请求、15/15 tools、冻结 BUSCO lineage | PASS |
| 当前运行 baseline | baseline completed，所有必需 QC 可解析 | PASS（科学）/ BLOCKED（release commit） |
| 至少一个单变量 candidate | 仅 `purge_level: 3 -> 2`，其余参数及 128 threads 不变 | PASS |
| 同输入、同工具、同 QC 协议 | 输入 checksum 相同；两次 attempt contract 与产物 inventory 完整 | PASS |
| comparator 科学结论 | `KEEP_INCUMBENT / NO_PROTECTED_MATERIAL_IMPROVEMENT` | PASS |
| 实际 argv 与六件套 contract | baseline/candidate 均 `PARAMETER_CONTRACT PASS` | PASS |
| `verify-run --deep` | 全部 identity/journal/budget/hash/contract/QC/incumbent-chain checks | PASS |
| `verify-real` | dataset、单变量、comparison、deep、environment 全部门禁 | PASS |
| live provider→Schema→arbiter | 披露授权已取得；等待 clean-commit run3 context | PENDING_RUN3 |
| real acceptance suite | collect-only 为 3 selected / 194 deselected；未获得成功 live manifest，未执行最终 suite | BLOCKED |
| release evidence bundle | builder 拒绝未提交工作树 | FAIL |

## 真实结果

| 指标 | baseline (`-l 3`) | candidate (`-l 2`) | 解释 |
|---|---:|---:|---|
| Assembly size (bp) | 181,039,394 | 181,301,805 | +262,411 |
| Contigs | 229 | 232 | candidate 略多 |
| Contig N50 (bp) | 23,623,430 | 23,623,430 | 不变 |
| BUSCO complete (%) | 99.6 | 99.6 | 不变 |
| BUSCO duplicated (%) | 0.9 | 0.9 | 不变 |
| Merqury QV | 65.0480 | 64.6867 | -0.3613，未达硬回归阈值 |
| k-mer completeness (%) | 99.0775 | 99.0896 | +0.0121，未达实质改善阈值 |
| Mapped read fraction | 0.9972 | 0.9972 | 不变 |
| Coverage CV | 0.476450 | 0.478463 | 略差，未达硬回归阈值 |
| Assembly size ratio | 1.005774 | 1.007232 | 两者均接近 1 |
| CPU hours | 44.608 | 44.634 | 总计 89.243 |
| Walltime hours | 1.543 | 1.582 | 总计 3.125 |
| Peak RSS (GiB) | 36.490 | 35.277 | 均显著低于配置上限 |

所有受保护指标的 assessment 均为 `UNCHANGED`，candidate 无 hard regression、无 missing required
metric、无 improved metric。保留 baseline 不代表搜索到全局最优参数，只表示在本次受控候选范围内没有
足以替换 incumbent 的证据。

## 验证完整性与限制

- run UUID：`d20d9d34342a49ba838bdaef64aaa985`；package `3.0.0`；终态
  `STOP_PLATEAU`；outcome class `SCIENTIFIC`。
- deep verifier 重新哈希两套约 64.6 GB 的 artifact inventory，并验证两套参数六件套、QC source
  hash、state/journal、budget ledger、history chain 和 incumbent chain，结果 `PASS`。
- `verify-real` 重新核对完整 FASTQ checksum 和全部真实门禁，结果 `PASS`；run evidence SHA-256 为
  `81505e67acf18be40c71133334165c130d08ffc6af8ccab19a3a2af3595a9bba`。
- Merqury 使用同一 HiFi reads，故其 QV/completeness 是 advisory，不是独立 reads 验证；mapping 使用
  长度/质量过滤后的 reads；无 reference 时 QUAST misassembly 指标不适用。两次 attempt 均无 tool failure。
- `logs/drosophila_assemble_run2.log` 存在，但没有单独的 `.exit_code` 文件；机器可读
  `final_summary.json` 记录 `process_exit_code: 0`。

## Live smoke 与隐私边界

首次 `live-smoke` 在本地受限网络环境中约 7.9 ms 即失败，保存的 receipt 为
`provider=deepseek`、`model=deepseek-chat`、`status=FAILED`、
`failure_reason=LLM_PROPOSAL_FAILED:LLMProviderError`，没有 output hash；凭据扫描通过。这个 receipt 只能
证明 fail-closed 行为，不能满足真实 wiring 门禁。

外部调用将发送：脱敏的样本事实、聚合 QC 指标、incumbent 参数和指纹、预算与限制、受治理的 hifiasm
知识片段及响应 Schema。它不会发送原始 FASTQ、任何 reads/序列、绝对路径或 API key。在取得用户明确
用户已于 2026-08-11 明确授权上述范围。run3 尚不存在，因此尚未发起外部调用；不使用 run2 生成最终
receipt，以免 receipt 的 run/commit 身份与 release bundle 不一致。

## 必须执行的下一步

1. 审查当前大量变更并提交，使 `git status --short` 完全为空；重新安装 editable package 并重建 wheel。
2. 使用已切换到 `results/Drosophila_melanogaster_acceptance_run3` 的配置执行 run3。不能在提交后把 run2
   重新包装成发布证据，因为 run2 identity 永久绑定旧 commit。
3. 使用已经明确授权的范围和 run3 真实 context 执行 live DeepSeek smoke，并要求成功 receipt 和凭据扫描 PASS。
4. 执行 3 个 real acceptance tests，必须 `0 failed / 0 skipped`；随后生成 hash 一致的 evidence bundle。

完整 run3 命令见 `stage9_acceptance.md`。只有以上四项全部完成，阶段 9 才能由
`RUN2_SCIENTIFIC_PASS_RELEASE_BLOCKED` 改为 `ACCEPTED`。
