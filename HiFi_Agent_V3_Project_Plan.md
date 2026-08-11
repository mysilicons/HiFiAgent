# HiFi Agent V3 项目计划书与任务书

> **项目定位**：将现有 V2 分阶段组件整合为一个可恢复、可审计、真实可重放的单命令 HiFi 组装优化系统
> **文档版本**：V3.0-draft
> **编制日期**：2026-08-10
> **代码基线**：`main@1786dcd3cd5b8ecae20b767a5a0c7328656bac6a`，包版本 `2.0.0`
> **输入基线**：`HiFi_Agent_V1_Project_Plan.md`、`HiFi_Agent_V2_Project_Plan.md`、`HiFi_Agent_V1_V2_Compliance_Assessment.md`
> **目标版本**：HiFi Agent `3.0.0`
> **核心原则**：整合优先于重写、一个生产入口、一个权威状态、证据优先、LLM 不越权、执行参数可证明、历史不可覆盖、真实验收可重放
> **实施修订（2026-08-10）**：操作方明确要求不兼容 V2。本文中所有兼容读取、迁移器、旧 CLI
> 保留期和 exporter 要求均被本修订取代；V3 只接受、执行和写出原生 V3 契约。

---

## 1. 文档目的和规范用语

本任务书用于指导 V3 的设计、开发、测试、真实数据验收和发布。V3 不是继续堆叠独立 Stage，
而是消除当前“组件基本齐全、主流程没有闭合”的结构性问题。

本文使用以下规范用语：

- **必须**：V3 发布阻断要求；
- **应当**：正常情况下需要完成，偏离时必须有 ADR、理由和替代验收；
- **可以**：不影响 V3 发布判定的可选实现；
- **生产路径**：用户通过 `hifi-agent assemble` 启动的真实执行路径；
- **portable 验收**：不依赖大型真实生物数据或付费 API 的确定性测试；
- **真实验收**：使用真实 PacBio HiFi reads、真实工具链和真实文件产物的发布门禁；
- **完成**：代码、测试、文档和可核验证据同时满足，不以模型、fixture 或历史自述代替。

---

## 2. 当前代码现状和问题分析

### 2.1 已有能力

V3 必须复用当前已经验证的能力，不应重新实现一套平行组件：

- 输入 Schema、FASTQ/FASTQ.GZ 校验、checksum 和 resolved config；
- SeqKit、NanoPlot、meryl、GenomeScope 组装前 QC；
- hifiasm baseline、GFA/FASTA/bin 和 Nextflow resume；
- QUAST、BUSCO、Merqury、mapping 和 coverage 组装后 QC；
- 14 条版本化规则、确定性安全停止和参数白名单；
- `QcFeatureBundle`、来源 hash、confidence 和 limitation；
- 受治理的 RAG 索引、typed LLM proposal 和 Safety Arbiter；
- hifiasm 参数双向命令契约和 `None` 省略；
- `CandidateExecutor` 的 attempt 隔离、失败保留和同源 post-QC；
- `RoundComparator` 的硬回退、Pareto、实质改善和平台期逻辑；
- `OptimizationLoop` 的最多三轮、去重、恢复和预算基础；
- V1/V2 Markdown、JSON、TSV 报告器；
- 当前 portable 测试、Ruff、mypy 和 coverage 门禁。

### 2.2 当前质量基线

V3 开发开始前，以以下实测结果作为不可退化基线：

| 项目 | 当前结果 | V3 要求 |
|---|---:|---|
| Python 测试 | `354 passed, 17 skipped` | portable 测试不得退化；真实测试必须恢复 |
| 覆盖率 | `87.14%` | 总覆盖率保持 `>=85%`，V3 核心模块分支覆盖另设门禁 |
| Ruff | 通过 | 持续通过 |
| mypy strict | 通过，119 个源文件 | 持续通过 |
| workflow tests | `7 passed` | 持续通过并增加 V3 attempt/resume 场景 |
| portable demo | 5/5 | 保留，但不得充当生物学验收 |
| 显式真实 integration | `14 failed, 2 skipped` | V3 RC 前选定 suite 必须 0 failed、0 skipped |

### 2.3 问题登记表

| ID | 等级 | 当前问题 | 根因 | V3 处理方向 |
|---|---:|---|---|---|
| V3-P0-01 | P0 | `assemble` 只完成 baseline 和至多一个第一轮规则候选，随后以 `CANDIDATE_EXECUTED_STAGE3` 结束 | Stage 3 控制器从未接入后续组件 | 用唯一生产控制器串联提议、执行、比较、incumbent、round 2/3 和报告 |
| V3-P0-02 | P0 | `AssemblyController`、legacy Agent 和独立 `OptimizationLoop` 各自持有部分生命周期 | 分阶段开发形成多套状态和适配器 | 建立一个权威 run state；现有 loop 降为受控制器调用的领域服务 |
| V3-P0-03 | P0 | 当前真实验收依赖已缺失的 Candida baseline/checksum，显式 suite 失败 | 测试硬编码 ignored 工作区产物，发布证据未形成可移植清单 | 建立 manifest 驱动的外部真实数据集和 release evidence bundle |
| V3-P0-04 | P0 | 三轮只由 `ScriptedProvider`/`ScriptedRunner` 证明 | loop 没有生产调用点 | 用真实生产适配器完成 portable 三轮和至少一条真实 candidate 路径 |
| V3-P1-01 | P1 | `OptimizationConfig` 只校验，不驱动 `assemble` | CLI/controller 没有消费配置 | 明确配置来源和优先级，输出 effective config receipt |
| V3-P1-02 | P1 | 主控制器 candidate 仍发布到 V1 平铺目录，attempt 目录只保存引用 | 主控制器绕过 `CandidateExecutor` | baseline/candidate 统一通过同一隔离执行契约 |
| V3-P1-03 | P1 | 预算仅局部覆盖 CPU、walltime 和候选数 | 没有 run 级原子 ledger | 统一 assemblies、retries、CPU、walltime、disk、LLM calls 预算 |
| V3-P1-04 | P1 | loop trace 通过重写 JSONL 保存，state/event 存在 crash window | 持久化没有事务恢复协议 | 使用 sequence、transaction ID、pending journal 和恢复对账 |
| V3-P1-05 | P1 | `assemble` 不自动生成完整 V2 报告 | 报告器仍是手工分阶段入口 | 所有终态自动生成成功或失败报告 |
| V3-P1-06 | P1 | baseline 没有 candidate 同等级的六份命令契约 | baseline 使用旧执行路径 | baseline 和 candidate 共用 `AssemblyExecutor` |
| V3-P1-07 | P1 | 当前 conda 环境实际 Java 25，Nextflow 要求 JDK 21；工具存在宿主绝对路径 fallback | 声明环境与实际解析环境漂移 | 环境锁定、preflight、实际工具 manifest、禁止隐藏 fallback |
| V3-P1-08 | P1 | README 配置含未知字段，示例路径/大小写错误 | 文档未进入自动测试 | 文档示例作为 CI fixture 执行 |
| V3-P2-01 | P2 | `INPUT_NOT_HIFI_STOP` 规则读取的是固定 `pacbio_hifi` | FASTQ 本身不能可靠推断测序技术 | 改为必填用户声明并标记 `USER_DECLARED_NOT_INFERRED` |
| V3-P2-02 | P2 | V1/V2 输出目录和 schema version 混用 | 兼容路径缺少明确主从关系 | 定义 V3 canonical tree 和只读兼容视图 |
| V3-P2-03 | P2 | 多个高级 CLI 可写同一 run，可能绕过控制器 | 缺少 run lock 和命令所有权 | 活跃 V3 run 只允许控制器写入；其他命令只读或显式独立输出 |

### 2.4 核心根因

当前问题不是缺少单个算法，而是缺少统一所有权：

```text
当前：
assemble(Stage 3) ─┐
propose             ├─ 各自读写部分状态和目录
execute-candidate   ┤
OptimizationLoop  ──┤
report-v2         ──┘

V3：
assemble → RunCoordinator → 统一状态、预算、attempt、事件和报告
                         ├→ Rule/RAG/LLM Proposal Service
                         ├→ AssemblyExecutor
                         ├→ PostQc Service
                         └→ RoundComparator
```

V3 的首要工程目标是建立这一条主链，而不是新增更多旁路入口。

---

## 3. V3 总体目标

### 3.1 总体目标

V3 必须让用户通过一条命令完成以下受控流程：

```bash
hifi-agent assemble sample.yaml --decision-mode rules_only --resume
```

完整流程为：

