# V3 阶段 0～9 需求追踪矩阵

> 基线：`main@1786dcd3cd5b8ecae20b767a5a0c7328656bac6a`
> 任务书：`HiFi_Agent_Project_Plan.md`
> Owner：HiFi Agent maintainer

## 状态定义

- `PLANNED`：已有验收设计，尚未实现；
- `IMPLEMENTED`：代码和测试已经实现；
- `ACCEPTED`：阶段验收命令已经通过；
- `BLOCKED`：存在明确外部阻断。

## P0/P1 追踪

| Requirement | Owner | 阶段 | 实现位置 | 验收位置 | 状态 |
|---|---|---:|---|---|---|
| V3-P0-01 单命令完整闭环 | maintainer | 5 | `orchestration/controller.py` | `tests/test_orchestration.py` | ACCEPTED |
| V3-P0-02 单一权威状态 | maintainer | 2/5 | `orchestration/runtime_models.py`, `journal.py` | control-plane + three-round tests | ACCEPTED |
| V3-P0-03 真实验收证据可重放 | maintainer | 0/9 | dataset registry、real verifier、live smoke、evidence builder | release real gate | IMPLEMENTED |
| V3-P0-04 生产三轮而非独立 loop | maintainer | 5/8 | `RunCoordinator` + executable fixture | real CLI subprocess three-round suite | ACCEPTED |
| V3-P1-01 配置驱动生产执行 | maintainer | 1/5 | runtime config + coordinator | runtime/CLI/three-round tests | ACCEPTED |
| V3-P1-02 自包含 attempt | maintainer | 3 | `executors/assembly.py`, `executors/nextflow.py` | `tests/test_executor.py` | ACCEPTED |
| V3-P1-03 统一预算 | maintainer | 2 | `orchestration/budget.py` | `tests/test_control_plane.py` | ACCEPTED |
| V3-P1-04 crash-safe state/event | maintainer | 2 | `orchestration/journal.py` | `tests/test_control_plane.py` | ACCEPTED |
| V3-P1-05 自动终态报告 | maintainer | 6 | `reporting/models.py`, `service.py` | terminal/report consistency tests | ACCEPTED |
| V3-P1-06 baseline 六件套 | maintainer | 3 | `executors/assembly.py`, `executors/hifiasm_contract.py` | `tests/test_executor.py` | ACCEPTED |
| V3-P1-07 环境可复现 | maintainer | 1 | `environment.py`, `tool_resolution.py`, `environment.yml` | `tests/test_environment.py` | ACCEPTED |
| V3-P1-08 文档示例自动验证 | maintainer | 1/8 | README portable quickstart | exact README entrypoint subprocess test | ACCEPTED |

## 阶段 0～2 详细追踪

