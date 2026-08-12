# HiFi Agent V3

HiFi Agent V3 是面向单样本 PacBio HiFi 的受约束组装助手。当前代码是原生 V3 实现：只接受
`schema_id: "hifi-agent"`，只写 canonical V3 run，不包含旧版本控制器、Schema、迁移器、导出器或
兼容执行入口。

当前已实现并严格验收阶段 0～9，阶段 10 发布门禁正在执行：

- 原生 V3 配置、环境预检、不可变 run identity、事务状态日志、单写者锁和统一预算；
- pre-QC 与 baseline 通过公开 `assemble` 的唯一 `RunCoordinator`；
- baseline/candidate 共用 `AssemblyExecutor`、同一 Nextflow entry 和同一 post-QC contract；
- attempt 内六件套参数契约、独立 work/publish/cache、inventory、完成 marker 和 retry/resume 语义；
- typed `DecisionContext`、governed RAG、可选结构化 LLM、单参数 Safety Arbiter、incumbent overlay、
  全局指纹去重和完整 proposal lineage；
- `assemble` 自动完成 baseline review、最多三轮/每轮最多两个候选、受保护多指标比较、plateau、
  budget、human-review 和失败终态；
- 每个终态自动生成 Markdown、JSON、run/parameter/provenance TSV 和 deep verification report；
- attempt/Nextflow cache 恢复、完成后故障恢复、单写者并发拒绝、账本幂等和损坏闭锁均有 portable
  破坏性测试。
- executable fixture 通过真实 CLI 子进程和磁盘边界完成 baseline + 三轮 candidate、round 2 resume、
  recorded LLM replay，以及退出码 `0/3/4/5` 和报告一致性验收。

## 环境

项目要求 Python 3.12。推荐使用仓库环境文件：

```bash
conda env create -f environment.yml
conda activate hifiAgent
python -m pip install -e '.[dev]'
```

真实执行还要求环境预检中列出的 Nextflow、Java、hifiasm、gfatools、SeqKit、NanoPlot、meryl、
QUAST、BUSCO、Merqury、minimap2、samtools、coverage backend、R 和 GenomeScope 工具。

## 五分钟 portable quickstart

以下命令不需要大型数据或付费 API。它会在指定目录安装独立的 fixture 可执行工具副本，并由真实
`python -m hifi_agent assemble` 子进程完成 baseline 和三轮优化；测试套件会执行完全相同的入口。

```bash
python scripts/run_portable_demo.py --workspace /tmp/hifi-agent-portable --scenario three-rounds
```

成功时脚本自身退出 `0`，输出 JSON 中的 `exit_codes` 为 `[0]`，run 的
`06_report/final_summary.json` 为 `STOP_MAX_ROUNDS`。这只证明生产 wiring 可移植，不代表真实生物
数据质量；真实数据和 live LLM 属于阶段 9。

## Drosophila 真实验收

阶段 9 已提供 `configs/drosophila_real_acceptance.yaml`、版本化 dataset registry、真实 run
verifier、release-only pytest suite、live provider smoke 和 evidence builder。配置通过
`HIFI_AGENT_DATA_ROOT` 定位未提交 Git 的 34.9 GB FASTQ，固定使用 128 线程并把内存上限设为
960 GB。完整的预下载、启动、恢复、日志和最终验收命令见
[阶段 9 验收报告](docs/v3/stage9_acceptance.md)。run3 已在 clean commit 上完成真实 baseline、单变量
candidate、同源 post-QC、comparison、live API、0-skip real suite 和 evidence bundle；deep/real verifier
均为 PASS，科学结论为 `KEEP_INCUMBENT / STOP_PLATEAU`。这证明当前受限搜索空间内的真实闭环和审计
链有效，不构成全局参数最优性声明。

## 配置示例：