```text
输入与环境验证
  → pre-QC 与证据可信度
  → baseline 参数契约
  → baseline 组装与统一 post-QC
  → 规则判定
  → 当前 incumbent 的 RAG/LLM/规则候选提议
  → 确定性安全审批
  → 原子预算预留
  → 隔离 candidate attempt 执行
  → 同源 post-QC 与参数契约复核
  → 多指标比较
  → incumbent 更新 / 平台期停止 / 风险停止
  → 最多三轮
  → 自动生成最终报告和完整 provenance
```

### 3.2 功能成功标准

1. `assemble` 是唯一推荐的生产编排入口；
2. `SampleConfig.optimization` 的全部字段真正控制执行；
3. baseline 后最多三轮，每轮默认 1、最多 2 个候选；
4. round 2/3 的候选基于当前 incumbent，而不是固定 baseline；
5. `rules_only`、`hybrid`、`llm_disabled` 均在主命令中可运行和审计；
6. baseline 和 candidate 使用相同命令契约、隔离、post-QC 和 inventory 标准；
7. 每个 candidate 在启动前完成安全审批、参数指纹去重和预算预留；
8. 每轮比较可以接受唯一候选、保留 incumbent 或安全停止；
9. 任意中断点 `--resume` 不重复已完成昂贵任务、不重复计费、不覆盖历史；
10. 任意合法或失败终态都会自动生成 Markdown/JSON/TSV 报告；
11. 用户可以从报告追溯到配置、批准参数、实际 argv、指标源文件和 checksum；
12. `verify-run` 可以离线验证 V3 run 的结构、hash、状态和选择链。

### 3.3 科学成功标准

1. 不按 N50 单指标选择；
2. BUSCO、k-mer、mapping、coverage 和适用时的结构错误硬回退不可被覆盖；
3. 同源 reads Merqury 明确标记为 advisory；
4. genome size 不可信时，size ratio 不得作为硬判断；
5. reference-free 和 reference-based 指标严格分支；
6. 比较双方必须使用同一 QC 协议和可兼容工具版本；
7. 缺失核心指标时不做虚假优选，进入证据不足或人工复核；
8. V3 初始发布每个候选默认只改变一个白名单参数，确保可归因性；
9. 报告只能声称“当前约束和预算下证据支持最高”，不得声称全局最优；
10. V3 发布不要求候选一定优于 baseline，但要求正确接受、拒绝或停止。

### 3.4 工程和发布成功标准

1. portable 测试、Ruff、format、mypy strict 和 coverage 全部通过；
2. V3 核心控制器、状态恢复、预算和命令契约分支覆盖率 `>=90%`；
3. fixture 通过生产控制器完成 round 1/2/3 和 round 2 中断恢复；
4. 至少一个真实样本在当前 release commit 完成 baseline 和一个 candidate；
5. 选定的真实验收 suite 为 0 failed、0 skipped；
6. clean clone 可以按文档完成 portable quickstart；
7. 声明环境与实际工具版本一致，`conda run -n hifiAgent nextflow -version` 直接成功；
8. release tag、wheel、源码、验收 manifest 和 checksum 指向同一 commit；
9. 发布前工作树干净；
10. 历史 V1/V2 结果不会被 V3 原地覆盖。

---

## 4. V3 范围和非目标

### 4.1 支持范围

- 单样本；
- 单个或多个 PacBio HiFi FASTQ/FASTQ.GZ；
- 以 hifiasm 为唯一组装器；
- 单机或单一调度后端上的 Nextflow 执行；
- 真核基因组；
- 可选 expected genome size、reference genome、独立 k-mer reads；
- baseline 后 0～3 个优化轮次；
- 每轮 1～2 个候选，V3 默认 1 个；
- 当前四个白名单参数：`purge_level`、`purge_similarity`、`hom_cov`、`disable_post_join`；
- 规则模式和可选 hybrid LLM 模式；
- Linux x86_64 作为 V3 正式支持平台。

### 4.2 V3 明确不做

- 不新增第二种 assembler；
- 不扩大 hifiasm 参数白名单；
- 不做群体样本、批量调度或联合组装；
- 不做无界搜索、贝叶斯优化或强化学习；
- 不允许 LLM 直接执行 shell、修改路径、线程、预算或工具版本；
- 不自动推断 reads 一定是 HiFi；
- 不承诺候选必然优于 baseline；
- 不宣称获得全局最佳参数；
- 不在 V3 内实现 Web UI、云平台或多用户权限系统；
- 不把 portable demo 当作真实生物学验收；
- 不为兼容旧目录而继续维护第二套生产状态机。

### 4.3 非兼容策略（实施修订）

1. 只接受 `schema_id: "hifi-agent"` 和原生 V3 配置字段；
2. 不提供旧 run reader、迁移器、exporter 或旧命令别名；
3. 发现旧 schema、旧字段或已有非 V3 run 时 fail closed；
4. 历史产物只作为仓库外人工档案，不进入任何 V3 identity、incumbent 或报告事实链；
5. `hifi-agent plan` 保持只读，公开 CLI 只保留原生 V3 命令。

---

## 5. V3 核心设计原则

### 5.1 一个生产入口

所有正式自动执行都从 `hifi-agent assemble` 进入。高级命令可以用于调试和离线分析，但其
产物不能被主控制器静默采纳。

### 5.2 一个权威状态

一个 run 只能有一个权威 `RunState`。`OptimizationLoop` 不再独立维护与主控制器竞争的
生产 state；其比较和轮次算法应作为领域服务，由主控制器提交状态变化。

### 5.3 整合而非重写

V3 应复用：

- `rag.proposer` 的检索、LLM Schema 和 Safety Arbiter；
- `executors.candidate` 的 attempt 隔离和 contract；
- `optimization.rounds` 的比较策略；
- `optimization.loop` 中已验证的去重、平台期和轮次算法；
- `reporting.v2` 的报告数据收集和渲染；
- 当前 Nextflow workflow 和 parser。

允许重构接口和持久化职责，不允许复制为 `v3_*` 后长期保留两套逻辑。

### 5.4 事实、建议、批准和执行分离

```text
QC/工具产物 = 事实
规则/RAG/LLM = 建议
Safety Arbiter = 批准或拒绝
AssemblyExecutor = 只执行批准配置
RoundComparator = 选择或停止
RunCoordinator = 唯一生命周期所有者
```

任何层不得越过下一层的确定性约束。

### 5.5 默认失败安全

- 输入、环境、状态、checksum 或参数契约不一致时停止；
- 规则 STOP 不能被 LLM 覆盖；
- `require_llm=true` 时 LLM 不可用必须停止；
- 指标不适用不得当作 0；
- 无唯一科学结论时保留 incumbent 或进入人工复核；
- 失败 attempt 永不删除，且不得参加自动比较。

---

## 6. V3 目标架构

### 6.1 生产控制流

```text
CLI assemble
  │
  ▼
RunCoordinator
  ├── ConfigResolver + EnvironmentPreflight
  ├── RunStateStore + EventJournal + RunLock
  ├── BudgetLedger
  ├── PreQcService
  ├── AssemblyExecutor
  │     ├── baseline attempt
  │     └── candidate attempt
  ├── PostQcService
  ├── DecisionContextBuilder
  ├── ProposalService
  │     ├── RuleEngine
  │     ├── Governed RAG
  │     ├── optional LLM
  │     └── SafetyArbiter
  ├── RoundComparator
  ├── ReportService
  └── RunVerifier
```

### 6.2 现有组件到 V3 的映射

| 现有组件 | V3 处理 | 说明 |
|---|---|---|
| `orchestration.controller.AssemblyController` | 重构为完整 `RunCoordinator` 或被其替换 | 不保留 Stage 3 终态语义 |
| `optimization.loop.OptimizationLoop` | 提取轮次领域逻辑并由 coordinator 调用 | 不单独保存生产权威 state |
| `ExecutingAssemblyTools` | 拆成 typed service ports | 移除固定 round 1/max candidate 1 |
| `CandidateExecutor` | 升级为 baseline/candidate 通用 `AssemblyExecutor` | 统一六件套契约和 attempt 布局 |
| `propose_run` | 改为接收当前 `DecisionContext` | 不再固定读取 baseline 路径 |
| `RoundComparator` | 直接复用并补齐 provenance | 版本化 policy/hash |
| `render_v2_report` | 改为 coordinator 终态自动调用 | 支持失败/部分完成报告 |
| legacy Agent | 只读兼容或弃用 | 不再参与 V3 自动闭环 |

### 6.3 模块边界建议

