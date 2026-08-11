# V3 阶段 9 真实验收报告与运行手册

> 准备日期：2026-08-10
> 当前状态：`RUN2_SCIENTIFIC_PASS_RELEASE_BLOCKED`，不是 `ACCEPTED`
> 数据：Drosophila melanogaster / SRR33554835 / PacBio HiFi

## 当前结论

阶段 9 的生产配置、外部数据根契约、离线 BUSCO 门禁、强制单变量对照、真实 run verifier、live
provider smoke、0-skip real suite 和 evidence builder 已实现。第一次真实 baseline 已完成，但 Conda
Merqury 的符号链接被 workflow 错误解释为安装根目录，造成 `kmer_qv` 和 `kmer_completeness` 缺失；
控制器按安全策略以 `STOP_INSUFFICIENT_EVIDENCE` 终止，没有执行不可比较的 candidate。该缺陷已修复，
并加入运行时资产预检和回归测试。run2 已完成 baseline、单变量 candidate、comparison、deep verifier
和 real verifier，科学结论为 `KEEP_INCUMBENT / STOP_PLATEAU`。但 run2 仍在未提交工作树上执行，无法
绑定 current clean commit；live API 也因缺少明确的外部数据披露授权而未通过。因此配置已切换到独立
的 `_run3` 目录；run1/run2 均完整保留，但不能代替最终发布证据。

真实配置使用 128 threads、960 GB 上限，在 1 TiB 主机上保留约 64 GB 给系统和文件缓存；Merqury
明确预留 128 threads/512 GB，以覆盖 `meryl-lookup` 的大缓冲区。磁盘安全底线为 1,000 GiB。
配置最多执行 baseline + 一个 candidate，另允许一次工具 retry。

## 已完成的短门禁

| 项目 | 结果 |
|---|---|
| FASTQ 首记录 | PASS，sequence/quality 均 13,036 bp |
| 文件大小 | PASS，34,915,862,206 bytes |
| 完整 SHA-256 | PASS，`38d859e526bd8ded49c3daea9a0211fb7bd7eb328773740ae1ebca98338c1d4d` |
| 主机资源 | PASS，512 CPU / 1007.319 GiB RAM / 18,246 GiB free disk |
| 128-thread/960-GB 请求 | PASS |
| 15 项工具解析与版本 | PASS |
| 修复相关测试 | PASS，28 passed |
| 全量 pytest + coverage | PASS，194 passed / 3 real-only skipped / 87.14% |
| 核心 branch coverage | PASS，92.16%（门槛 90%） |
| Ruff / format / mypy | PASS |
| Nextflow config/lint | PASS，6 files / 0 errors |
| 离线 `diptera_odb12` | PASS，1.6 GB，creation date 2026-06-16，5,067 BUSCOs |
| 包 metadata | PASS，当前 editable package 为 3.0.0；最终 commit 后须重装 |
| 真实配置 `plan` | PASS，environment status PASS |
| run1 `verify-run --deep` | PASS，失败证据本身完整且未损坏 |
| run1 `verify-real` | FAIL，缺少 eligible candidate；符合严格拒绝预期 |
| 修复后真实 Merqury smoke | PASS，QV 65.048 / completeness 99.0775% |

## run2 验收结果

| 项目 | 结果 |
|---|---|
| baseline/candidate | PASS；仅 `purge_level 3→2`，两次运行均完成 |
| post-QC/contract | PASS；必需 metrics 可解析，两套六件套通过 |
| comparison | PASS；`KEEP_INCUMBENT / NO_PROTECTED_MATERIAL_IMPROVEMENT` |
| 终态 | `STOP_PLATEAU`，进程退出码 0 |
| deep/real verifier | PASS / PASS |
| live smoke | AUTHORIZED/PENDING；披露授权已取得，等待 clean-commit run3 context |
| real suite | BLOCKED；3 tests 已选中，缺成功 live manifest |
| evidence bundle | FAIL；运行与当前源码均不是 clean-commit 发布状态 |
| 阶段 9 | **NOT ACCEPTED** |

