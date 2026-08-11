# V3 阶段 5～7 严格验收报告

> 验收日期：2026-08-10
> 基线 commit：`1786dcd3cd5b8ecae20b767a5a0c7328656bac6a`
> 验收 worktree：`DIRTY`（阶段 0～7 原生 V3 重构尚未提交）

## 结论

| 阶段 | 结论 | 核心出口 |
|---|---|---|
| 阶段 5：统一控制器/三轮闭环 | ACCEPTED | 公开 `assemble` 的 `RunCoordinator` 自动推进到报告终态 |
| 阶段 6：自动报告/verifier | ACCEPTED | 六个 canonical report 自动生成，deep verifier 回填且一致 |
| 阶段 7：恢复/并发/破坏性测试 | ACCEPTED | 不重跑、不重复计费、不覆盖、不安全猜测 |

本轮没有恢复 V2 兼容层。生产 source tree 中不存在 V2 controller、schema、reader、migration、
exporter、旧 optimization loop 或旧 CLI 命令；旧版本仅保留为历史任务书/文档。

## 阶段 5 portable 验收矩阵

| 任务书场景 | 终态/关键断言 | 结果 |
|---|---|---|
| baseline 直接接受 | `ACCEPTED_BASELINE`，仅一次 assembly | PASS |
| baseline 规则 STOP | production rule `STOP_RULE_DECISION`；0 retrieval、0 LLM | PASS |
| round 1 candidate 改善 | candidate 成为 incumbent，`STOP_MAX_ROUNDS` | PASS |
| round 1 改善、round 2 plateau | round 2 `KEEP_INCUMBENT`，`STOP_PLATEAU` | PASS |
| round 1/2/3 连续改善 | 四节点 incumbent chain，`STOP_MAX_ROUNDS` | PASS |
| 两 candidate 唯一胜者 | 唯一 protected improvement 被选中 | PASS |
| Pareto 冲突 | 不以 N50 覆盖正确性，`STOP_HUMAN_REVIEW`/exit 3 | PASS |
| 所有 candidate 失败 | 每个失败 attempt 保留，`FAILED_TOOL`/exit 4 | PASS |
| 参数契约违规 | ineligible，`FAILED_PARAMETER_CONTRACT`/exit 4 | PASS |
| round 2 前预算耗尽 | candidate 未启动，`STOP_BUDGET`/exit 3 | PASS |
| round 2 中断/resume | 同 attempt/cache，assembly committed=3 而非 4 | PASS |
| round 3 前全部 fingerprint 重复 | 0 round-3 attempt，`STOP_NO_LEGAL_CANDIDATE` | PASS |

额外验收覆盖 optimization disabled、`max_rounds=0`、candidate retry、confirmation gate、
required/optional LLM timeout、missing required evidence、hard/material regression、target-one 和唯一
Pareto dominant candidate。round 2 context 明确引用 round 1 incumbent，不回退 baseline。

## 阶段 6 报告验收

每个终态由 manifest/control artifacts 生成：

- `06_report/final_report.md`；
- `06_report/final_summary.json`；
- `06_report/all_runs.tsv`；
- `06_report/all_parameters.tsv`；
- `06_report/provenance.tsv`；
- `06_report/verification_report.json`。

`FinalSummary` 同时记录 `terminal_outcome`、`outcome_class`、`process_exit_code`、selected/baseline、
完整 incumbent chain、全部 attempt、approved/rejected/未执行 proposal、LLM activity、预算 limit/
reserved/committed/remaining 和 verification status。参数 TSV/Markdown 展示 requested、approved、
rendered argv、realized 四层事实。deep verifier 重新检查 identity/state/event/budget/history、artifact
inventory、marker、参数契约、QC source hash、incumbent chain 和 Markdown/JSON/TSV 一致性。

验收终态覆盖 accepted、plateau、budget、human review、tool/contract/integrity failure 和 required LLM
failure。删除报告可由显式 resume 补齐；修改报告或关键 artifact 时只读 verifier 明确 FAIL。

## 阶段 7 恢复与破坏性验收

完整矩阵见 [recovery_matrix.md](recovery_matrix.md)。主要出口：

- 所有昂贵边界均有 before/after fault hook；
- round 2 执行中断恢复同一 attempt，Nextflow cache 缺失时明确失败；
- controller 在 candidate final manifest 后退出，resume 不调用 runner、不重复计费；
- 部分 post-QC、截断 inventory、缺失/损坏 marker 均不能误标成功；
- live writer lock 阻止第二个 `assemble`；stale takeover 必须显式；
- 磁盘保留线在 launch 前执行；同 attempt 恢复允许自然变化的磁盘观测但复用首次证据；
- state/event/ledger/history/报告/assembly artifact 篡改 fail closed；
- optional LLM timeout 使用规则 fallback，required timeout 退出 5；重复 provider config 仅执行一次；
- 科学成功后的内部 deep verification FAIL 会覆盖为 `FAILED_STATE_INTEGRITY`。

## 验收中发现并修复的问题

1. 中断恢复的 disk reservation 曾要求 `observed_free_gib` 字节级相等；磁盘自然波动导致同 attempt
   被误判为 reservation 冲突。现以同 reservation ID、resource 和 estimate 幂等复用首次观测。
2. comparator 曾只对 `comparison_eligible=true` 的候选检查 missing required metrics；而缺失证据会先
   令候选 ineligible，形成不可达判断。现任何候选缺少必需证据均安全停止为
   `INSUFFICIENT_EVIDENCE`。
3. pre-terminal 报告时间戳会随 TERMINAL transition 变化。现终态后再次从稳定 terminal event
   物化报告，并支持缺失报告恢复，重复生成字节一致。
4. standalone raw proposal、LLM receipt/provider response 原先未全部进入 history checksum 图。现由
   `RoundRecord` 显式引用，任一 lineage 文件篡改都会令 `MANIFEST_HISTORY` 失败。

## 实际质量门禁

| 命令 | 结果 |
|---|---|
| `ruff check .` | PASS |
| `ruff format --check .` | PASS，67 files |
| `mypy` | PASS，67 source/test files |
| `pytest -q` | PASS，172 passed，0 failed，0 skipped |
| `pytest --cov --cov-report=term --cov-fail-under=85 -q` | PASS，172 passed，89.58% |
| 阶段 5～7 core branch gate | PASS，172 passed，90.42% |
| `pytest tests/workflow -ra` | PASS，5 passed |
| `nextflow config workflow` | PASS |
| `nextflow lint -output concise workflow` | PASS，6 files，0 error，0 warning |
| production source V2 扫描 | PASS，无 V2 production implementation |

core branch gate 覆盖 `orchestration/controller.py`、`orchestration/comparison.py`、
`orchestration/verifier.py`、`reporting` package 和 `decision/rules.py`。

## 阶段边界

本报告只接受阶段 5～7。阶段 8 的 executable fixture CLI subprocess、阶段 9 的当前 commit 真实
数据 suite 和阶段 10 的 tag/wheel/release 证据尚未执行，不能由本轮 portable runner 结果推导为完成。