```text
src/hifi_agent/
├── orchestration/
│   ├── controller.py        # 唯一生产 coordinator
│   ├── ports.py             # typed service protocols
│   ├── state.py             # V3 state + transition table
│   ├── journal.py           # transaction/event recovery
│   ├── lock.py              # single-writer lock
│   └── history.py           # identity, round, attempt index
├── execution/
│   ├── assembly.py          # baseline/candidate common executor
│   ├── budget.py            # run-level reservation ledger
│   └── environment.py       # tool resolution and preflight
├── optimization/
│   ├── context.py           # incumbent-aware decision context
│   ├── loop.py              # stateless/domain round transitions
│   ├── rounds.py            # comparator
│   └── policy.py
├── rag/
│   ├── proposer.py
│   └── safety.py
└── reporting/
    ├── v3.py
    └── verifier.py
```

实际文件名可以调整，但职责边界和单一所有权不得改变。

---

## 7. V3 CLI 和配置规格

### 7.1 主命令

```bash
hifi-agent assemble CONFIG \
  [--decision-mode rules_only|hybrid|llm_disabled] \
  [--resume] \
  [--confirm-medium-high-risk]
```

要求：

- `--decision-mode` 覆盖配置但必须写入 effective config 和事件；
- `--resume` 只恢复同一 `run_uuid`、同一配置 hash 和输入 checksum；
- 风险确认只授权已经通过 arbiter 的候选，不得放宽白名单或范围；
- CLI 不直接拼接 shell command；
- 未提供 `--resume` 且 state 已存在时拒绝启动；
- 活跃 run 已被其他进程持锁时拒绝第二写入者；
- 每次退出打印 terminal outcome、报告路径和 verify 命令。

### 7.2 辅助命令

```bash
hifi-agent plan CONFIG [--decision-mode ...]
hifi-agent verify-run RUN_DIR [--deep]
```

- `plan`：验证配置和环境，输出有效配置、预计最大 assembly 数和预算，不运行 hifiasm；
- `verify-run`：只读验证 schema、state/event sequence、manifest、checksum、contract、incumbent 链和报告引用；
- `verify-run --deep`：计算全部大文件 checksum；默认模式可以使用已冻结 inventory；

### 7.3 配置来源优先级

优先级从高到低：

1. 明确 CLI override；
2. V3 `optimization`/`execution_budget` 配置；
3. 版本化默认值。

必须生成：

```text
00_metadata/resolved_config.yaml
00_metadata/effective_config.json
00_metadata/config_sources.json
```

`config_sources.json` 对每个可执行字段标记 `cli | config | default`。任何旧字段或未知字段都必须
报错，不能映射或静默选择。

### 7.4 V3 配置示例

```yaml
schema_id: "hifi-agent"
sample_id: Candida_albicans
read_technology: pacbio_hifi
hifi_reads:
  - /absolute/path/to/Candida_albicans_HiFi.fastq
outdir: /absolute/path/to/results/Candida_albicans_v3

species_name: Candida albicans
expected_genome_size: 14500000
ploidy: 2
busco_lineage: saccharomycetes_odb12
reference_genome: null
kmer_reads: null

resources:
  max_threads: 64
  max_memory_gb: 256

optimization:
  enabled: true
  max_rounds: 3
  max_candidates_per_round: 1
  max_parameter_changes_per_candidate: 1
  plateau_rounds: 1
  decision_mode: rules_only
  require_llm: false
  confirm_risk_level: medium_high
  retain_all_attempts: true

execution_budget:
  max_total_assemblies: 4
  max_tool_retries: 1
  max_cpu_hours: 10000
  max_walltime_hours: 168
  min_free_disk_gib: 100
  max_llm_calls_per_round: 1
  max_total_llm_calls: 3
```

Schema 约束：

- `read_technology` 在 V3 必填且当前只能为 `pacbio_hifi`；
- receipt 必须说明它是用户声明，不是 FASTQ 自动推断；
- `max_rounds`: 0～3；
- `max_candidates_per_round`: 1～2；
- `max_parameter_changes_per_candidate`: V3 固定为 1；
- `max_total_assemblies`: 1～7，包含 baseline；
- `max_total_assemblies` 可以小于理论轮次上限，此时由预算提前停止；
- `retain_all_attempts` 只能为 `true`；
- `require_llm=true` 只允许 `decision_mode=hybrid`；
- 未知字段继续 `extra="forbid"`；
- 新增大小字段在字段名中明确使用 bytes/GiB；为兼容保留的 `*_gb` 字段必须在 Schema 中明确其实际换算口径。

### 7.5 决策模式语义

| 模式 | LLM | 规则候选 | RAG 审计 | 故障语义 |
|---|---:|---:|---:|---|
| `rules_only` | 不初始化 | 允许 | 可记录规则授权来源 | 不存在 LLM 降级概念 |
| `llm_disabled` | 明确禁止 | 允许 | 可检索但不得发给 LLM | 报告记录操作方禁用 |
| `hybrid` | 可调用 | 允许 | 必须 | `require_llm=false` 可记录后降级；`true` 时失败停止 |

LLM 不可改变规则 STOP、候选数、预算、参数白名单或风险确认要求。

### 7.6 CLI 退出语义

`final_summary.json` 必须包含 `outcome_class` 和 `process_exit_code`：

| exit code | 类别 | 示例 |
|---:|---|---|
| 0 | 正常科学终态 | accepted、plateau、max rounds、no legal candidate |
| 2 | 输入/配置错误 | invalid FASTQ、schema、checksum |
| 3 | 需要操作方处理 | human review、risk confirmation、budget extension |
| 4 | 执行或完整性失败 | tool failure、parameter contract、state corruption |
| 5 | 必需外部服务失败 | required LLM unavailable |

即使 exit code 非 0，只要 run identity 已创建，也必须尽最大可能生成失败报告。

---

## 8. V3 数据模型和状态规格

### 8.1 `RunIdentity`

至少包含：

```text
schema_id = 3.0
run_uuid
sample_id
run_dir
created_at
code_commit
package_version
config_sha256
effective_config_sha256
input_manifest_sha256
environment_manifest_sha256
comparison_policy_sha256
rag_index_sha256 | null
```

输入验证和环境 preflight 必须先生成稳定 snapshot，全部 hash 就绪后再原子创建 identity。preflight
之前的失败只生成 bootstrap failure receipt，不创建半成品 identity。身份创建后不可改变；resume 时
任一身份字段漂移必须停止并生成 drift receipt。

### 8.2 `RunState`

至少包含：

```text
run_identity
sequence
state
round_index
candidate_index
active_attempt_id
baseline_run_ref
incumbent_run_ref
seen_parameter_fingerprints
completed_round_refs
budget_snapshot_ref
latest_decision_ref
terminal_outcome
outcome_class
last_error
report_refs
```

状态只保存小型引用和控制事实，不复制大型 metrics 或 LLM payload。

### 8.3 状态机

```text
INITIALIZING
INPUT_VALIDATION
ENVIRONMENT_PREFLIGHT
PRE_QC
BASELINE_PLAN
BASELINE_ASSEMBLY
BASELINE_POST_QC
BASELINE_REVIEW
ROUND_CONTEXT
RAG_RETRIEVAL
LLM_PROPOSAL
SAFETY_REVIEW
BUDGET_RESERVATION
CANDIDATE_ASSEMBLY
CANDIDATE_POST_QC
ROUND_COMPARISON
INCUMBENT_UPDATE
REPORTING
VERIFYING
TERMINAL
```

规则模式可以产生 `LLM_PROPOSAL` 的显式 skipped event，但不得省略序列，以保证审计路径一致。

### 8.4 终态

正常科学终态：

- `ACCEPTED_BASELINE`；
- `ACCEPTED_INCUMBENT`；
- `STOP_PLATEAU`；
- `STOP_MAX_ROUNDS`；
- `STOP_METRIC_CONFLICT`；
- `STOP_INSUFFICIENT_EVIDENCE`；
- `STOP_NO_LEGAL_CANDIDATE`；
- `STOP_RULE_DECISION`。

需要操作方：

- `STOP_HUMAN_REVIEW`；
- `STOP_CONFIRMATION_REQUIRED`；
- `STOP_BUDGET`。

失败终态：

- `FAILED_INPUT`；
- `FAILED_ENVIRONMENT`；
- `FAILED_TOOL`；
- `FAILED_PARAMETER_CONTRACT`；
- `FAILED_STATE_INTEGRITY`；
- `FAILED_REQUIRED_LLM`。

不得继续使用 `CANDIDATE_EXECUTED_STAGE3` 作为终态。

### 8.5 `RoundRecord`

```text
round_id
round_index
incumbent_before_ref
decision_context_ref + sha256
rule_decision_ref
retrieval_trace_ref
proposal_decision_ref
approved_candidate_refs
rejected_candidate_refs
attempt_refs
comparison_ref
incumbent_after_ref
round_outcome
stop_reason_codes
created_at
completed_at
```

round 0 表示 baseline；round 1～3 表示优化轮次。完成记录不可覆盖，只能追加更正事件。