完整指标、证据哈希、限制和失败门禁见 `stage9_run2_assessment.md`。run2 的科学证据有效，但其 immutable
identity 绑定旧 commit，提交当前代码后也不能追溯修复；最终发布链必须重新产生 run3。

## 第一次运行前

任务书要求 commit、wheel、配置、输入和 run hash 一致，所以必须先审查并提交当前工作树。不要在
dirty worktree 上启动真实 run；`build-evidence` 会硬性拒绝它。

```bash
cd /data/gw/code/HiFiAgent
git status --short

conda run -n hifiAgent python -m pip install --no-deps -e .
conda run -n hifiAgent hifi-agent --version
conda run -n hifiAgent python -m pip wheel --no-deps --no-build-isolation . -w dist

export HIFI_AGENT_DATA_ROOT=/data/gw/code/HiFiAgent/Data
mkdir -p logs results/busco_downloads

conda run --no-capture-output -n hifiAgent hifi-agent check-dataset \
  benchmark/datasets.yaml drosophila_melanogaster_srr33554835 \
  2>&1 | tee logs/drosophila_dataset_check.log

conda run --no-capture-output -n hifiAgent busco \
  --download diptera_odb12 --download_path "$PWD/results/busco_downloads" \
  2>&1 | tee logs/drosophila_busco_download.log

conda run --no-capture-output -n hifiAgent hifi-agent plan \
  configs/drosophila_real_acceptance.yaml \
  2>&1 | tee logs/drosophila_plan.log
```

只有 `hifi-agent --version` 与 `pyproject.toml` 一致、dataset check PASS、BUSCO lineage 已离线冻结、
`plan` 显示 environment PASS 时才能启动。BUSCO 官方建议离线运行前先用 `--download` 获取数据集，
运行时明确报告 lineage 和 creation date。

## 长时间运行

建议在 `tmux` 内运行，以便 SSH 断开后任务继续。该命令保留真实退出码，并将完整控制台写入日志。

```bash
tmux new -s hifi-drosophila
cd /data/gw/code/HiFiAgent
export HIFI_AGENT_DATA_ROOT=/data/gw/code/HiFiAgent/Data
set -o pipefail
conda run --no-capture-output -n hifiAgent hifi-agent assemble \
  configs/drosophila_real_acceptance.yaml \
  2>&1 | tee logs/drosophila_assemble.log
status=${PIPESTATUS[0]}
printf '%s\n' "$status" | tee logs/drosophila_assemble.exit_code
exit "$status"
```

另一个终端可查看进度：

```bash
tmux attach -t hifi-drosophila
tail -n 100 -f logs/drosophila_assemble.log
tail -n 20 results/Drosophila_melanogaster_acceptance_run3/01_pre_qc/logs/trace.txt
find results/Drosophila_melanogaster_acceptance_run3/02_assembly \
  -path '*/workflow/logs/trace.txt' -type f -print
```

若进程收到 SIGINT/SIGTERM 且状态尚未进入终态，使用完全相同的 YAML 恢复：

```bash
export HIFI_AGENT_DATA_ROOT=/data/gw/code/HiFiAgent/Data
conda run --no-capture-output -n hifiAgent hifi-agent assemble \
  configs/drosophila_real_acceptance.yaml --resume \
  2>&1 | tee -a logs/drosophila_assemble.log
```

不要删除 attempt 内的 `workflow/.nextflow` 或 `workflow/work`；它们是恢复证据。确定性工具失败已经
进入终态时，不应盲目 `--resume`，应先分析日志。

## 运行结束后的严格验收

```bash
export HIFI_AGENT_DATA_ROOT=/data/gw/code/HiFiAgent/Data
export HIFI_AGENT_REAL_RUN=/data/gw/code/HiFiAgent/results/Drosophila_melanogaster_acceptance_run3

conda run --no-capture-output -n hifiAgent hifi-agent verify-run \
  "$HIFI_AGENT_REAL_RUN" --deep \
  2>&1 | tee logs/drosophila_verify_deep.log

conda run --no-capture-output -n hifiAgent hifi-agent verify-real \
  "$HIFI_AGENT_REAL_RUN" benchmark/datasets.yaml \
  drosophila_melanogaster_srr33554835 \
  2>&1 | tee logs/drosophila_verify_real.log
```