| ID | 要求 | 实现/交付物 | 测试或证据 | 状态 |
|---|---|---|---|---|
| V3-S0-01 | V3 任务书进入仓库 | `HiFi_Agent_Project_Plan.md` | Git status/review | ACCEPTED |
| V3-S0-02 | 单控制器 ADR | `docs/adr/ADR-V3-001-single-production-controller.md` | 文档审查 | ACCEPTED |
| V3-S0-03 | canonical attempt ADR | `docs/adr/ADR-V3-002-canonical-attempt-layout.md` | 文档审查 | ACCEPTED |
| V3-S0-04 | 当前质量基线 | `benchmark/reports/v3_baseline_quality.json` | JSON parse + recorded commands | ACCEPTED |
| V3-S0-05 | 接口和 Schema inventory | `docs/v3/current_interface_inventory.md` | 文档审查 | ACCEPTED |
| V3-S0-06 | 真实产物 inventory | `docs/v3/current_real_artifact_inventory.md` | 当前路径抽查 | ACCEPTED |
| V3-S0-07 | scope freeze | `docs/v3/scope_freeze.md` | ADR/task board | ACCEPTED |
| V3-S1-01 | V3 schema/read technology | `schemas/sample.py` | runtime config tests | ACCEPTED |
| V3-S1-02 | execution budget config | `schemas/sample.py` | boundary/conflict tests | ACCEPTED |
| V3-S1-03 | CLI/config/default 来源 | `runtime_config.py` | source-map tests | ACCEPTED |
| V3-S1-04 | `assemble --decision-mode` | `cli.py` | CLI override test | ACCEPTED |
| V3-S1-05 | 只读 `plan` | `cli.py` | no-write CLI/real example gate | ACCEPTED |
| V3-S1-06 | environment preflight/manifest | `environment.py`, `tool_resolution.py` | missing/version/real-tool gates | ACCEPTED |
| V3-S1-07 | README 示例可执行 | `README.md`, Candida example | actual `plan` tests | ACCEPTED |
| V3-S2-01 | immutable V3 identity | `runtime_models.py`, `identity.py` | identity drift/hash tests | ACCEPTED |
| V3-S2-02 | V3 state/transition | `runtime_models.py`, `journal.py` | graph/checksum/tamper tests | ACCEPTED |
| V3-S2-03 | single-writer lock | `lock.py` | live/stale/concurrent tests | ACCEPTED |
| V3-S2-04 | pending transaction recovery | `journal.py` | three crash-window tests | ACCEPTED |
| V3-S2-05 | append-only event trace | `journal.py` | prefix/sequence/graph tests | ACCEPTED |
| V3-S2-06 | unified budget ledger | `budget.py` | reserve/commit/release/tamper tests | ACCEPTED |
| V3-S2-07 | attempt/round/history manifests | `manifests.py` | immutability/hash-chain tests | ACCEPTED |
| V3-S2-08 | bootstrap failure/drift/旧 schema 拒绝 | `bootstrap.py`, `identity.py` | negative CLI/drift tests | ACCEPTED |
| V3-S2-09 | basic `verify-run` | `verifier.py`, `cli.py` | read-only/tamper tests | ACCEPTED |

## 阶段 3～4 详细追踪

| ID | 要求 | 实现/交付物 | 测试或证据 | 状态 |
|---|---|---|---|---|
| V3-S3-01 | baseline/candidate 共用 executor | `executors/assembly.py` | common runner tests | ACCEPTED |
| V3-S3-02 | attempt-local publish/work/cache | `executors/nextflow.py`, `workflow/main.nf` | Nextflow argv/layout tests | ACCEPTED |
| V3-S3-03 | 六件套参数 round-trip | `executors/hifiasm_contract.py` | boundary/illegal-token tests | ACCEPTED |
| V3-S3-04 | 同源 post-QC contract | `PostQcContract`, `ASSEMBLY_ATTEMPT` | baseline/candidate equality test | ACCEPTED |
| V3-S3-05 | inventory、marker、deep verify | `executors/assembly.py`, `verifier.py` | missing/tamper/deep tests | ACCEPTED |
| V3-S3-06 | interruption 与 retry 分离 | `AssemblyExecutor` | same-attempt/new-attempt tests | ACCEPTED |
| V3-S3-07 | 删除旧执行/reader/adapter | source tree、CLI、workflow | production surface scan | ACCEPTED |
| V3-S4-01 | typed incumbent context/hash | `decision/models.py`, `decision/context.py` | round-2/immutability tests | ACCEPTED |
| V3-S4-02 | unified proposal provider | `decision/service.py` | three-mode/fallback tests | ACCEPTED |
| V3-S4-03 | governed RAG 和 prompt quarantine | `decision/retrieval.py` | allowlist/version/date/injection tests | ACCEPTED |
| V3-S4-04 | structured LLM receipt/budget | `decision/client.py`, `decision/service.py` | redaction/failure/resume tests | ACCEPTED |
| V3-S4-05 | single-parameter Safety Arbiter | `decision/service.py` | type/range/source/metric/direction/path/budget tests | ACCEPTED |
| V3-S4-06 | incumbent overlay/global fingerprint | `AssemblyConfig`, `ApprovedProposal` | different-incumbent test | ACCEPTED |
| V3-S4-07 | raw/rejected/approved lineage | `04_decisions/round_NN` artifacts | immutable lineage tests | ACCEPTED |