### 8.6 `AssemblyAttemptRecord`

至少包含：

- attempt 身份和父 round/candidate；
- `PLANNED | RUNNING | COMPLETED | FAILED | INTERRUPTED | CONTRACT_VIOLATION`；
- requested、approved、rendered、realized config 引用；
- command、工具版本、环境 hash；
- 开始/结束时间和真实资源消耗；
- assembly/post-QC artifacts inventory；
- 完成 marker；
- 错误和 retry parent；
- 是否有资格参加比较及原因。

### 8.7 `BudgetLedger`

使用 append-only entries：

```text
entry_id
sequence
timestamp
resource_type
action = RESERVE | COMMIT | RELEASE | ADJUST
amount
unit
round_id
attempt_id | llm_call_id
reason_code
balance_after
```

同一 attempt 的 reservation 必须幂等，resume 不得重复扣费。

---

## 9. 状态、事件和并发一致性

### 9.1 单写者锁

- run root 创建后立即获得文件锁；
- 锁记录 PID、host、started_at、run_uuid 和 command；
- 活锁拒绝第二写入者；
- 疑似 stale lock 只能通过显式恢复流程接管并记录事件；
- `verify-run` 只读，不需要写锁；
- 高级命令不得绕过活跃 V3 run 的锁。

### 9.2 持久化事务

状态和 JSONL 事件无法用一次文件 rename 同时提交，V3 必须实现可恢复协议：

1. 生成唯一 `transaction_id` 和下一 sequence；
2. 原子写 `pending/<transaction_id>.json` 并 fsync；
3. 原子替换 state snapshot；
4. 向 event journal 追加同 transaction/sequence 的事件并 fsync；
5. 删除 pending journal；
6. resume 时对 pending、state、event 三方进行幂等对账。

不允许继续通过每轮重写整份 JSONL 来模拟 append-only。

### 9.3 完整性规则

- sequence 必须从 1 单调连续；
- state sequence 不得落后于已提交 event；
- journal 中 transaction ID 不得重复；
- 完成 attempt 的 manifest 及 inventory 不得变化；
- final selected run 必须能沿 `incumbent_before/after` 链回溯到 baseline；
- 状态损坏时不得猜测恢复，进入 `FAILED_STATE_INTEGRITY`。

---

## 10. 统一执行器和参数契约

### 10.1 baseline 与 candidate 同权

V3 使用一个 `AssemblyExecutor` 接收：

```text
run_identity
round/candidate/attempt identity
approved full AssemblyConfig
input manifest
environment manifest
execution budget reservation
resume policy
```

baseline 只是 `round_00/baseline`，不能继续使用弱于 candidate 的执行契约。

### 10.2 每次 assembly 六件套

每个 baseline/candidate attempt 在执行前后必须生成：

```text
requested_config.json
approved_config.json
rendered_argv.json
hifiasm_command.txt
realized_parameters.json
parameter_contract_check.json
```

附加要求：

- `requested_config` 保存提议原貌；
- `approved_config` 是完整配置，不只是 diff；
- `rendered_argv` 是 token array，不是未经解析的 shell 字符串；
- `hifiasm_command.txt` 仅用于展示，执行不得通过 shell；
- `realized_parameters` 由实际保存 argv 反向解析；
- contract check 字段级比较 approved/rendered/realized；
- `None` 完全省略；
- bool flag 不接收数值 token；
- flag 不重复；
- 未知 token、路径、环境变量和 shell 元字符阻断执行；
- contract violation attempt 永久保留但无比较资格。

### 10.3 incumbent overlay

round 2/3 的候选必须以当前 incumbent 的完整 `AssemblyConfig` 为基准：

```text
candidate_full_config = overlay(incumbent_full_config, approved_single_parameter_diff)
```

必须保存：

- incumbent config hash；
- requested diff；
- approved diff；
- overlay 后完整 config；
- 新参数指纹。

禁止每轮重新从 baseline overlay，否则视为 P0 回归。

### 10.4 attempt 语义

- launch 前分配 `attempt_001` 并持久化预算 reservation；
- 进程中断且 work/cache 完整时，`--resume` 恢复同一 attempt；
- 工具确定失败且允许 retry 时创建 `attempt_002`；
- retry 不改变参数，参数改变必须是新 candidate；
- 完成 marker 最后写入；
- 没有完成 marker 的 attempt 不得参与比较；
- 任何 attempt 不允许 overwrite。

---

## 11. 输出目录和产物契约

### 11.1 V3 canonical tree

```text
results/<sample_id>_v3/
├── 00_metadata/
│   ├── run_identity.json
│   ├── resolved_config.yaml
│   ├── effective_config.json
│   ├── config_sources.json
│   ├── input_manifest.json
│   ├── input_checksums.tsv
│   ├── validation_receipt.json
│   ├── environment_manifest.json
│   └── preflight_receipt.json
├── 01_pre_qc/
│   ├── raw_metrics.json
│   ├── qc_feature_bundle.json
│   └── artifacts_manifest.json
├── 02_assembly/
│   ├── baseline/attempt_001/
│   │   ├── metadata/
│   │   ├── contract/
│   │   ├── workflow/
│   │   ├── assembly/
│   │   ├── post_qc/
│   │   ├── artifacts_manifest.json
│   │   └── COMPLETED.json
│   ├── round_01/candidate_01/attempt_001/
│   ├── round_02/candidate_01/attempt_001/
│   └── round_03/candidate_01/attempt_001/
├── 03_post_qc/
│   └── post_qc_index.json
├── 04_decisions/
│   ├── rounds/round_00/
│   ├── rounds/round_01/
│   ├── rounds/round_02/
│   ├── rounds/round_03/
│   └── comparison_policy_snapshot.yaml
├── 05_agent/
│   ├── run_state.json
│   ├── event_trace.jsonl
│   ├── pending/
│   ├── budget_ledger.jsonl
│   ├── history_manifest.json
│   └── run.lock
├── 06_report/
│   ├── final_report.md
│   ├── final_summary.json
│   ├── all_runs.tsv
│   ├── all_parameters.tsv
│   ├── provenance.tsv
│   ├── verification_report.json
│   └── report_assets/
└── logs/
```

### 11.2 目录规则

- attempt 是 assembly、contract、workflow 和 post-QC 的自包含审计单元；
- `03_post_qc/post_qc_index.json` 只保存 canonical attempt 路径和 hash，不复制大型结果；
- 报告和比较器通过 manifest 查找产物，不用字符串猜测平铺路径；
- 所有 JSON 有 `schema_id`；
- 所有 TSV 固定列顺序并有 UTF-8 header；
- 大文件 inventory 至少保存相对路径、大小、mtime 和 SHA-256；
- 日志中的绝对路径在发送给 LLM 前脱敏，但本地 provenance 保留真实路径；
- 不生成 V1/V2 兼容输出，V3 manifest 是唯一事实源。

---

## 12. QC、RAG、LLM 和候选审批

### 12.1 决策上下文

每轮生成不可变 `DecisionContext`：

```text
sample facts
read technology declaration
QcFeatureBundle
incumbent full config + fingerprint
incumbent AssemblyMetrics + source hashes
round index
seen parameter fingerprints
comparison policy version/hash
remaining budget
previous round outcomes
applicable metric IDs
known limitations/tool failures
```

context 写盘并计算 SHA-256。提议、审批和 round record 必须引用同一 hash。

### 12.2 规则和 RAG

- 每轮先运行确定性规则；
- 规则 STOP 立即阻止 LLM candidate；
- RAG source 必须在 allowlist、未过期并与当前 hifiasm 版本兼容；
- 检索 trace 保存 query、source ID、chunk hash、index hash 和过滤原因；
- 无参数授权证据时不得调用 LLM；
- prompt injection 内容继续作为不可信数据隔离；
- RAG 内容不能携带 shell、路径或工具调用指令进入批准配置。

### 12.3 LLM 调用

- 只发送结构化、最小化、路径脱敏上下文；
- API key 不写盘、不进入日志、不进入 report；
- 每轮最多一次调用；
- 调用前原子预留 LLM budget；
- receipt 保存 provider、model、时间、prompt hash、index hash、schema hash、output hash、token/latency 元数据；
- 原始输出经过严格 Pydantic 校验后才可进入 arbiter；
- provider retry 不得绕过总调用预算；
- `require_llm=false` 的 fallback 必须明确记录；
- `require_llm=true` 的失败必须进入 `FAILED_REQUIRED_LLM`。

### 12.4 Safety Arbiter

每个参数提议必须通过：