`verify-real` 要求：同一输入 checksum、完整环境和离线 lineage、baseline/candidate 均可比较、只有
一个参数变化、两边合同 PASS、同源 post-QC、六项关键 metrics 可解析、comparison 为接受或保留
incumbent 且 reason codes 完整、deep verification PASS。

## Live LLM smoke

API key 只放环境变量，不写命令行或文件。smoke 使用真实 run 的 round-1 context、冻结 RAG index、
生产 Schema 和 Safety Arbiter，但不会启动新 assembly。

```bash
read -rsp 'DEEPSEEK_API_KEY: ' DEEPSEEK_API_KEY
export DEEPSEEK_API_KEY
conda run --no-capture-output -n hifiAgent hifi-agent live-smoke \
  "$HIFI_AGENT_REAL_RUN" "$HIFI_AGENT_REAL_RUN/07_evidence/live_smoke" \
  2>&1 | tee logs/drosophila_live_smoke.log
unset DEEPSEEK_API_KEY

export HIFI_AGENT_LIVE_SMOKE_MANIFEST="$HIFI_AGENT_REAL_RUN/07_evidence/live_smoke/live_smoke_manifest.json"
```

smoke 必须记录 `provider=deepseek`、`status=SUCCESS`、prompt/index/schema/output hash，并通过凭据扫描；
LLM 候选可以被 arbiter 拒绝，这不构成 smoke 失败。

## Real suite 和 evidence bundle

```bash
HIFI_AGENT_REAL_ACCEPTANCE=1 \
HIFI_AGENT_DATA_ROOT="$HIFI_AGENT_DATA_ROOT" \
HIFI_AGENT_REAL_RUN="$HIFI_AGENT_REAL_RUN" \
HIFI_AGENT_LIVE_SMOKE_MANIFEST="$HIFI_AGENT_LIVE_SMOKE_MANIFEST" \
conda run --no-capture-output -n hifiAgent pytest -m real_acceptance -ra \
  --junitxml="$HIFI_AGENT_REAL_RUN/07_evidence/real_acceptance.xml" \
  2>&1 | tee logs/drosophila_real_suite.log

conda run --no-capture-output -n hifiAgent hifi-agent build-evidence \
  "$HIFI_AGENT_REAL_RUN" benchmark/datasets.yaml \
  drosophila_melanogaster_srr33554835 \
  --source-config configs/drosophila_real_acceptance.yaml \
  --wheel dist/hifi_agent-3.0.0-py3-none-any.whl \
  --live-manifest "$HIFI_AGENT_LIVE_SMOKE_MANIFEST" \
  --real-suite-report "$HIFI_AGENT_REAL_RUN/07_evidence/real_acceptance.xml" \
  --output-dir "$HIFI_AGENT_REAL_RUN/07_evidence/bundle"
```

bundle 只在 clean HEAD 等于 run/live commit、真实 suite `tests>0/failures=0/errors=0/skipped=0`，且
wheel、registry、source config、resolved/effective config、input/environment manifest、run evidence、
live receipt 全部哈希一致时生成。

## 回传分析材料

长任务结束后至少提供以下路径；无需复制 34.9 GB FASTQ 或完整 assembly：

- `logs/drosophila_assemble.log` 与 `.exit_code`；
- `results/Drosophila_melanogaster_acceptance_run3/06_report/final_summary.json`；
- `results/Drosophila_melanogaster_acceptance_run3/06_report/verification_report.json`；
- `results/Drosophila_melanogaster_acceptance_run3/04_decisions/round_01/comparison.json`；
- `results/Drosophila_melanogaster_acceptance_run3/07_evidence/live_smoke/live_smoke_manifest.json`；
- `results/Drosophila_melanogaster_acceptance_run3/07_evidence/real_acceptance.xml`；
- 若已生成，`results/Drosophila_melanogaster_acceptance_run3/07_evidence/bundle/acceptance_manifest.json`。

收到这些证据后再把阶段状态从 `RUN2_SCIENTIFIC_PASS_RELEASE_BLOCKED` 改为 `ACCEPTED` 或给出逐项失败分析。