```yaml
schema_id: "hifi-agent"
sample_id: candida
read_technology: pacbio_hifi
hifi_reads:
  - /absolute/path/reads.fastq.gz
outdir: /absolute/path/results/candida

resources:
  max_threads: 32
  max_memory_gb: 128

optimization:
  enabled: true
  max_rounds: 3
  max_candidates_per_round: 1
  max_parameter_changes_per_candidate: 1
  decision_mode: rules_only
  require_llm: false
  retain_all_attempts: true

execution_budget:
  max_total_assemblies: 4
  max_tool_retries: 1
  max_cpu_hours: 1000
  max_walltime_hours: 168
  min_free_disk_gib: 100
  max_llm_calls_per_round: 1
  max_total_llm_calls: 3
```

`examples/candida_sample_config.yaml` 提供仓库内示例。`plan` 是只读操作，不创建 run：

```bash
hifi-agent plan examples/candida_sample_config.yaml
```

## 命令

```bash
hifi-agent validate sample.yaml
hifi-agent plan sample.yaml --decision-mode rules_only
hifi-agent assemble sample.yaml --decision-mode rules_only
hifi-agent assemble sample.yaml --decision-mode rules_only --resume
hifi-agent verify-run /path/to/results/sample --deep
```

决策模式为 `rules_only`、`llm_disabled` 或 `hybrid`。只有 `hybrid` 可使用 LLM，且
`require_llm: true` 只允许与 `hybrid` 同时配置。在线 API key 只从环境变量读取，不写入 run、日志或
报告。高级离线审计可在 `hybrid` 下配置 checksummed `llm_replay_transcript`；它按 round 绑定响应，
仍经过同一个 Schema 和 Safety Arbiter。

高级 CLI 选项在 `--help` 中标为 `Advanced`。V2 命令与别名已删除，不提供 deprecated 兼容入口；
旧 run 也不会由 V3 读取或迁移。

## Canonical attempt

```text
02_assembly/baseline/attempt_001/
├── metadata/
├── contract/
│   ├── requested_config.json
│   ├── approved_config.json
│   ├── rendered_argv.json
│   ├── hifiasm_command.txt
│   ├── realized_parameters.json
│   └── parameter_contract_check.json
├── workflow/
├── assembly/
├── post_qc/
├── artifacts_manifest.json
├── attempt_manifest.json
└── COMPLETED.json
```

中断恢复复用同一 attempt 和 Nextflow cache；确定性工具失败重试创建新的 `attempt_NNN`。没有完成
marker、inventory 漂移或参数契约失败的 attempt 永远不能进入比较。

## Canonical terminal reports

`assemble` 只在生成并内部验证以下报告后进入 `TERMINAL`：

```text
06_report/
├── final_report.md
├── final_summary.json
├── all_runs.tsv
├── all_parameters.tsv
├── provenance.tsv
└── verification_report.json
```

`final_summary.json` 包含终态类别和进程退出码、完整 incumbent 链、全部 attempt、approved/rejected/
未执行 proposal、requested/approved/rendered/realized 参数、LLM receipt 摘要及预算预留/实际消耗。
退出码为 `0`（科学终态）、`3`（需要人工动作）、`4`（工具/完整性失败）或 `5`（必需 LLM 失败）。

## 开发验收

```bash
ruff check .
ruff format --check .
mypy
pytest --cov --cov-report=term-missing --cov-fail-under=85
pytest -q --cov=hifi_agent.orchestration.controller \
  --cov=hifi_agent.orchestration.comparison \
  --cov=hifi_agent.orchestration.verifier \
  --cov=hifi_agent.reporting --cov=hifi_agent.decision.rules \
  --cov-branch --cov-fail-under=90
nextflow config src/hifi_agent/data/workflow
nextflow lint -output concise src/hifi_agent/data/workflow
```

用户操作细节见 [Quickstart](docs/v3/quickstart.md)、
[决策模式](docs/v3/decision_modes.md)、[恢复](docs/v3/resume_and_recovery.md)、
[预算](docs/v3/budgets.md) 与 [结果解释](docs/v3/result_interpretation.md)。阶段 5–8 的实现、恢复矩阵和
逐项证据见
[严格验收报告](docs/v3/stage5_stage7_acceptance.md)、
[阶段 8 验收报告](docs/v3/stage8_acceptance.md)、
[恢复矩阵](docs/v3/recovery_matrix.md) 与
[需求追踪矩阵](docs/v3/requirements_traceability.md)。
