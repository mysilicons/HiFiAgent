# 阶段 9 第一次真实运行失败分析

> 分析日期：2026-08-10
> 结论：`FAIL_REMEDIATED_AWAITING_RERUN`
> run UUID：`b0f4c26111e84587a5501ef2f5276f30`

## 验收结论

第一次 Drosophila melanogaster 真实运行完成了 pre-QC、hifiasm baseline 和大部分 post-QC，且
`verify-run --deep` 通过；但 Merqury 没有产生 `kmer_qv` 和 `kmer_completeness`，控制器因此安全终止
为 `STOP_INSUFFICIENT_EVIDENCE`。没有 eligible candidate、round-1 comparator、live LLM receipt 或
release evidence bundle，所以本次运行不能接受为阶段 9 证据。

此外，run identity 记录的 commit 为 `1786dcd3cd5b8ecae20b767a5a0c7328656bac6a`，但运行时工作树
包含未提交实现。即使生物学门禁全部通过，这也不满足 current clean commit 的发布绑定要求。

## 实际结果

| 项目 | 结果 |
|---|---|
| terminal outcome | `STOP_INSUFFICIENT_EVIDENCE` |
| process exit code | 0（科学证据不足，不是工具进程崩溃） |
| baseline | COMPLETED / comparison eligible |
| assembly size | 181,039,394 bp |
| contig count / N50 / L50 | 229 / 23,623,430 bp / 3 |
| BUSCO complete / single / duplicated | 99.6% / 98.7% / 0.9% |
| mapped read fraction | 0.9972 |
| coverage mean / CV | 94.5874 / 0.47645 |
| assembly size ratio | 1.00577 |
| baseline CPU / walltime / peak RSS | 48.996 h / 1.596 h / 35.95 GiB |
| missing required metrics | `kmer_qv`, `kmer_completeness` |
| candidate | 未执行 |

## 严格门禁

| 阶段 9 要求 | run1 |
|---|---|
| 冻结真实输入及完整 checksum | PASS |
| 环境 manifest、128-thread 配置和离线 BUSCO | PASS |
| baseline 六件套参数 contract | PASS |
| baseline `approved == rendered == realized` | PASS |
| baseline post-QC metrics 完整 | FAIL |
| 单变量真实 candidate | FAIL，未执行 |
| 同源 baseline/candidate post-QC | FAIL，candidate 不存在 |
| comparator 和 reason codes | FAIL，round 1 不存在 |
| `verify-run --deep` | PASS |
| `verify-real` | FAIL：`Real run must contain an eligible baseline and candidate` |
| live provider→Schema→arbiter | 未执行，前置门禁失败 |
| real suite 0 failed / 0 skipped | 未执行，前置门禁失败 |
| clean-commit evidence bundle | FAIL，工作树不干净且前置证据缺失 |

## 根因

Conda 的 `bin/merqury.sh` 是指向 `share/merqury/merqury.sh` 的符号链接。workflow 使用
`dirname "$MERQURY_BIN"` 设置 `MERQURY`，得到错误的 `.../bin` 根目录。真实 stderr 为：

```text
/home/gw/miniconda3/envs/hifiAgent/bin/merqury.sh: line 16:
/home/gw/miniconda3/envs/hifiAgent/bin/util/util.sh: No such file or directory
```

Merqury 失败被结构化记录为 `tool_failures=["merqury"]`，baseline review 检测到两项必需指标缺失，
没有继续执行 candidate。这一失败处理是正确的；缺陷位于 Merqury 启动环境解析。

## 修复和复验

1. workflow 先用 `readlink -f` 解析真实 `merqury.sh`，再设置安装根目录；
2. 环境预检硬性检查 `util/util.sh`、`eval/spectra-cn.sh` 和 `eval/qv.sh`；
3. 环境预检真实加载 R 包 `argparse`、`ggplot2` 和 `scales`；
4. Merqury 调度预留调整为 128 threads / 512 GB；
5. evidence builder 新增源配置 effective hash 和 run outdir 绑定；
6. portable fixture 同步实现相同运行时资产契约。

使用 run1 的真实 3.7 GB meryl DB 和 181 Mb baseline assembly 复验：Merqury 退出 0，在 15 分 49 秒内
生成 QV `65.048` 和 completeness `99.0775%`；Conda R 环境随后完成真实 spectra-cn 绘图。

修复后工程门禁：194 passed、3 个普通 CI 中预期跳过的 release-only tests、总体覆盖率 87.14%、
核心 branch coverage 92.16%、Ruff/format/mypy PASS、Nextflow 6 files lint PASS、真实配置 plan PASS。

## 下一步

保留 `results/Drosophila_melanogaster_acceptance` 作为不可变失败证据。审查并提交当前源代码、重建
wheel 后，使用 `configs/drosophila_real_acceptance.yaml` 启动独立的
`results/Drosophila_melanogaster_acceptance_run2`。run2 必须完成 baseline、一个单变量 candidate、
comparison、deep/real verifier、live smoke、零跳过 real suite 和 evidence bundle，阶段 9 才能通过。