1. 白名单字段；
2. 类型和范围；
3. 单参数变化限制；
4. RAG source authorization；
5. supporting metric 存在且适用；
6. evidence 与提议方向一致；
7. 风险等级和用户确认；
8. 参数指纹未运行；
9. 预算允许；
10. 完整配置 overlay 和命令预渲染契约。

任何拒绝都保存原提议、reason codes 和证据引用，但不得创建 execution attempt。

---

## 13. 多轮比较和停止策略

### 13.1 baseline 和 incumbent

- baseline 完成全部 post-QC 后成为初始 incumbent；
- 每轮候选都与进入本轮时的同一个 incumbent 比较；
- 本轮结束前不逐个改变比较基准；
- 唯一满足硬保护和实质改善的胜者成为下一轮 incumbent；
- 多个非支配候选无法确定唯一胜者时停止人工复核；
- 候选失败、契约违规或核心指标缺失时无替换资格。

### 13.2 比较协议

沿用版本化 V2 比较策略，并补充：

- policy YAML 快照和 SHA-256 写入 run；
- 每个指标保存 value、unit、direction、applicability、source、tool version；
- baseline/candidate 必须使用同一 parser/schema 和相容工具版本；
- coverage backend 不同的结果默认不可自动比较；
- reference、BUSCO lineage、k-mer source 改变时停止比较；
- `null` 与“不适用”分开；
- 浮点阈值比较有固定 rounding/tolerance；
- tie-break 不得以 N50 覆盖保护指标；
- comparison JSON 保存完整判定路径和 reason codes。

### 13.3 实质改善和硬回退

V3 初始阈值继续沿用 V2 policy，不在本版本随意调参。任何阈值变化必须：

1. 修改版本化 policy；
2. 新增 ADR；
3. 增加边界测试；
4. 对历史 benchmark 重新计算；
5. 在报告中显示 policy version/hash。

### 13.4 轮次推进

```text
round 开始
  → 构建当前 incumbent context
  → 提议并审批 0～2 candidates
  → 执行所有已启动 candidates
  → 一次性比较
  → 更新 incumbent 或停止
  → 仅存在实质改善且仍有预算时进入下一轮
```

禁止：

- 为凑满三轮继续运行；
- 运行重复参数指纹；
- round 2/3 回退到 baseline context；
- 因候选已经消耗计算就降低接受标准；
- 将失败 attempt 当作 0 分候选；
- 用 LLM 文本替代 comparator 结论。

---

## 14. 预算、环境和工具链

### 14.1 统一预算

V3 统一控制：

- baseline + candidate assembly 总数；
- 每轮 candidate 数；
- tool retry 次数；
- CPU hours；
- walltime hours；
- 启动前最小可用磁盘；
- LLM 每轮/全局调用数。

候选启动前必须同时满足：

```text
assembly slot available
candidate slot available
retry budget available
estimated CPU <= remaining CPU
estimated walltime <= remaining walltime
free disk >= configured floor
estimated artifact size <= usable disk after safety margin
```

预计资源以最近完成 incumbent 的真实 Nextflow trace 为基准；无真实基准时使用保守默认并记录来源。

### 14.2 预算结算

- launch 前 RESERVE；
- 完成后用实际 trace COMMIT 并释放差额；
- 未启动候选释放 reservation；
- 进程中断保留 reservation，resume 时复用；
- attempt 明确失败后结算已消耗资源；
- 不允许负余额；
- 调整预算必须通过新的 CLI invocation 和审计事件，不能编辑 JSON。

### 14.3 环境 preflight

启动昂贵任务前检查并记录：

- Python、HiFi Agent、Nextflow、Java；
- hifiasm、seqkit、NanoPlot、meryl、GenomeScope；
- QUAST、BUSCO、Merqury；
- minimap2、samtools、coverage backend；
- R/GenomeScope 脚本依赖；
- BUSCO lineage；
- CPU、内存、磁盘和临时目录；
- 可写 outdir 和路径安全；
- reference/k-mer inputs checksum。

### 14.4 环境可复现性

- 正式环境锁定 JDK 21 与兼容 Nextflow；
- `conda run -n hifiAgent nextflow -version` 必须直接成功；
- 移除未声明的 `/home/gw/software`、`/data/gw/BUSCO` 默认路径；
- 如需外部工具根目录，必须由显式配置提供并写入 manifest；
- 声明版本与实际解析版本不一致时 preflight 失败或明确进入 human review；
- coverage 可以支持 mosdepth 或 bedtools，但一个 run 内必须固定 backend 并写入 feature/provenance；
- clean host 验收不得依赖开发者个人目录。

---

## 15. 报告和离线验证

### 15.1 自动报告

`RunCoordinator` 进入任何终态前调用报告服务。报告至少包含：

1. run identity 和终态；
2. 输入、配置来源和环境；
3. pre-QC 和限制；
4. baseline 参数、命令、post-QC；
5. 每轮 decision context；
6. 规则、RAG、LLM 的角色和状态；
7. 所有批准、拒绝、失败和未执行候选；
8. requested/approved/rendered/realized 参数；
9. 每轮比较和 incumbent 演化；
10. 预算计划与实际消耗；
11. 停止原因；
12. 最终推荐和科学限制；
13. provenance、checksum 和 verify 结果。

失败报告不得伪装为成功报告，缺失值必须显示 `NOT_AVAILABLE` 和原因。

### 15.2 报告输出

```text
06_report/final_report.md
06_report/final_summary.json
06_report/all_runs.tsv
06_report/all_parameters.tsv
06_report/provenance.tsv
06_report/verification_report.json
```

`final_summary.json` 是机器读取的权威终态摘要；Markdown 由其和 manifest 派生，不得另写不一致事实。

### 15.3 `verify-run`

验证至少包括：

- identity/config/input/environment hash；
- state/event/pending journal 一致性；
- budget ledger 平衡；
- attempt manifest 和完成 marker；
- 参数六件套等价；
- metrics source hash；
- comparison 输入与 selected run；
- incumbent chain；
- 报告引用；
- 目录中未登记的关键执行产物。

验证失败返回非 0，并生成结构化错误列表，不自动修复历史。

---

# 16. 分阶段实施任务书

## 阶段 0：V3 需求冻结和回归基线

### 目标

冻结 V3 范围，确保后续整合不破坏已验证组件。

### 任务

1. 将本任务书加入版本控制；
2. 为问题登记表建立对应 issue/ADR；
3. 保存当前测试、coverage、Ruff、mypy 和 workflow 基线；
4. 列出所有公开 CLI、状态文件、schema 和输出目录；
5. 标注每个现有组件的 owner、生产/测试调用点；
6. 冻结 V3 四参数白名单和 comparison policy；
7. 冻结“不提供旧版本兼容代码”的删除策略；
8. 禁止在阶段 0 后新增第二个生产控制器。

### 交付物

- `docs/v3/requirements_traceability.md`；
- `docs/adr/ADR-V3-001-single-production-controller.md`；
- `docs/adr/ADR-V3-002-canonical-attempt-layout.md`；
- `benchmark/reports/v3_baseline_quality.json`；
- 当前真实产物 inventory 和缺失清单。

### 验收

- 每个 V3-P0/P1 项有负责人、测试策略和阶段归属；
- 当前 354 个 portable tests 不少于基线；
- 没有以“后续处理”跳过 P0 owner。

---

## 阶段 1：配置、CLI 和环境契约

### 目标

让 V3 配置真正决定生产行为，并在昂贵执行前发现环境问题。

### 任务

1. 增加 `schema_id: hifi-agent` 和 `read_technology`；
2. 实现 `ExecutionBudgetConfig`；
3. 消除 `agent` 与 `optimization` 同义字段冲突；
4. 实现 CLI/config/default 来源解析；
5. 为 `assemble` 增加 `--decision-mode`；
6. 实现只读 `plan`；
7. 实现 environment preflight 和 manifest；
8. 固定 JDK/Nextflow，移除隐藏宿主路径；
9. 修正 README 未知字段和 Candida 示例路径；
10. 将 README 示例加入配置解析测试。

### 必须新增的测试

- 三种 decision mode 的配置和 CLI override；
- `require_llm` 非 hybrid 拒绝；
- legacy/new 字段冲突拒绝；
- max assemblies/round/candidate 组合边界；
- read technology receipt；
- Java 版本错误、工具缺失、版本漂移；
- README 示例实际通过 `hifi-agent plan`。

### 阶段出口

- `hifi-agent plan examples/...yaml` 成功；
- `conda run -n hifiAgent nextflow -version` 成功；
- `assemble --help` 与 Schema/README 一致；
- `OptimizationConfig` 字段都有生产消费测试，不再只是 Schema 字段。

---

## 阶段 2：V3 身份、状态、事件、锁和预算

### 目标

建立唯一、可恢复、可验证的 run 控制平面。