## 阶段 5～7 详细追踪

| ID | 要求 | 实现/交付物 | 测试或证据 | 状态 |
|---|---|---|---|---|
| V3-S5-01 | 唯一 coordinator 自动到终态 | `RunCoordinator.run/_advance` | public coordinator scenario matrix | ACCEPTED |
| V3-S5-02 | round 1～3/current incumbent | context、comparison、round manifest、state | three-round incumbent-chain test | ACCEPTED |
| V3-S5-03 | candidate cap/plateau/enabled/max rounds | runtime policy + safety/comparator | direct accept、plateau、zero/max-round tests | ACCEPTED |
| V3-S5-04 | unique winner/Pareto/hard regression | `RoundComparator` | two-candidate + direct comparator tests | ACCEPTED |
| V3-S5-05 | budget/contract/all-failed stops | controller + common executor | budget-before-round2、contract、failure tests | ACCEPTED |
| V3-S5-06 | rule STOP/required LLM/global dedup | rules + proposal service | no-call、exit 5、round3 duplicate tests | ACCEPTED |
| V3-S6-01 | 全终态自动报告 | `ReportService` | accepted/plateau/budget/human/failed tests | ACCEPTED |
| V3-S6-02 | incumbent 与 proposal 演化 | `FinalSummary`/Markdown | selected/state/comparison consistency | ACCEPTED |
| V3-S6-03 | 四层参数契约展示 | requested/approved/rendered/realized | JSON/TSV/Markdown consistency test | ACCEPTED |
| V3-S6-04 | LLM 与预算事实 | LLM activity + reserved/committed/remaining | timeout/fallback/report tests | ACCEPTED |
| V3-S6-05 | deep verifier/回填 | `verify_run`, `verification_report.json` | artifact/report tamper tests | ACCEPTED |
| V3-S7-01 | expensive-step fault hooks | coordinator pre/post hooks | hook coverage assertion | ACCEPTED |
| V3-S7-02 | attempt/cache resume 幂等 | executor/Nextflow/budget | round2 SIGTERM + cache present/missing | ACCEPTED |
| V3-S7-03 | partial/corrupt evidence 闭锁 | inventory/marker/verifier | truncation/corruption tests | ACCEPTED |
| V3-S7-04 | 并发/磁盘边界 | run lock + disk reservation | live writer + disk floor tests | ACCEPTED |
| V3-S7-05 | state/event/ledger tamper | state store/budget/verifier | fail-closed destructive tests | ACCEPTED |
| V3-S7-06 | LLM timeout/duplicate response | proposal service | required/optional/duplicate tests | ACCEPTED |
| V3-S7-07 | 报告恢复/幂等 | terminal report recovery | missing report + repeated generation | ACCEPTED |

## 阶段 8 详细追踪

