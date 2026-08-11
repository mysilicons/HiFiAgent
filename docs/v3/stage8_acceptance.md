# V3 阶段 8 严格验收报告

> 验收日期：2026-08-10
> 基线 commit：`1786dcd3cd5b8ecae20b767a5a0c7328656bac6a`
> 验收 worktree：`DIRTY`（阶段 0～8 原生 V3 重构尚未提交）

## 结论

阶段 8 `ACCEPTED`。portable suite 不依赖大型数据、网络或付费 API，已通过真实 CLI 子进程、显式
fixture 可执行文件和生产磁盘契约完成 baseline + 三轮 candidate。阶段 9 的真实数据/live LLM
证据未执行，本报告不作替代声明。

## 十项任务逐项验收

| ID | 任务书要求 | 实现与断言 | 结果 |
|---|---|---|---|
| S8-01 | executable fixture，非注入 runner | 15 个显式 override 副本；真实 preflight/argv/subprocess | PASS |
| S8-02 | 真实 CLI/文件边界三轮 | 4 attempts、round 0～3、4 节点 incumbent chain、deep PASS | PASS |
| S8-03 | recorded LLM receipt replay | checksummed hybrid transcript；3 个 round-bound SUCCESS receipt | PASS |
| S8-04 | subprocess/退出码/报告测试 | 科学 `0`、human `3`、tool `4`、required LLM `5` 与 summary 一致 | PASS |
| S8-05 | 重构 controller | 1481→824 行；round/terminal/support/models 分责，无第二控制器 | PASS |
| S8-06 | Ruff/mypy/coverage | Ruff/format、mypy strict、overall/core branch 门禁 | PASS |
| S8-07 | 五类用户文档 | quickstart、decision modes、resume、budgets、results | PASS |
| S8-08 | 自动执行 README 命令 | exact README entrypoint 由 pytest 真实执行 | PASS |
| S8-09 | architecture/ADR/changelog | V3 图、ADR-V3-003/004、Unreleased changelog | PASS |
| S8-10 | advanced/deprecated CLI | help 标注 Advanced；明确删除 V2 deprecated commands/aliases | PASS |

## Portable 场景证据

| 场景 | CLI 退出码 | 终态 | 核心证据 |
|---|---:|---|---|
| `three-rounds` | 0 | `STOP_MAX_ROUNDS` | baseline + 3 candidates；全部 contract/报告/deep PASS |
| `llm-replay` | 0 | `STOP_MAX_ROUNDS` | 3 calls；provider=`recorded:portable-fixture` |
| `resume` | 4 → 0 | `STOP_MAX_ROUNDS` | round 2 SIGTERM；同 `attempt_001`、assembly commit=4 |
| `human-review` | 3 | `STOP_HUMAN_REVIEW` | BUSCO/N50 Pareto 冲突不自动排序 |
| `tool-failure` | 4 | `FAILED_TOOL` | baseline 工具非零退出；自动失败报告 |
| `llm-required-failure` | 5 | `FAILED_REQUIRED_LLM` | 无 API key；receipt/report 明确失败 |

执行 fixture 时还修复了两个 production-only wiring 问题：环境记录的是带工具名的 hifiasm version
banner，RAG 原先要求字符串完全相等；以及前八个 chunk 可被一个 source 占满，Safety Arbiter 又把
同 source 多 chunk 覆盖为最后一个。现版本按完整 token 匹配、检索 round-robin 保留 source diversity，
arbiter 对同 source 全部证据求授权，仍保持 fail closed。

## 实际质量门禁

| 命令 | 结果 |
|---|---|
| `ruff check .` | PASS |
| `ruff format --check .` | PASS，74 files |
| `mypy` | PASS，73 source/test files |
| `pytest -q` | PASS，181 passed，0 failed，0 skipped |
| `pytest --cov --cov-report=term-missing --cov-fail-under=85 -q` | PASS，181 passed，总体 90.58% |
| V3 core `--cov-branch --cov-fail-under=90` | PASS，92.17% |
| `pytest tests/workflow -ra` | PASS，5 passed |
| `nextflow -version` | PASS，25.04.7 build 5955 |
| `nextflow config workflow` | PASS |
| `nextflow lint -output concise workflow` | PASS，6 files，0 error/warning |

core branch gate 包含 controller、拆分后的 rounds/terminal、comparison、verifier、reporting 和
decision rules。fixture 可执行副本从 coverage 分母排除，因为它们不是 `hifi_agent` 生产包源码。

## 边界

- 没有恢复 V2 reader、schema、migration、adapter、report/export 或 CLI alias；
- clean-clone portable 命令已进入 README 和自动测试；
- 阶段 9 的真实 PacBio 样本、实际 hifiasm/QC 和 live provider wiring 仍需单独验收；
- 阶段 10 的 wheel/sdist/tag/release evidence 仍未执行。