### 任务

1. 实现 `RunIdentity` 和 immutable identity；
2. 实现 `RunState` 和完整 transition table；
3. 实现 single-writer lock 和 stale lock 接管审计；
4. 实现 pending journal 事务协议；
5. 将 event trace 改为真实 append-only；
6. 实现 `BudgetLedger` 的 reserve/commit/release；
7. 实现 attempt/round/history manifest；
8. 增加旧 state schema 拒绝和 drift receipt；
9. 实现基础 `verify-run`。

### 故障注入测试

- pending 写完、state 未写时崩溃；
- state 写完、event 未追加时崩溃；
- event 已追加、pending 未删除时崩溃；
- lock 持有者存活/死亡；
- event sequence 缺口或重复；
- budget reserve 后中断；
- 同一 attempt resume 不重复扣费；
- config/input/environment hash 漂移。

### 阶段出口

- 所有故障点 resume 后得到唯一确定状态；
- JSONL 从不整体重写；
- 第二写入者无法启动；
- `verify-run` 能发现人工篡改。

---

## 阶段 3：baseline/candidate 统一执行器

### 目标

消除主控制器平铺路径，让每次 assembly 都成为自包含、不可覆盖的 attempt。

### 任务

1. 将 `CandidateExecutor` 抽象为通用 `AssemblyExecutor`；
2. baseline 改走同一 attempt executor；
3. Nextflow publish/work/cache 指向 attempt root；
4. baseline 和 candidate 都生成六件套契约；
5. post-QC 写入同一 attempt；
6. 生成 artifacts inventory 和完成 marker；
7. 区分 interruption resume 和 tool retry；
8. retry 生成新 attempt；
9. manifest 驱动产物发现，移除平铺路径猜测；
10. 删除 V1/V2 reader、adapter、迁移和旧执行入口。

### 必须新增的测试

- baseline approved/rendered/realized round-trip；
- candidate `None`、bool、边界和非法 token；
- baseline/candidate 相同 post-QC contract；
- attempt_001 失败、attempt_002 retry 不覆盖；
- interruption 恢复同一 attempt；
- 完成 marker 缺失不参与比较；
- inventory hash 漂移阻断；
- 两个候选并列目录不互相发布文件。

### 阶段出口

- `ExecutingAssemblyTools.run_candidate_workflow(run_dir, ...)` 平铺生产路径不再由 `assemble` 调用；
- baseline 与 candidate 命令契约等级一致；
- 每个 attempt 可独立离线验证。

---

## 阶段 4：incumbent-aware 决策和候选服务

### 目标

让每轮提议真正使用当前 incumbent，并统一规则、RAG、LLM 和安全审批。

### 任务

1. 实现 `DecisionContext`；
2. 将 `propose_run` 从固定 run 路径读取改为 typed context 输入；
3. 每轮保存 context 和 hash；
4. 规则结果转为统一 `ProposalDirective`；
5. hybrid 调用复用当前 governed RAG/LLM；
6. Safety Arbiter 强制单参数变化；
7. 完整保存 raw/rejected/approved proposal lineage；
8. 实现从 incumbent 完整配置 overlay；
9. 统一全局 fingerprint 去重；
10. 将 LLM calls 接入预算 ledger。

### 必须新增的测试

- round 2 context 引用 round 1 incumbent，不引用 baseline；
- 相同 diff 在不同 incumbent 上得到正确完整配置和 fingerprint；
- rule STOP 不调用 LLM；
- hybrid fallback 和 require_llm failure；
- 无授权 source、未知 metric、prompt injection、shell/path token 拒绝；
- 多参数提议在 V3 被拒绝；
- LLM 调用预算 resume 幂等。

### 阶段出口

- 三种 decision mode 使用同一生产 provider 接口；
- 所有 approved candidate 都能追溯到 context、规则/RAG/LLM 和 arbiter；
- LLM 无直接执行路径。

---

## 阶段 5：统一控制器和最多三轮闭环

### 目标

完成 V3 的核心 P0：由 `assemble` 自动推进到真正终态。

### 任务

1. 扩展或替换当前 Stage 3 `AssemblyController`；
2. coordinator 调用 pre-QC、baseline executor、proposal、candidate executor 和 comparator；
3. 将 `OptimizationLoop` 的已验证算法纳入唯一 state；
4. 删除 `CANDIDATE_EXECUTED_STAGE3` 和 comparison deferred 逻辑；
5. 实现 round 1～3；
6. 每轮末更新 incumbent 或停止；
7. 完整消费 `max_rounds`、candidate limit、plateau 和 enabled；
8. 所有 launch 接入 budget reservation；
9. 所有状态变化进入事务 journal；
10. 最终进入 REPORTING/VERIFYING/TERMINAL。

### portable 验收场景

1. baseline 直接接受；
2. baseline 规则 STOP；
3. round 1 candidate 改善后接受；
4. round 1 改善、round 2 plateau；
5. round 1/2/3 连续改善后 max rounds；
6. 两 candidate 唯一胜者；
7. Pareto 冲突进入 human review；
8. 所有 candidate 执行失败；
9. 参数契约违规；
10. round 2 启动前预算耗尽；
11. round 2 执行中断并 resume；
12. round 3 前全部 fingerprint 重复。

### 阶段出口

- 测试必须通过公开 `assemble` 使用的同一 coordinator；
- 不允许只用独立 `OptimizationLoop.run()` 证明完成；
- round 2/3 目录、事件、预算、比较和 incumbent 链真实生成；
- 主命令不再要求用户手工串联 Stage 6/7/8/9/10。

---

## 阶段 6：自动报告和 run verifier

### 目标

让每个终态都可解释、可离线审计。

### 任务

1. 将 V2 report collector 改为 manifest 驱动；
2. coordinator 自动生成 V3 报告；
3. 支持 accepted、plateau、budget、human review 和 failed 报告；
4. 展示完整 incumbent 演化；
5. 展示 requested/approved/rendered/realized 参数；
6. 展示 LLM 做了什么和没有做什么；
7. 展示预算预留/实际消耗；
8. 实现 `verify-run --deep`；
9. verification report 回填最终报告；
10. 增加 Markdown/JSON/TSV 一致性测试。

### 阶段出口

- `assemble` 结束即存在全部五类报告产物；
- 报告 selected run 与 state/comparison 完全一致；
- 删除/修改任一关键 artifact 后 verifier 必须失败；
- 报告不泄露 API key 和未脱敏 LLM 路径。

---

## 阶段 7：恢复、并发和破坏性测试

### 目标

证明 V3 在真实长任务常见故障下仍不重复、不覆盖、不误选。

### 任务

1. 在每个昂贵步骤前后加入 fault injection hook；
2. 测试进程 SIGTERM、机器重启等价恢复场景；
3. 测试 Nextflow cache 存在/缺失；
4. 测试部分 post-QC、部分 inventory 和损坏 marker；
5. 测试两个 `assemble` 并发；
6. 测试磁盘临界和写满；
7. 测试 state/event/ledger 人工篡改；
8. 测试 LLM timeout 和重复 provider response；
9. 测试失败报告二次生成幂等；
10. 保存恢复矩阵。

### 阶段出口

- 已完成 hifiasm 不因 controller resume 重跑；
- 已完成 candidate 不重复计费；
- 不完整 attempt 不被误标成功；
- 并发写入被阻止；
- 状态无法安全恢复时明确失败，不猜测继续。

---

## 阶段 8：portable E2E、质量门禁和文档

### 目标

在不依赖大型数据或付费 API 时完整验证生产 wiring。

### 任务

1. 建立 executable fixture toolchain，而不是直接注入 `ScriptedRunner`；
2. 通过真实 CLI 和文件边界运行三轮；
3. 建立 recorded LLM receipt replay；
4. 增加 CLI subprocess、退出码和报告测试；
5. 重构过大的 controller，保持模块边界；
6. 保持 Ruff、mypy strict 和 coverage；
7. 编写 quickstart、decision mode、resume、预算、结果解释文档；
8. 自动执行 README 命令；
9. 更新 architecture diagram、ADR 和 changelog；
10. 标注 advanced/deprecated CLI。

### 质量门禁

```bash
conda run -n hifiAgent ruff check .
conda run -n hifiAgent ruff format --check .
conda run -n hifiAgent mypy
conda run -n hifiAgent pytest --cov --cov-report=term-missing --cov-fail-under=85
conda run -n hifiAgent pytest tests/workflow -ra
conda run -n hifiAgent nextflow -version
```

### 阶段出口

- portable suite 0 failed；
- 非 real marker 的测试没有无理由 skip；
- V3 核心分支覆盖率 `>=90%`；
- clean clone portable quickstart 成功；
- 文档示例由 CI 执行。