| ID | 要求 | 实现/交付物 | 测试或证据 | 状态 |
|---|---|---|---|---|
| V3-S8-01 | executable fixture toolchain | `tests/fixtures/toolchain/fixture_tool.py` | explicit executable overrides + preflight | ACCEPTED |
| V3-S8-02 | 真实 CLI/文件边界三轮 | `scripts/run_portable_demo.py` | baseline + round 1/2/3、deep verify | ACCEPTED |
| V3-S8-03 | recorded LLM receipt replay | `RecordedLLMClient` + transcript fixture | 3 SUCCESS receipts、round/prompt/output hash | ACCEPTED |
| V3-S8-04 | subprocess/退出码/报告 | stage-8 portable E2E tests | exit 0/3/4/5 与 summary 一致 | ACCEPTED |
| V3-S8-05 | controller 模块边界 | controller/rounds/terminal/support/models | 1481→824 行；阶段 5～8 回归 | ACCEPTED |
| V3-S8-06 | Ruff/mypy/coverage | `pyproject.toml` + quality gates | overall >=85%、core branch >=90% | ACCEPTED |
| V3-S8-07 | 用户文档 | quickstart/modes/resume/budgets/results | 链接与示例审查 | ACCEPTED |
| V3-S8-08 | README 命令自动执行 | README portable entrypoint | exact command assertion + subprocess | ACCEPTED |
| V3-S8-09 | architecture/ADR/changelog | architecture + ADR-003/004 + changelog | 文档审查 | ACCEPTED |
| V3-S8-10 | advanced/deprecated CLI | CLI help + README | help subprocess；无 V2 commands/aliases | ACCEPTED |

## 阶段 9 详细追踪

| ID | 要求 | 实现/交付物 | 测试或证据 | 状态 |
|---|---|---|---|---|
| V3-S9-01 | 冻结真实 PacBio HiFi 样本 | `benchmark/datasets.yaml` | registry model + 34.9 GB SHA-256 复核 | IMPLEMENTED |
| V3-S9-02 | 外部 artifact root | `input_root_env` 安全路径契约 | 缺失变量、绝对路径、越界负向测试 | IMPLEMENTED |
| V3-S9-03 | 来源/授权/物种/大小/指纹 | `AcceptanceDataset` | registry governance test | IMPLEMENTED |
| V3-S9-04 | 当前 commit baseline | Drosophila real config + public coordinator | run2 baseline 科学 PASS，但不满足 clean commit 发布绑定 | RUN2_RELEASE_BLOCKED |
| V3-S9-05 | 单变量 candidate/同源 QC | `minimum_candidate_runs` + strict verifier | run2 `purge_level 3→2`，同源 QC 完整 | PASS_RUN2 |
| V3-S9-06 | comparator 科学结论 | `verify-real` | `KEEP_INCUMBENT / NO_PROTECTED_MATERIAL_IMPROVEMENT` | PASS_RUN2 |
| V3-S9-07 | 实际 argv/contract | attempt 六件套 + `verify-real` | 两套 contract、deep verifier、real verifier PASS | PASS_RUN2 |
| V3-S9-08 | live hybrid LLM smoke | `live-smoke`，真实 context/RAG/Schema/arbiter | 披露授权已取得；等待 clean-commit run3 context | AUTHORIZED_PENDING_RUN3 |
| V3-S9-09 | 0 failed/0 skipped real suite | `tests/integration/test_real_acceptance.py` | 3 tests 已选中，因无成功 live manifest 未执行 | BLOCKED_LIVE_SMOKE |
| V3-S9-10 | release evidence bundle | `build-evidence` | builder 按预期拒绝 dirty worktree | FAIL_RERUN_CLEAN_COMMIT |

阶段证据见 `stage0_acceptance.md`、`stage1_acceptance.md`、`stage2_acceptance.md`、
`stage3_stage4_acceptance.md`、`stage5_stage7_acceptance.md`、`recovery_matrix.md`、
`benchmark/reports/v3_stage0_stage4_acceptance.json` 和
`benchmark/reports/v3_stage5_stage7_acceptance.json`、`stage8_acceptance.md`、
`benchmark/reports/v3_stage8_acceptance.json`、`stage9_acceptance.md` 和
`stage9_run1_failure_analysis.md` 和 `stage9_run2_assessment.md`。

## 变更规则

每个需求状态改为 `ACCEPTED` 前，必须同时满足：代码存在、负向测试存在、阶段验收命令通过、
验收报告记录 commit/worktree 状态。未来阶段不得通过新建另一套生产 state 或 executor 绕过本矩阵。
