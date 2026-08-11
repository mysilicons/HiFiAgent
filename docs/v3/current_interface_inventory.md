# V3 当前接口、状态和删除清单

> 更新日期：2026-08-10
> 范围：阶段 0～8 完成后的原生 V3 source tree

## 公开 CLI

| 命令 | 权限 | 当前边界 |
|---|---|---|
| `validate` | 写 `00_metadata` validation artifacts | 原生 V3 schema/input |
| `plan` | 只读 | config、预算、environment preflight |
| `assemble` | 单写者 | pre-QC → baseline → 最多三轮候选/比较 → 报告/验证 → `TERMINAL` |
| `verify-run` | 只读 | identity/state/journal/budget/history/report；`--deep` 重哈希 attempt/QC/参数契约 |

不存在旧命令 alias、reader、migration、report/export 或独立 candidate 命令。

## 唯一生产状态

- `05_agent/run_state.json`：唯一 lifecycle snapshot；
- `05_agent/event_trace.jsonl`：append-only transaction journal；
- `05_agent/budget_ledger.jsonl`：append-only unified budget；
- `05_agent/history_manifest.jsonl`：attempt/round manifest hash chain；
- `05_agent/run.lock`：单写者租约。

## 核心 typed contracts

- `SampleConfig`、`EffectiveRuntimeConfig`、`RunIdentity`、`RunState`；
- `AssemblyParameters`、`AssemblyConfig`、`AssemblyAttemptRecord`；
- `ArtifactInventory`、`CompletionMarker`、`PostQcContract`；
- `QcFeatureBundle`、`DecisionContext`、`ProposalDirective`；
- `RawProposal`、`RejectedProposal`、`ApprovedProposal`、`ProposalDecision`；
- `LLMCallReceipt`、`RetrievalTrace`；
- `RecordedLLMTranscript`、`RecordedLLMResponse`；
- `BaselineReview`、`RoundComparison`、`FinalSummary`、`VerificationReport`。

## 生产组件

- controller：`RunCoordinator`；
- scientific round service：`CoordinatorRounds`（没有独立 run loop/state）；
- terminal service：`CoordinatorTerminal`；
- assembly port：`AssemblyExecutor`；
- workflow runner：`NextflowAssemblyRunner`；
- proposal provider：`ProposalService`；
- governed retrieval：`LocalGovernedRetriever`；
- structured provider：`StructuredLLMClient`；离线审计：`RecordedLLMClient`；
- verifier：`verify_run`；
- comparator：`RoundComparator`；
- terminal report：`ReportService`。

## 已删除的旧实现

`agent`、`benchmarking`、`optimization`、`rag`、`reporting`、`rules` 旧 package，旧
`CandidateExecutor`、旧 controller/state/history、旧 integration/portable tests、旧 Phase 6 脚本、
独立 `POST_QC_ONLY` 和 bin-reuse workflow entry 均已从 source tree 删除。

## 后续边界

阶段 8 的 executable fixture CLI E2E 与 recorded replay 已验收。阶段 9 的真实数据/live LLM 和
阶段 10 的发布资产不在阶段 0～8 范围中。后续只能扩展上述单一 V3 控制面，不得恢复被删除的
第二套状态或入口。