---

## 阶段 9：真实数据和真实 LLM 验收

### 目标

恢复当前中断的发布证据链，在同一 release commit 上完成真实验收。

### 任务

1. 选择并冻结至少一个真实 PacBio HiFi 验收样本；
2. 建立不依赖 Git ignored 相对路径的 dataset manifest；
3. 保存 input URI/位置、大小、SHA-256、授权和物种元数据；
4. 在当前 commit 完成 baseline；
5. 完成至少一个单变量真实 candidate 和同源 post-QC；
6. 运行 comparator 并得到接受、拒绝或平台期结论；
7. 验证实际 argv 和 contract；
8. 运行一次 live hybrid LLM smoke，保存脱敏 receipt；
9. 运行选定 real acceptance suite，禁止 skipped；
10. 生成 release evidence bundle。

### 真实验收最低要求

- baseline 和 candidate 输入 checksum 相同；
- 环境 manifest 完整；
- baseline/candidate 的工具和 QC 协议相同；
- candidate 只有一个参数变化；
- contract 为 PASS；
- post-QC metrics 可解析；
- comparison reason codes 完整；
- `verify-run --deep` 通过；
- 真实候选不要求改善，但结论必须科学一致；
- live LLM 不要求候选获批，但必须证明 provider→Schema→arbiter 的真实 wiring。

### 验收命令

```bash
HIFI_AGENT_REAL_ACCEPTANCE=1 \
  conda run -n hifiAgent pytest -m real_acceptance -ra

hifi-agent verify-run /path/to/real_run --deep
```

### 阶段出口

- 选定 suite 0 failed、0 skipped；
- evidence bundle 中 commit、wheel、config、input 和 run hash 一致；
- 不再依赖已删除的 `Data/Candida_albicans/hifiAgent` 隐式目录；
- 历史 V2 candidate 可以作为补充证据，但不替代 V3 当前运行。

---

## 阶段 10：迁移、发布候选和 V3.0.0 发布

### 目标

完成无兼容面的 clean-room 复验和可追溯发布。

### 任务

1. 验证 wheel/source tree 不包含 V1/V2 reader、迁移器或执行入口；
2. 验证旧 schema 和旧字段被明确拒绝；
3. 将包版本更新为 `3.0.0`；
4. 从 clean clone 重建环境；
5. 重跑 portable 和真实门禁；
6. 生成 wheel/sdist 和 SHA-256；
7. 生成 `release/v3.0.0/acceptance_manifest.json`；
8. 保存测试摘要、真实 run verification 和已知限制；
9. 创建 annotated tag `v3.0.0`；
10. 确认 tag、artifact、acceptance commit 一致。

### 发布产物

```text
release/v3.0.0/
├── RELEASE_NOTES.md
├── ACCEPTANCE_REPORT.md
├── acceptance_manifest.json
├── portable_test_summary.txt
├── real_acceptance_summary.txt
├── real_run_verification.json
├── environment_manifest.json
├── known_limitations.md
└── SHA256SUMS
```

### 阶段出口

- clean clone 门禁通过；
- release commit 工作树干净；
- tag 指向验收 commit；
- wheel 中版本为 3.0.0；
- 发布说明不夸大科学最优性；
- 所有 P0/P1 已关闭或按发布规则阻断。

---

## 17. 阶段依赖和建议顺序

```text
阶段 0 需求冻结
  → 阶段 1 配置/环境
  → 阶段 2 状态/预算
  → 阶段 3 统一执行器
  → 阶段 4 incumbent-aware 提议
  → 阶段 5 统一三轮控制器
  → 阶段 6 报告/verifier
  → 阶段 7 故障恢复
  → 阶段 8 portable E2E/文档
  → 阶段 9 真实验收
  → 阶段 10 发布
```

允许的并行工作：

- 阶段 1 的文档修复可与阶段 2 设计并行；
- 阶段 4 的 proposer typed interface 可在阶段 3 接口冻结后开发；
- 阶段 6 的报告模型可在阶段 5 state schema 稳定后并行；
- 真实数据准备可提前开始，但真实 candidate 不得早于阶段 3 参数契约通过。

禁止的倒序：

- 不得在阶段 2 前接入三轮生产写入；
- 不得在阶段 3 前运行 V3 真实 candidate；
- 不得用阶段 8 fixture 通过替代阶段 9；
- 不得先更新版本/tag 再补验收。

---

## 18. 建议里程碑和时间表

| 里程碑 | 阶段 | 可演示结果 | 建议周期 |
|---|---|---|---:|
| M1：契约冻结 | 0～1 | 配置、CLI、环境计划可执行 | 1～2 周 |
| M2：可靠控制平面 | 2 | state/event/lock/budget 可恢复 | 1～2 周 |
| M3：统一执行 | 3 | baseline/candidate 自包含 attempt | 1～2 周 |
| M4：智能闭环 | 4～5 | `assemble` 完成最多三轮 | 2～3 周 |
| M5：可审计产品 | 6～8 | 自动报告、verifier、portable E2E | 2～3 周 |
| M6：真实发布 | 9～10 | 当前 commit 真实 run 和 3.0.0 release | 2～4 周 |

总建议周期为 9～16 周，取决于真实数据计算时间和环境资源。时间表不能作为降低验收标准的理由。

---

## 19. 测试策略

### 19.1 测试分层

| 层级 | 目的 | 是否允许 mock |
|---|---|---:|
| 纯单元 | Schema、transition、policy、parser | 允许 |
| 组件契约 | proposer、executor、comparator、reporter | 允许外部工具 fixture，不允许绕过被测契约 |
| portable E2E | 证明生产 CLI/controller wiring | 不允许 `ScriptedRunner` 直接替代 coordinator 依赖；允许 fixture executable |
| workflow | Nextflow compile、publish、resume | 使用真实 Nextflow |
| real acceptance | 生物数据、真实工具、真实文件 | 不允许 mock |
| live LLM smoke | provider 到 arbiter wiring | 使用真实 provider，release-only |

### 19.2 必测回归

- `hom_cov=None` 不变为 `true`；
- bool 不能作为 int；
- approved/rendered/realized 完全一致；
- round 2 从 incumbent overlay；
- hard regression 不被 N50 覆盖；
- same-read Merqury advisory；
- untrusted genome size 降级；
- reference-free 指标不误用；
- 失败 attempt 不参与比较；
- retry 不覆盖；
- resume 不重跑、不重复扣费；
- LLM 不覆盖规则 STOP；
- prompt injection 不进入执行；
- config/environment drift 不静默恢复；
- 最终报告与 state/comparison 一致。

### 19.3 跳过策略

- portable suite 中不允许无 issue/reason 的 skip；
- real tests 可以在普通 CI 通过 marker 跳过；
- release gate 必须显式启用 real marker，并断言选定测试数大于 0、skip 数为 0；
- “没有真实数据所以全部 skipped”是发布失败；
- live LLM smoke 可以独立于每次 CI，但 V3 正式发布必须有当前 commit 的 receipt。

---

## 20. Benchmark 和验收数据治理

### 20.1 数据 manifest

真实数据不必提交 Git，但必须有版本化 manifest：

```text
dataset_id
species
read_technology
source/license
local/external locator
file size
sha256
expected genome size + source
ploidy
reference + sha256 | null
BUSCO lineage
approved usage
```

测试通过环境变量或配置解析 artifact root，禁止硬编码开发者个人绝对路径。

### 20.2 Benchmark 场景

至少保留：

1. rules only；
2. hybrid recorded replay；
3. live hybrid smoke；
4. baseline accepted；
5. candidate rejected by hard regression；
6. candidate accepted by material improvement；
7. plateau；
8. metric conflict；
9. budget stop；
10. round 2 resume。

### 20.3 评价指标

系统工程指标：

- 成功恢复率；
- 重复昂贵任务数，目标 0；
- 历史覆盖数，目标 0；
- 参数契约违规漏检数，目标 0；
- 报告/状态不一致数，目标 0；
- 真实验收 skip 数，目标 0；
- 决策可追溯率，目标 100%。

生物学指标沿用 comparison policy，报告原始值和适用性，不压缩为单一“总质量分”。

---

## 21. 风险登记表

