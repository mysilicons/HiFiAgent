# 当前真实数据与产物 inventory

> 抽查日期：2026-08-11
> 用途：阶段 9 输入、run1 失败证据和 run2 验收结果冻结；不等同于阶段 9 发布验收通过。

## 已冻结真实输入

- `Data/Drosophila_melanogaster/Drosophila_melanogaster_HiFi.fastq`；
- accession `SRR33554835`，PacBio HiFi，`Drosophila melanogaster`；
- 34,915,862,206 bytes，2,430,495 reads，17,357,574,041 bases；
- SHA-256 `38d859e526bd8ded49c3daea9a0211fb7bd7eb328773740ae1ebca98338c1d4d`，
  2026-08-10 从当前 34.9 GB 文件完整重算一致；
- 版本化记录位于 `benchmark/datasets.yaml`，生产配置通过 `HIFI_AGENT_DATA_ROOT` 解析，
  不依赖开发者绝对路径。

## 当前主机短门禁

- 512 logical CPUs，1007.319 GiB 物理内存，18,246 GiB 可用磁盘；
- 真实配置限制为 128 threads、960 GB，Merqury 预留 128 threads/512 GB，磁盘安全底线
  1,000 GiB；
- Java、Nextflow、hifiasm、gfatools、SeqKit、NanoPlot、meryl、QUAST、BUSCO、Merqury、
  minimap2、samtools、R、GenomeScope 和 bedtools 均通过版本预检；
- `diptera_odb12` 已下载至 ignored `results/busco_downloads`，1.6 GB；creation date
  `2026-06-16`、OrthoDB `12.1`、5,067 BUSCOs、76 species，`dataset.cfg` SHA-256
  `bf657327af8b416f27b482a656e0350e968294e786e1481e005f48da3477a75e`；
- editable distribution metadata 已重装为 `3.0.0`；最终 commit 后仍须再重装并重建 wheel；
- `hifi-agent plan configs/drosophila_real_acceptance.yaml` 已得到 environment `PASS`。

## 第一次真实运行

- run UUID：`b0f4c26111e84587a5501ef2f5276f30`；
- 保留目录：`results/Drosophila_melanogaster_acceptance`；
- baseline 完成：181,039,394 bp、229 contigs、N50 23,623,430 bp、BUSCO complete 99.6%、
  mapped read fraction 0.9972；
- Merqury 根目录解析失败，`kmer_qv`/`kmer_completeness` 缺失；
- 控制器安全终止为 `STOP_INSUFFICIENT_EVIDENCE`，没有执行 candidate；
- `verify-run --deep` PASS；`verify-real` 按预期 FAIL（缺少 eligible candidate）；
- 工作树不干净，因此 run identity 的 commit 也不能作为发布绑定；
- 逐项报告见 `stage9_run1_failure_analysis.md`。

缺陷已修复。使用真实 run1 meryl DB/assembly 的诊断 smoke 得到 QV 65.048、completeness
99.0775%，Conda R 绘图 PASS；小型证据保存在 `benchmark/reports/drosophila_merqury_smoke/`。

## 第二次真实运行

- run UUID：`d20d9d34342a49ba838bdaef64aaa985`；保留目录：
  `results/Drosophila_melanogaster_acceptance_run2`；
- baseline 和一个 `purge_level 3→2` 单变量 candidate 均完成，同源 post-QC 和 contract PASS；
- baseline：181,039,394 bp、229 contigs、N50 23,623,430 bp、BUSCO complete 99.6%、
  Merqury QV 65.048、k-mer completeness 99.0775%；
- candidate 未达到任何实质改善阈值，比较结论为 `KEEP_INCUMBENT`，终态为 `STOP_PLATEAU`；
- `verify-run --deep` 和 `verify-real` 均 PASS，逐项报告见 `stage9_run2_assessment.md`；
- run2 在未提交工作树上启动，故不能满足 release commit 绑定；live smoke、0-skip suite 和 bundle 未完成。

## 当前缺失的发布证据

- 干净、已提交 source commit；
- 当前 commit 的 wheel；
- clean commit 上的 run3 baseline、单变量 candidate、同源 post-QC、comparison 和 deep/real verifier；
- live DeepSeek provider→Schema→Safety Arbiter 脱敏 receipt；
- real marker suite 0 failed、0 skipped 的 JUnit；
- `build-evidence` 生成的 acceptance manifest。

配置已切换到 `results/Drosophila_melanogaster_acceptance_run3`。在成功 live receipt、0-skip JUnit 和
clean-commit bundle 实际产生前，阶段 9 状态只能是 `RUN2_SCIENTIFIC_PASS_RELEASE_BLOCKED`，不得写为
`ACCEPTED`。
