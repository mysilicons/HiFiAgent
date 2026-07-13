# 阶段 1–7 严格验收说明

本文件定义可重复执行的阶段 1–7 验收证据。README 中的完成声明不能替代自动化测试或
真实运行产物。

## 本地质量门禁

```bash
conda run -n hifiAgent ruff check .
conda run -n hifiAgent ruff format --check .
conda run -n hifiAgent mypy
conda run -n hifiAgent pytest
conda run -n hifiAgent hifi-agent --help
```

CI 在 push 和 pull request 时执行相同的 Python 门禁。独立的 `nextflow-resume` job 使用
Java 21 和 Nextflow 25.04.7，真实终止运行中的工作流后执行 `-resume`，并检查缓存恢复。

## 分阶段证据

1. 阶段 1：`test_engineering_quality.py` 检查公共函数注解、docstring 和内置 `print()`；
   Git 分支必须为 `main` 且至少有一个 commit。
2. 阶段 2：配置测试覆盖缺失文件、损坏 gzip、FASTQ、字段范围和范围外输入；
   `validation_receipt.json` 绑定 resolved config 与输入 checksum 清单。
3. 阶段 3：`test_nextflow_resume_acceptance.py` 验证中断恢复、缓存和正确输出保留。
4. 阶段 4：`tests/golden/raw_metrics.json` 对固定输入执行内容级和字节级回归。
5. 阶段 5：测试覆盖 coverage、空估计、GenomeScope 失败、来源标签、低覆盖峰和重复解析。
6. 阶段 6：真实 Candida 验收必须产生 GFA、三个 FASTA、三个 `.bin`、资源清单；复用运行
   必须记录至少三个 reused bin，且 hifiasm 明确报告从磁盘加载 corrected reads/overlaps。
7. 阶段 7：真实结果必须包含 QUAST、BUSCO、Merqury、mapping；所有 scalar metrics 都要
   分类，mapping 使用过滤 reads，BUSCO 保存实际 lineage 和数据集版本。

## 真实数据验收

```bash
THREADS=128 MEMORY_GB=256 bash scripts/validate_phase6_candida_bin_reuse.sh
conda run -n hifiAgent hifi-agent validate \
  results/Candida_albicans_phase6/logs/phase6_validation/candida_phase6_config.yaml
conda run -n hifiAgent hifi-agent evaluate results/Candida_albicans_phase6
HIFI_AGENT_REAL_ACCEPTANCE=1 conda run -n hifiAgent pytest \
  tests/integration/test_real_stage6_stage7_acceptance.py
```

真实数据、Nextflow work 目录和结果目录受 `.gitignore` 管理，不提交到 Git；CI 验收使用
合成 fixtures，真实验收在具备本地数据和工具的服务器执行。