| 风险 | 等级 | 后果 | 缓解 |
|---|---:|---|---|
| 重构控制器导致 V2 组件回归 | P0 | 已验证能力丢失 | 先建 traceability，保持组件契约测试，分阶段替换 |
| 保留双 state 形成新旁路 | P0 | resume 和报告不一致 | 一个权威 `RunState`，loop 只做领域计算 |
| baseline 迁移到 attempt 后 Nextflow publish/resume 失效 | P0 | 重跑或丢产物 | 真实 workflow resume 测试和中断测试 |
| round 2 仍固定使用 baseline | P0 | 三轮逻辑科学错误 | incumbent hash/overlay P0 回归测试 |
| 参数或实际 argv 漂移 | P0 | 实验不可解释 | baseline/candidate 六件套和执行前后双向验证 |
| state/event crash window | P0 | 错误恢复或重复执行 | pending journal、sequence、fault injection |
| 真实证据再次被清理 | P0 | 发布不可重放 | 外部 artifact manifest、release bundle、校验脚本 |
| LLM 越权或 prompt injection | P0 | 非法候选执行 | typed output、arbiter、零 shell、负向测试 |
| 多轮磁盘耗尽 | P1 | run 失败 | disk preflight、预测、预算、安全余量 |
| 工具版本漂移 | P1 | 指标不可比 | lockfile、environment manifest、同 run 固定版本 |
| coverage backend 改变 | P1 | CV 等指标不可比 | backend 写入 metrics，同 run 不允许改变 |
| 多指标无唯一胜者 | P1 | 自动误选 | Pareto conflict 和 human review |
| real LLM API 不稳定 | P1 | 发布验收波动 | recorded replay + 单独 live smoke + receipt |
| 文档再次漂移 | P1 | 用户无法运行 | README 示例 CI |
| 旧 run 被误写 | P1 | 历史破坏 | schema guard、拒绝旧 schema、新 outdir |
| 任务范围扩张 | P2 | V3 延期 | 冻结 assembler/白名单/单样本范围 |

---

## 22. Definition of Done

任一阶段只有同时满足以下条件才算完成：

1. 生产代码已实现，不以设计文档或 mock 替代；
2. 正常、边界、失败、恢复和安全测试齐全；
3. 对应需求 traceability 已更新；
4. Ruff、format、mypy 和相关 pytest 通过；
5. 产物有 schema version、manifest 和稳定字段；
6. 状态变化和外部调用可审计；
7. 失败不删除、不覆盖历史；
8. 新配置字段有生产消费测试；
9. 文档示例可执行；
10. 真实工具相关阶段至少有一次真实命令验证；
11. 未通过项不能通过降低测试数量、改为 skip 或只改文档标记完成；
12. P0 变更完成 code review 和 ADR 复核。

---

## 23. V3 最终验收清单

### 23.1 统一主链

- [ ] `assemble` 自动完成输入、环境、pre-QC、baseline 和 post-QC；
- [ ] `assemble` 自动调用规则/RAG/LLM/arbiter；
- [ ] `assemble` 自动执行候选和比较；
- [ ] `assemble` 可以生成 round 2/3；
- [ ] round 2/3 基于当前 incumbent；
- [ ] 没有 Stage 3 deferred comparison 终态；
- [ ] 用户不需手工串联分阶段命令；
- [ ] `OptimizationConfig` 全部驱动生产行为。

### 23.2 参数和执行正确性

- [ ] baseline/candidate 均有六件套契约；
- [ ] `None` 永不变成 `true`；
- [ ] approved == rendered == realized；
- [ ] 非法参数零执行；
- [ ] 每个 V3 candidate 只有一个参数变化；
- [ ] command 不通过 shell；
- [ ] contract violation 不参与比较；
- [ ] 实际 argv 可从最终报告追溯。

### 23.3 状态、历史和预算

- [ ] 一个权威 state；
- [ ] event/ledger 真正 append-only；
- [ ] pending transaction 可恢复；
- [ ] 单写者锁有效；
- [ ] attempt 不覆盖；
- [ ] interruption resume 同一 attempt；
- [ ] retry 创建新 attempt；
- [ ] resume 不重复执行和扣费；
- [ ] assemblies/retries/CPU/walltime/disk/LLM budgets 全部执行；
- [ ] `verify-run --deep` 通过。

### 23.4 科学安全

- [ ] 不按 N50 单指标选择；
- [ ] 硬回退不可覆盖；
- [ ] 指标适用性和来源完整；
- [ ] same-read Merqury 标记 advisory；
- [ ] genome size 不可信时降级；
- [ ] reference-free/reference-based 分离；
- [ ] metric conflict 安全停止；
- [ ] LLM 无法覆盖规则 STOP；
- [ ] LLM 无法改变白名单、预算或命令；
- [ ] 报告不声称全局最佳。

### 23.5 报告和可解释性

- [ ] 所有终态自动生成报告；
- [ ] 报告包含全部成功、失败、拒绝和未执行候选；
- [ ] 报告展示 incumbent 演化；
- [ ] 报告展示配置来源和环境；
- [ ] 报告展示 RAG/LLM 证据和限制；
- [ ] Markdown/JSON/TSV 一致；
- [ ] 报告不泄露密钥；
- [ ] report selected run 与 state/comparison 一致。

### 23.6 工程和真实发布

- [ ] portable pytest 全部通过；
- [ ] coverage 总体 `>=85%`；
- [ ] V3 核心分支覆盖率 `>=90%`；
- [ ] Ruff、format、mypy strict 通过；
- [ ] Nextflow compile/resume/attempt 隔离通过；
- [ ] fixture 通过生产 controller 完成三轮；
- [ ] round 2 resume 通过；
- [ ] 当前 commit 真实 baseline + candidate 完成；
- [ ] 选定 real suite 0 failed、0 skipped；
- [ ] live hybrid receipt 属于当前 commit；
- [ ] clean clone quickstart 通过；
- [ ] 声明/实际环境一致；
- [ ] tag、wheel、checksum 和 acceptance commit 一致。

---

## 24. 第一批立即执行任务

按顺序开始，不应先运行新的大型真实 candidate：

1. 为本任务书建立 requirement ID 到测试文件的映射；
2. 编写单控制器 ADR，决定 `OptimizationLoop` 如何降为领域服务；
3. 删除或替换 `CANDIDATE_EXECUTED_STAGE3` 终态设计；
4. 为 `assemble` 增加 `--decision-mode` 并消费 `OptimizationConfig`；
5. 修复 README 无效字段和 Candida 示例路径；
6. 重建 JDK 21/Nextflow 环境并移除隐藏 fallback；
7. 实现 `RunIdentity`、`RunState` 和 transaction journal；
8. 实现 run lock 和统一 `BudgetLedger`；
9. 将 baseline 接入通用 attempt executor 和六件套契约；
10. 让 proposal provider 接收当前 incumbent context；
11. 将 comparator 和 round progression 接入主控制器；
12. 用 executable fixture 先跑通 round 1/2/3；
13. 自动接入 V3 report/verifier；
14. 建立真实 dataset manifest，恢复 0-skip real gate；
15. 最后运行当前 commit 的真实 baseline + 单变量 candidate。

---

## 25. 发布判定

满足以下任一条件时不得发布 V3：

- `assemble` 仍只到第一候选或要求用户手工比较；
- 三轮只在 scripted loop 中成立；
- 存在两个竞争的生产权威 state；
- round 2/3 仍基于 baseline 而非 incumbent；
- baseline 没有完整参数契约；
- 主控制器绕过隔离 executor；
- resume 会重跑已完成 hifiasm 或重复扣费；
- state/event/ledger 不能从 crash window 恢复；
- LLM 可以绕过规则或 arbiter；
- 真实验收为 failed 或 skipped；
- 环境依赖未声明个人绝对路径；
- 报告与实际 argv、comparison 或 selected run 不一致；
- 当前 release commit 工作树不干净；
- tag、wheel 和 acceptance evidence 不属于同一 commit；
- 文档仍宣称超出当前证据和搜索边界的“最佳参数”。

只有第 23 节全部通过，才允许更新版本、创建 `v3.0.0` tag 和发布。

---

## 26. 变更治理

以下任何变化必须新增 ADR、测试和任务书修订：

- 新增 assembler；
- 扩展参数白名单；
- 改变最多三轮或每轮候选上限；
- 允许多参数 candidate；
- 改变硬回退或实质改善阈值；
- 改变 LLM 权限；
- 改变 canonical attempt 布局；
- 改变真实验收样本或删除其证据；
- 允许旧 V1/V2 run 原地迁移；
- 放宽 release real-test 门禁。

任务书、Schema、代码、测试、README 和 release acceptance 必须保持同步，不能只修改其中一项。

---

## 27. 文档结束

V3 的成功不以新增多少类或命令衡量，而以现有组件是否形成一条真实、可恢复、可证明的生产
闭环衡量。V3.0.0 的最终定义是：

> **用户通过一个 `assemble` 命令，在明确预算和科学保护条件下完成 baseline、最多三轮受控候选、同源评价、incumbent 更新、停止和报告；任一结论都能从最终报告追溯到实际命令、原始指标、证据与 checksum，并能在当前发布证据中重放验证。**
