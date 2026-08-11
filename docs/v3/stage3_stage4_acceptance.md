# V3 阶段 3～4 严格验收报告

- 验收日期：2026-08-10
- 包版本：`3.0.0`
- 验收 worktree：`DIRTY`（阶段 0～4 的实现尚未提交）
- 阶段 3 结论：`ACCEPTED`
- 阶段 4 结论：`ACCEPTED`
- 发布结论：`NOT ASSESSED`（阶段 5～10 不属于本次范围）

## 操作方修订

本次实现以“不兼容 V2”为高优先级修订。生产 source tree、CLI 和 Nextflow workflow 不包含旧
controller、reader、migration、report/export、独立 candidate executor、独立 post-QC 或 bin-reuse
兼容入口。旧 schema/字段只允许出现在负向测试中，用于证明 V3 fail closed。

## 阶段 3 验收矩阵

| 要求 | 实现证据 | 负向/恢复验收 | 结论 |
|---|---|---|---|
| baseline/candidate 共用 executor | `AssemblyExecutor` + `AssemblyWorkflowRunner` | baseline/candidate 同 runner | PASS |
| publish/work/cache attempt-local | `NextflowAssemblyRunner` 以 `workflow/` 为 cwd，显式 work/publish | cwd/work/publish 路径断言 | PASS |
| 六件套契约 | requested/approved/rendered/display/realized/check | None、bool、边界、重复、未知、shell/path token | PASS |
| 同源 post-QC | `PostQcContract` + `ASSEMBLY_ATTEMPT` | baseline/candidate contract byte-equivalent | PASS |
| inventory/marker | 完成 inventory 最先冻结，marker 最后写；失败 partial inventory | marker 缺失、hash/mtime/bytes 漂移、deep verify | PASS |
| interruption/retry | interruption 保留同一 attempt reservation/cache；tool retry 新 attempt | attempt_001/002 不覆盖、预算幂等 | PASS |
| manifest 驱动发现 | state/manifest/inventory 提供 canonical 引用，QC 不猜平铺路径 | 篡改或缺失立即失败 | PASS |
| 并列 candidate 隔离 | `round_NN/candidate_NN/attempt_NNN` | 两候选目录无交叉发布 | PASS |
| 旧执行面删除 | 仅保留 pre-QC 默认 workflow 与 `ASSEMBLY_ATTEMPT` | 生产 surface 扫描 0 match | PASS |

阶段 3 专项包含 common executor、参数 parser、Nextflow 边界、公开 coordinator、深度验证和
post-QC parser 测试。完成 attempt 可独立离线复验；失败 attempt 有 partial inventory，但没有
`COMPLETED.json`，因此不具比较资格。

## 阶段 4 验收矩阵

| 要求 | 实现证据 | 负向/恢复验收 | 结论 |
|---|---|---|---|
| typed incumbent context | `DecisionContext` + immutable context/hash sidecar | round 2 禁止回退 baseline | PASS |
| typed `propose_run` | `ProposalService` 不读取固定 run path | resume control/context drift 拒绝 | PASS |
| 统一 rule directive | `ProposalDirective` + `rule_directive.json` + hash | STOP 不检索、不调用 LLM | PASS |
| governed RAG | allowlist、scope、版本、review date、parameter authority、chunk hash | stale/expired/mismatch/injection 全量过滤 | PASS |
| 结构化 LLM | 单 provider protocol、JSON object、脱敏 prompt、无 secret persistence | HTTP/shape/schema 失败 fail closed | PASS |
| LLM ledger | 调用前 reserve，成功/失败均 commit，resume 返回 immutable decision | 同 round 仅一次调用 | PASS |
| Safety Arbiter | 白名单、严格类型/范围、单参数、source、metric、方向、风险、预算、预渲染 | 未授权/未知/多参数/path/shell/方向/预算拒绝 | PASS |
| incumbent overlay | diff overlay 当前完整 config，保存 incumbent hash 和新 fingerprint | 同 diff/不同 incumbent 得到不同完整配置 | PASS |
| proposal lineage | raw/rejected/approved + context/directive/retrieval/receipt hashes | control drift 和文件重复写拒绝 | PASS |
| 无直接执行路径 | proposal service 只返回 typed approved config | LLM/provider 不持有 executor port | PASS |

## 实际门禁结果

| 命令 | 结果 |
|---|---|
| `ruff check .` | PASS |
| `ruff format --check .` | PASS，61 files |
| `mypy` | PASS，61 source files |
| `pytest --cov --cov-report=term-missing --cov-fail-under=85` | PASS，149 passed，88.34% |
| 阶段 3～4 core branch gate（`--cov-branch --cov-fail-under=90`） | PASS，57 passed，93.33% |
| `nextflow config workflow` | PASS，V3 manifest/config 可解析 |
| `nextflow lint -output concise workflow` | PASS，6 files，0 error，0 warning |
| Nextflow DSL2 portable execution | PASS，`FIRST_STEP`/`SECOND_STEP` 2/2 processes |
| `hifi-agent plan examples/candida_sample_config.yaml` | PASS，environment WARNING 可审计，且 0 run artifacts |
| V3 workflow/executor/post-QC portable gate | PASS，41 passed |
| production surface 旧入口扫描 | PASS，0 match |

core branch gate 覆盖 `executors/assembly.py`、`executors/hifiasm_contract.py`、整个
`decision` package 和 `qc/features.py`。总体覆盖率门禁没有降级。

## 阶段边界

公开 `assemble` 已使用唯一 `RunCoordinator` 完成 pre-QC、baseline、同源 post-QC 和 typed QC，
并诚实停在 `BASELINE_REVIEW`。候选多轮执行、比较、终态报告属于阶段 5～6，本报告不将它们声明
为已完成，也不以 fixture 冒充阶段 9 的真实生物数据发布验收。
