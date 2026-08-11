# HiFi Agent V1/V2 任务书符合性评估报告

> 评估对象：当前工作区 `/data/gw/code/HiFiAgent`，Git `main` 分支 `1786dcd3cd5b8ecae20b767a5a0c7328656bac6a`
> 任务书：`HiFi_Agent_V1_Project_Plan.md`、`HiFi_Agent_V2_Project_Plan.md`
> 评估日期：2026-08-10
> 评估方式：需求逐条映射、代码静态审查、当前测试重跑、保留产物抽查、发布证据复核
> 本报告中的“达标”表示当前代码与当前可重放证据满足任务书，不等同于历史文档中的自述状态。

## 1. 执行结论

### 1.1 总体结论

| 版本 | 当前结论 | 说明 |
|---|---|---|
| V1 | **部分达到，但不满足当前完整发布判定** | 输入验证、QC、hifiasm、post-QC、规则、安全白名单、报告、测试等主要组件已经实现；但真实闭环仍由多个命令和适配器分段完成，legacy Agent 不能对真实 candidate 完成重新评价与选择，当前 V1 真实验收产物已缺失，显式真实测试失败。 |
| V2 | **组件实现度较高，但不达到 V2 最终验收** | 参数契约、QC feature bundle、RAG/LLM typed proposal、Safety Arbiter、隔离候选执行器、多指标比较器、三轮循环和 V2 报告器均有实现和测试；但这些组件没有接入任务书要求的一个 `hifi-agent assemble` 端到端控制器。主命令只执行 baseline 和至多一个第一轮规则候选，随后以 `CANDIDATE_EXECUTED_STAGE3` 结束，不进行比较、incumbent 更新、第二/三轮、RAG/LLM 提议或最终 V2 报告。 |

因此，当前仓库更准确的定位是：

> **一个工程质量较好、关键科学安全组件较完整、拥有历史真实运行证据的 V2 分阶段实现；尚不是任务书定义的统一三轮端到端 V2 产品。**

### 1.2 发布判定

- 当前代码可以作为组件演示、规则/安全策略演示和 portable demo 使用。
- 当前代码可以运行真实 baseline 工作流；工作区中有一个完整的 Ziziphus baseline 与 post-QC 实例。
- 当前代码不应按 V2 任务书宣称“一条命令完成最多三轮 RAG/LLM 闭环”。
- 按 V1/V2 任务书的严格发布条件，当前 HEAD 均应判定为 **NO-GO**，其中 V2 的阻断项更明确。

## 2. 评估口径

### 2.1 状态定义

| 状态 | 判定规则 |
|---|---|
| 满足 | 当前代码存在真实执行路径，并有当前可运行测试或可核验产物支持。 |
| 部分满足 | 数据模型或组件已实现，但未接入主流程、只由 fixture/mock 验证、产物布局不完全符合，或当前真实证据不可重放。 |
| 不满足 | 任务书要求的公开行为不存在，或当前验证直接失败。 |
| 无法验证 | 依赖外部 API、数据库或已删除产物，当前环境不足以形成结论。该状态不计为通过。 |

### 2.2 证据优先级

本次采用以下证据优先级：

1. 当前源代码和公开 CLI 的真实控制流；
2. 本次实际运行的测试、静态检查和 CLI；
3. 当前工作区中可核验的真实结果及 checksum/manifest；
4. 历史验收 JSON、release note 和 checklist；
5. README 或任务书中的完成声明。

历史 `PASS` 记录可证明某一时间点曾完成过验收，但如果当前依赖产物已缺失或当前测试不能重放，不能单独证明当前 HEAD 达标。

## 3. 当前验证快照

### 3.1 实际执行结果

| 验证项 | 当前结果 | 判定 |
|---|---|---:|
| `pytest -q --cov --cov-fail-under=85` | `354 passed, 17 skipped`；coverage `87.14%` | portable 门禁通过；真实验收未通过发布口径 |
| Ruff lint | `All checks passed` | 通过 |
| Ruff format | `120 files already formatted` | 通过 |
| mypy strict | `Success: no issues found in 119 source files` | 通过 |
| `tests/workflow` | `7 passed`，含 Nextflow smoke 和中断恢复 | 通过 |
| V2 portable demo | `5/5` safety scenarios passed；明确 `biological_data_used: false` | 通过，但不是生物学验收 |
| 显式真实集成验收 | `HIFI_AGENT_REAL_ACCEPTANCE=1 ... tests/integration` 得到 `14 failed, 2 skipped` | 不通过 |
| Nextflow 版本 | 显式使用本机 JDK 21 时为 `25.04.7` | 可用 |
| 任务书原样环境命令 | `conda run -n hifiAgent nextflow -version` 失败；当前 env 的 Nextflow 选择了不受支持的 Java 25 | 不通过 |
| README 示例配置 | README YAML 含 Schema 不支持字段；仓库示例的相对路径和文件名大小写也不匹配当前数据 | 不通过 |

17 个默认跳过项中，16 个涉及保留真实数据或真实 LLM 验收，另 1 个涉及缺失的保留 Candida 产物。V2 任务书明确要求发布前真实验收不能仅以 skipped 代替，因此不能用“全量 pytest 退出码为 0”替代真实门禁。

### 3.2 Git 与发布证据

- 当前存在本地 annotated tag：`v1.0.0`、`v2.0.0`。
- `v2.0.0` 指向 `2e151e7436cedb3f740cb404e63808efec4d8e25`。
- 当前 HEAD 为 `1786dcd3cd5b8ecae20b767a5a0c7328656bac6a`，比 `v2.0.0` 多 4 个提交，主要是 CI/Nextflow resume 修复。
- `dist/hifi_agent-2.0.0-py3-none-any.whl` 的 SHA-256 与 `release/v2.0.0/SHA256SUMS` 一致：`71b9164...c45a35fa`。
- `benchmark/reports/v2_stage12_acceptance.json` 和对应文档记录 2026-07-29 的历史 `PASS`。
- 但历史 V2 真实测试依赖 `Data/Candida_albicans/hifiAgent` 下的 baseline/checksum/post-QC 产物；这些文件当前不存在。当前显式执行任务书要求的真实 suite 会失败。

结论：历史 V2 发布包和当时验收记录具有证据价值，但它们不是当前 HEAD 的完整、可重放验收。

## 4. 当前实现架构概览

当前仓库实际包含两套相互重叠的控制路径：

```text
V1 分步路径
validate → run → decide/agent → propose/explain → optimize → report

V2 Stage 3 主命令路径
assemble → validate → baseline + post-QC → rule evaluation
         → [最多一个规则候选 + post-QC] → Stage 3 summary

独立 V2 组件路径
propose → CandidateExecutor → RoundComparator → OptimizationLoop → report-v2
```

各个独立 V2 组件能力较完整，问题主要在于第三条路径没有被第一条 `assemble` 主命令统一编排。

## 5. V1 任务书符合性评估

### 5.1 V1 核心功能映射

| 需求域 | 状态 | 当前证据 | 主要差距 |
|---|---:|---|---|
| 单样本、多 FASTQ/FASTQ.GZ 输入 | 满足 | `SampleConfig` 支持 path/list；输入路径、后缀、gzip、首条 FASTQ 记录和资源范围校验 | “是否真为 HiFi”没有数据级识别，规则上下文将 `input_type` 固定为 `pacbio_hifi`（`src/hifi_agent/rules/context.py:121`） |
| checksum、resolved config、validation receipt | 满足 | `src/hifi_agent/config.py` 生成并可重新校验 SHA-256 | `run_manifest.json` 内容较简化；任务书指定的 `00_metadata/software_versions.tsv` 不是 baseline 主工作流直接产物 |
| SeqKit、NanoPlot 基础 pre-QC | 满足 | Nextflow 真实 process、稳定 parser、golden/unit tests | 无关键缺口 |
| meryl、GenomeScope、coverage、k-mer source 分级 | 满足 | `KMER_COUNT`、条件 GenomeScope、失败返回 null/warning；feature bundle 中保留 confidence/limitation | `environment.yml` 未声明 GenomeScope/R 依赖，执行依赖本机 `/home/gw/software/genomescope2.0` fallback，降低可移植性 |
| hifiasm baseline 与 GFA/FASTA/bin | 满足 | baseline 只传 `-o/-t`；保存 GFA、primary/hap1/hap2 FASTA 和 `.bin`；有 reuse manifest | 工作流为单一 `main.nf`，未按建议拆 module；这不是功能阻断 |
| QUAST/BUSCO/Merqury/mapping/coverage | 满足 | 真实 Nextflow process、独立 parser、缺失值和 tool failure 处理；当前 Ziziphus 产物包含完整结果 | V1 指定 mosdepth 为必需；环境只固定 bedtools，实际结果使用 bedtools fallback。属于实现偏差，不影响已有 coverage 指标但影响任务书逐字符合性 |
| 统一 `PreQcMetrics`/`AssemblyMetrics` | 满足 | Pydantic Schema、事实/派生指标、版本、来源、限制和 tool failure 字段 | V2 feature bundle 是增强版；V1 Schema 仍为 `1.0`，可接受 |
| 规则引擎、阈值来源、白名单 | 满足 | `rules/v1_rules.yaml` 有 14 条规则；阈值版本化；规则优先级、冲突、安全停止和候选白名单均有测试 | 个别真实场景会落入通用 `STOP_INSUFFICIENT_EVIDENCE`，属于保守行为，不是越权 |
| Agent 状态、预算、恢复、decision trace | 部分满足 | V1 状态机、CPU/walltime、候选数、工具重试、原子 state + JSONL trace 均存在 | `ExistingRunAgentTools` 只读取已有组装；对 candidate 调用 `evaluate` 会明确拒绝并转入证据不足，不能在 legacy `agent` 命令内完成真实候选比较 |
| RAG/LLM 解释安全 | 满足 | 本地 allowlist 索引、source/version/hash、严格 Schema、无 shell、来源和置信度约束；关闭 LLM 可运行 | V1 主要是解释规则候选；V2 proposer 才允许 LLM typed proposal |
| 一轮有限闭环 | 部分满足 | Planner、candidate workflow、comparison、N50 hard-regression 防护均实现；有真实候选历史 | V1 `agent`、`optimize` 和执行入口分离；当前没有一个 V1 入口把决策、真实候选执行、同源 post-QC、比较、选择和报告自动串完 |
| Markdown/JSON/TSV 报告 | 满足（分步） | Jinja2 报告、summary、comparison、parameter diff、provenance、software versions、失败/缺失显示均有测试 | `assemble` 不调用完整报告器；V1 用户需另行执行 `report` |
| Nextflow resume | 满足 | 当前 `tests/workflow` 7/7，通过真实中断恢复和 smoke | 当前 conda Java 选择存在环境漂移，项目依靠宿主 JDK fallback |
| Benchmark、消融、文档、release | 部分满足 | V1 benchmark、消融、GIF、CITATION、release notes、tag 均存在 | 当前历史 V1 真实结果被移除；显式真实 suite 失败；示例配置不能直接验证；`hifi-agent plan` 仍未实现（`src/hifi_agent/cli.py:113-118`） |

### 5.2 V1 P0 验收归纳

V1 P0 的分析工具链基本已经编码完成：

- 合法配置可以进入 Nextflow；
- SeqKit、NanoPlot、meryl、GenomeScope、hifiasm、QUAST、BUSCO、Merqury、mapping 都有真实 process；
- primary/haplotype FASTA、统一 JSON、规则决策、白名单候选、comparison 和 Markdown 报告组件都存在；
- 当前 Ziziphus 结果证明 baseline、BUSCO、Merqury、mapping 和安全停止曾在真实数据上运行；
- 当前 V2 Stage 7 目录也保留了真实 Candida candidate 的参数契约和 post-QC 产物。

但是，按 V1 第 18 节发布判定，以下条件当前不能同时成立：

1. “至少一个真实数据端到端运行成功”无法通过当前 V1 验收测试重放；
2. legacy Agent 不会自动执行并比较缺失的 candidate；
3. `agent` 与 `optimize/report` 是分离流程；
4. 当前真实集成 suite 明确失败，而不是仅仅没有运行；
5. README/示例不能满足“新用户按示例即可完成”的严格要求。

### 5.3 V1 结论

V1 的科学分析和安全组件已经达到较成熟水平，作为“分步式受控组装助手”基本成立；作为任务书定义的“自动闭环 V1 发布物”，当前只能判定为 **部分满足**。

## 6. V2 任务书符合性评估

### 6.1 V2 功能成功标准逐项评估

| V2 功能标准 | 状态 | 评估 |
|---|---:|---|
| 一条 CLI 完成 QC、baseline、规划、候选、比较、停止和报告 | **不满足** | `assemble` 的 docstring 明确是“first bounded candidate orchestration path”（`src/hifi_agent/cli.py:142-171`）；控制器只有 5 个状态，candidate 完成后直接报告，比较被标为 `STAGE3_COMPARISON_DEFERRED_TO_STAGE8`（`src/hifi_agent/orchestration/controller.py:325-359`） |
| `rules_only`、`hybrid`、`llm_disabled` 三模式可审计 | 部分满足 | `propose` 和 `ProposalDecisionBundle` 支持三模式；`assemble` 没有 `--decision-mode`，也不消费配置中的 `optimization.decision_mode` |
| hybrid 允许 LLM 提出白名单候选并经确定性审批 | 满足（组件） | `propose_run`、严格 typed Schema、source/metric 校验、Safety Arbiter、风险确认和拒绝记录均存在 |
| baseline 后最多 3 轮 | 部分满足 | `OptimizationLoop` 可执行 1～3 轮；但没有接入 `assemble`，三轮证据使用 `ScriptedProvider`/`ScriptedRunner` fixture，而不是真实公开控制器 |
| 每轮默认 1、上限 2 个候选 | 满足（组件） | Schema、proposer、loop、comparator 均限制 1～2 |
| 无实质改善立即停止 | 满足（组件） | `RoundComparator` 有 material threshold、Pareto、`STOP_PLATEAU` 和硬回退保护 |
| 成功、失败、拒绝、未执行候选完整保留 | 部分满足 | `CandidateExecutor` 对失败/重试/库存/manifest 做得较完整；主 `AssemblyController` 仍通过平铺 V1 目录执行，再让 attempt manifest 引用外部平铺文件，不是同一条严格隔离路径 |
| `--resume` 不重复昂贵步骤 | 部分满足 | Nextflow resume、V2 state/history、CandidateExecutor 和独立 OptimizationLoop 都有恢复测试；统一主流程不存在，因而没有跨 baseline→RAG→候选→round 2/3→report 的完整 resume 证明 |
| 最终报告说明选择、停止及 LLM 权限 | 满足（手动组件） | `render_v2_report` 和 `report-v2` 能完成；`assemble` 只生成 `v2_stage3_summary.json`，不会自动生成最终 Markdown/TSV 报告 |

### 6.2 V2 科学成功标准

| 科学标准 | 状态 | 证据与说明 |
|---|---:|---|
| 不以 N50 单指标选择 | 满足 | comparison policy 把 N50 设为非保护性指标；BUSCO/k-mer/mapping/coverage hard regression 优先 |
| 硬回退不能被综合分数覆盖 | 满足 | comparator 使用显式 hard regression/acceptance failure，不使用单一加权总分 |
| 同源 HiFi Merqury 标记 advisory | 满足 | `MERQURY_SAME_HIFI_DATA_NOT_INDEPENDENT` 写入 limitation；真实 Ziziphus 产物可核验 |
| genome size 不可信时 size ratio 不作为核心 | 满足 | `RoundComparisonContext.genome_size_trusted` 控制适用性；QC bundle 保存 confidence/limitation |
| reference-free 与 reference-based 严格区分 | 满足 | QUAST mode 和 comparison applicability 分离；reference-free 时结构错误不参与自动判断 |
| LLM 参数建议具备证据、条件、风险、不确定性 | 满足（proposal 层） | `ProposedParameter` 强制 source IDs、metric IDs、applicability、risks、uncertainty、confidence |
| 实际 argv 与批准配置完全一致 | 部分满足 | candidate 有双向 command contract、实际参数反解析和 contract violation 阻断；baseline 不生成任务书列出的完整 requested/approved/rendered/realized/check 六件套 |
| 冲突、工具失败、参数漂移安全停止 | 满足（组件） | rule、proposer、CandidateExecutor、comparator 均有负向测试；参数违规 candidate 不进入比较 |

### 6.3 V2 工程成功标准

| 工程标准 | 状态 | 当前结果 |
|---|---:|---|
| Python 单元/集成测试全部通过 | 部分满足 | portable 测试 354 通过；17 skipped；显式真实 integration 为 14 failed、2 skipped |
| Ruff、format、mypy strict、coverage gate | 满足 | 全部通过，coverage 87.14% ≥ 85% |
| Nextflow compile、resume、隔离、round-trip | 部分满足 | workflow 7/7；参数 round-trip 测试充分；真实 candidate 隔离有历史产物，但当前 source baseline 缺失，不能完整复验 |
| 小 fixture 完成三轮状态机 | 满足 | 三轮、平台期、冲突、预算、resume、去重均有测试 |
| 至少一个真实样本 baseline + 一个真实 candidate | 历史满足、当前不可完整验证 | Candida candidate `attempt_002` 及 64 GB 产物仍在；其 source baseline/checksum 已缺失。Ziziphus baseline 完整，但没有同一主流程 candidate |
| 发布前工作树干净且真实验收不以 skipped 代替 | 不满足 | 评估开始时工作树干净；但当前真实门禁默认 skipped，显式启用后失败。当前 HEAD 也不等于 `v2.0.0` tag |

### 6.4 V2 数据模型与安全契约

| 模型/契约 | 状态 | 说明 |
|---|---:|---|
| `OptimizationConfig` | 部分满足 | 字段和范围基本符合任务书，但 `config.optimization` 在生产控制器中没有被消费；搜索结果只见 Schema 定义，没有 `config.optimization.*` 的执行引用 |
| `QcFeatureBundle` | 满足 | 单位、来源、confidence、limitation、missing、tool failure、source SHA-256 和脱敏摘要完整 |
| `LLMProposalBundle` | 满足 | 采用等价但更细的 parameter-list Schema；严格类型可阻止 bool-as-int 和未知字段 |
| `ApprovedCandidate` | 部分满足 | 保存 requested/approved、来源、metric、风险、fingerprint；但任务书要求的原始提议、完整参数集、参数 diff、预计资源、生成时间、model/prompt/index hash 并未全部包含在该模型本身，部分散落于 proposal/lineage/report |
| `RoundRecord` | 部分满足 | 独立 `OptimizationLoop` 有较完整 `LoopRoundRecord`；主控制器的 `RoundRecord` 只有简化字段，且 round 1 结束时没有 comparison/incumbent after |
| `RunState` | 部分满足 | 独立模块合计覆盖大部分状态；公开 `assemble` 使用的 `AssemblyState` 只有 INPUT_VALIDATION、BASELINE_EXECUTION、BASELINE_EVALUATION、CANDIDATE_EXECUTION、REPORT |
| hifiasm 参数白名单 | 满足 | `purge_level`、`purge_similarity`、`hom_cov`、`disable_post_join`，类型和范围明确 |
| None/布尔/重复 flag/反向解析 | 满足 | `_append_optional_nextflow_param` 省略 None；contract parser 有正向、边界和历史 `--hom-cov true` 回归测试 |
| 每次 assembly 的六份契约文件 | 部分满足 | candidate 完整；baseline 只有 command/manifest/version 等，不满足“每次组装”逐字要求 |

### 6.5 V2 RAG/LLM

该部分是当前实现较强的模块之一：

- 知识源有 allowlist、内容 SHA-256、tool/version、evidence level、authorization scope 和 review date；
- 每个白名单参数都有官方授权证据；
- prompt injection chunk 会隔离；
- LLM 只收到结构化、路径脱敏摘要；
- 输出限制为严格 JSON/Pydantic Schema；
- 未检索 source、未知 metric、未知参数、非法范围、flag/shell/path/env token、过高 confidence 会被拒绝；
- `require_llm` 的失败停止和非必需 LLM 的规则降级均已实现；
- LLM 无法静默覆盖规则 STOP，也无法直接执行 shell。

主要问题不是 RAG/LLM 安全实现，而是 `assemble` 没有调用这一层。当前用户必须手工执行 `propose`，再把 `ApprovedCandidate` 交给 `execute-candidate`。

### 6.6 V2 多轮优化

`OptimizationLoop` 本身具备：

- incumbent 驱动的每轮 context；
- 1～3 轮和每轮 1～2 candidate；
- 参数 fingerprint 全局去重；
- CPU/walltime 预测与预留；
- 每个候选完成后计费；
- material improvement、Pareto、plateau、conflict、missing metric、execution failure、max-round 停止；
- round 2 中断后恢复且不重跑 round 1。

但需注意两个严格差距：

1. `OptimizationLoop` 没有生产 CLI/统一控制器调用点；`src/hifi_agent/cli.py` 只 import 了分阶段入口，没有实例化该 loop。
2. 三轮测试中的 provider 和 runner 是 `ScriptedProvider`/`ScriptedRunner`（`tests/test_stage9_optimization_loop.py:107-167`），证明的是 loop 算法，不是任务书所说的真实主控制器 round 02/03 执行路径。

另外，V2 预算只实际覆盖 CPU/walltime 和 candidate limit；任务书列出的 `max_total_assemblies`、`max_tool_retries`、`min_free_disk_gb`、每轮/全局 LLM 调用预算没有形成一个统一生产 ledger。

### 6.7 V2 历史不可覆盖与产物布局

`CandidateExecutor` 的隔离实现符合预期：

```text
02_assembly/round_01/candidate_01/attempt_001/workflow/...
02_assembly/round_01/candidate_01/attempt_002/workflow/...
```

失败 attempt 不覆盖，retry 创建新 attempt，artifact inventory 和 checksum 会冻结。

但公开 `assemble` 走的是另一条路径：

- `ExecutingAssemblyTools.execute_candidate()` 调用 `run_candidate_workflow(run_dir, candidate)`，未传 `execution_run_dir`；
- Nextflow 仍发布到 `02_assembly/<candidate_run_id>` 和 `03_post_qc/<candidate_run_id>` 的平铺 V1 目录；
- `AttemptHistoryStore` 在 round/candidate/attempt 目录中只写 identity/manifest，并引用平铺目录里的真实文件（`src/hifi_agent/orchestration/controller.py:121-145`）；
- 因而主命令的 attempt 目录不是 candidate 的自包含执行目录。checksum 能发现后续漂移，但不能等同于物理隔离、不可覆盖的 attempt 历史。

这是 CandidateExecutor 与主控制器尚未统一造成的结构性差距。

### 6.8 V2 报告与输出目录

`report-v2` 可生成结构较完整的 Markdown/JSON/TSV 报告，并显示：

- terminal outcome 和最终推荐；
- baseline、失败和完成 attempt；
- requested/approved/realized 参数；
- parameter contract；
- RAG/LLM provider/model/hash；
- 全部运行、资源、限制和默认路径脱敏。

但是：

- `report-v2` 要求用户手工提供 `stage7-root`、comparison、loop-state、proposal 等多个路径；
- `assemble` 只输出 `06_report/v2_stage3_summary.json`，不输出 `final_report.md`、`final_summary.json`、`all_runs.tsv`、`all_parameters.tsv`；
- 当前真实 Ziziphus `assemble` 结果也只有 Stage 3 summary；
- V2 任务书指定的 `00_metadata/environment_manifest.json`、`00_metadata/run_identity.json` 未由主 baseline 流程按该位置统一生成；run identity 实际位于 `05_agent/v2`。

因此报告器本身较完整，主命令和目录契约不完整。

### 6.9 V2 阶段任务总结

| 阶段 | 当前状态 | 结论 |
|---:|---:|---|
| 0 需求冻结/缺陷登记 | 满足 | scope、known defects、ADR、历史基线存在 |
| 1 参数传递/命令契约 | 满足（candidate） | None 漂移、bool-as-int、历史 Candida 缺陷检测已修复；baseline 六件套仍缺 |
| 2 Schema/身份/历史 | 部分满足 | identity、attempt、checksum、并发锁存在；主 assemble 未使用自包含 attempt workflow |
| 3 统一控制器/CLI | **不满足最终目标** | 只做到 baseline + 第一候选 Stage 3，没有完整闭环 |
| 4 QC feature | 满足 | 结构、单位、confidence、来源、脱敏完整 |
| 5 RAG 治理 | 满足 | catalog、hash、version、stale、authorization、injection 防护完整 |
| 6 LLM proposer | 满足（独立组件） | typed proposal 和 arbiter 完整；未接 assemble |
| 7 candidate executor | 满足（独立组件） | 隔离、契约、同源 post-QC、失败保留、retry 完整 |
| 8 comparator | 满足（独立组件） | hard regression、Pareto、plateau、冲突和适用性完整 |
| 9 三轮闭环 | 部分满足 | production loop 类存在；只有 scripted fixture 证明三轮；未接公开控制器 |
| 10 V2 报告 | 满足（手动组件） | 报告内容完整；未由 assemble 自动生成 |
| 11 benchmark/消融 | 部分满足 | portable/safety/历史真实报告存在；当前真实验收重跑失败 |
| 12 文档/迁移/release | 部分满足 | 文档、wheel、tag、历史 acceptance 存在；README/schema/example/env 与当前实现有漂移 |

## 7. 关键问题清单

### P0：阻断 V2 任务书验收

#### P0-01：`assemble` 不是统一端到端控制器

证据：

- CLI 描述为“first bounded candidate orchestration path”；
- 主状态机没有 RAG_RETRIEVAL、LLM_PROPOSAL、SAFETY_REVIEW、ROUND_COMPARISON、round 2/3 等状态；
- candidate 执行后直接写 `CANDIDATE_EXECUTED_STAGE3`；
- comparison 明确 deferred；
- 最终只生成 Stage 3 JSON summary。

影响：直接违反 V2 总目标、功能成功标准 1、阶段 3/9/10 和最终验收 17.2。

#### P0-02：当前真实验收不可重放且实际失败

当前显式真实 integration 结果为 14 failed、2 skipped。主要缺失：

- `Data/Candida_albicans/hifiAgent/00_metadata/input_checksums.tsv`；
- Candida baseline `assembly_metrics.json`；
- 历史 V1 `results/Candida_albicans_phase6` 完整目录；
- bin reuse 与部分 decision artifacts。

这不证明历史运行是伪造的；64 GB candidate 目录、contract、actual argv、post-QC 和历史验收摘要仍在。但它证明当前发布证据链不完整，无法满足“当前真实集成验收不是 skipped/failed”。

#### P0-03：三轮只在独立 scripted loop 中成立

三轮算法通过 fixture，但任务书的发布标准要求统一真实控制器能够生成 `round_02` 和 `round_03`。当前公开控制器硬编码第一轮、第一候选，未消费 `OptimizationLoop`。

### P1：高优先级工程/审计差距

#### P1-01：`OptimizationConfig` 只校验、不驱动生产执行

- `max_rounds`、`decision_mode`、`require_llm` 等字段有 Schema；
- `assemble` 不读取它们；
- 任务书示例 `hifi-agent assemble sample.yaml --decision-mode hybrid --resume` 当前不被 CLI 支持；
- `assemble` 也没有 LLM provider/required failure 语义。

#### P1-02：主控制器的 attempt 历史不是自包含 candidate 目录

独立 CandidateExecutor 正确，主 `AssemblyController` 仍执行平铺 candidate，再由 attempt manifest 外部引用。需要统一到 CandidateExecutor。

#### P1-03：统一预算不完整

缺少 production 级统一控制：

- `max_total_assemblies<=7`；
- `min_free_disk_gb`；
- 每轮/全局 LLM call budget；
- 与三轮 loop 统一的 tool retry；
- 从 incumbent 真实资源消耗自动推导下一候选预算并写同一 ledger。

#### P1-04：当前环境不满足任务书原样质量命令

`environment.yml` 固定 OpenJDK 21，但当前 `hifiAgent` env 实际列出 OpenJDK 25.0.2；`conda run -n hifiAgent nextflow -version` 失败。项目 wrapper 因本机 `/home/gw/software/jdk21` 存在而可工作，说明当前运行依赖宿主 fallback，不是完全自包含环境。

此外，当前 conda env 中若干工具实际来自 `/home/gw/software` 而非环境锁定；samtools 实际版本也与 `environment.yml` 不同。应生成并核对真正的 environment manifest。

#### P1-05：发布文档与当前代码/证据不一致

- README 示例中的 `optimization.allow_multi_parameter_candidates` 不在 `OptimizationConfig`，因 `extra="forbid"` 会被拒绝；
- `examples/candida_sample_config.yaml` 相对路径缺少 `Data/` 且使用 `HIFI`，当前真实文件为 `Data/.../HiFi.fastq`；
- README 宣称 V2 最多三轮闭环，但 CLI help 同时承认 `assemble` 只是第一候选路径；
- 历史 Stage 12 文档称选定的 4 个真实测试 4/4 通过，当前相同测试依赖的 source baseline 已缺失。

### P2：中低优先级差距

#### P2-01：输出目录契约不统一

- V1 `05_report`、V2 `05_agent`/`06_report` 与 README 中的目录描述混用；
- run identity 实际在 `05_agent/v2`，不是任务书指定的 `00_metadata`；
- baseline contract artifacts 不完整；
- `software_versions.tsv` 不是 baseline 的固定 `00_metadata` 产物。

#### P2-02：输入类型规则为固定事实

规则 `INPUT_NOT_HIFI_STOP` 存在，但生产上下文将 `input_type` 固定为 `pacbio_hifi`。系统实际信任用户把 reads 放入 `hifi_reads` 字段，而不是从 read metadata 验证测序类型。报告和文档应明确这是“用户声明”，避免声称自动识别 HiFi。

#### P2-03：工具与路径可移植性

工作流包含多处 `/home/gw/software/...` 和 `/data/gw/BUSCO` fallback/default。Conda 环境存在时优先使用 PATH，安全风险有限，但 clean host 上的行为和任务书“依据环境文件复现”仍需验证。

## 8. 建议整改顺序

### 第一优先级：完成真正的 V2 主链

1. 将 `AssemblyController` 扩展或重构为唯一生产控制器：

   ```text
   validate → pre-QC → baseline → rule/RAG/LLM proposal
   → arbiter → CandidateExecutor → post-QC → RoundComparator
   → incumbent update/plateau/stop → round 2/3 → render_v2_report
   ```

2. `assemble` 读取并实际执行 `config.optimization`：

   - `enabled`；
   - `max_rounds`；
   - `max_candidates_per_round`；
   - `decision_mode`；
   - `require_llm`；
   - risk confirmation；
   - retain attempts。

3. 为 `assemble` 增加任务书承诺的 `--decision-mode` override，并记录 config/CLI 的解析优先级。
4. 用 `CandidateExecutor` 替换主控制器的平铺 `run_candidate_workflow` 路径。
5. 由主控制器直接实例化 `OptimizationLoop`，不要让用户手工拼接 `propose`、`execute-candidate`、`compare-stage7`、`report-v2`。

### 第二优先级：修复真实验收链

1. 重新生成或恢复一个稳定的、checksum 完整的真实 baseline 根目录；
2. 不让测试硬编码依赖可能被清理的 ignored 绝对路径；可通过版本化 manifest + 配置的 external artifact root 解析；
3. 对现有 Candida `attempt_002` 重新校验 source checksum、contract、post-QC homology 和 inventory；
4. 至少运行一次当前 HEAD 的 baseline + 单变量 candidate；
5. 显式执行选定的 V2 real suite，并保存当前日期、commit、输入 checksum 和测试输出；
6. 真实 LLM 不必每次付费调用，但保留 receipt 的 hash 必须能绑定当前 index/prompt/schema。

### 第三优先级：补全预算、历史和报告

1. 新增统一 `BudgetLedgerV2`，覆盖 assemblies、tool retries、CPU、walltime、disk、LLM calls；
2. 每次 launch 前原子预留，完成后按真实消耗结算；
3. optimization trace 改为真正 append-only 或实现 state/trace crash-window 修复；当前 loop 每次重写整份 JSONL（`src/hifi_agent/optimization/loop.py:405-412`）；
4. baseline 同样生成 requested/approved/rendered/realized/contract artifacts；
5. `assemble` 终态自动生成完整 `06_report`，失败终态也生成；
6. 对目录契约写自动化 tree acceptance test。

### 第四优先级：修正文档和环境

1. 删除 README 无效字段 `allow_multi_parameter_candidates`，换成实际 Schema；
2. 修正示例配置路径和文件名大小写，增加一个 Git 内小 FASTQ quickstart；
3. 在 CI 中真正执行 README 中至少一条配置验证和 `assemble --stop-after` fixture；
4. 重建 `hifiAgent` env，确保 `conda run -n hifiAgent nextflow -version` 直接成功；
5. 将 GenomeScope、R 和期望的 coverage 工具纳入环境锁定；若正式接受 bedtools fallback，则同步修改任务书/文档；
6. 生成 `environment_manifest.json`，比较声明版本与实际版本并在不一致时警告或停止。

## 9. 建议的最终验收门禁

整改后，至少应在同一 commit 上通过：

```bash
conda run -n hifiAgent ruff check .
conda run -n hifiAgent ruff format --check .
conda run -n hifiAgent mypy
conda run -n hifiAgent pytest --cov --cov-report=term-missing --cov-fail-under=85
conda run -n hifiAgent nextflow -version
```

以及不可跳过的真实/端到端门禁：

```bash
HIFI_AGENT_REAL_ACCEPTANCE=1 \
  conda run -n hifiAgent pytest tests/integration -ra

hifi-agent assemble sample.yaml --decision-mode rules_only --resume
hifi-agent assemble hybrid_sample.yaml --decision-mode hybrid --resume
```

需要保存并自动检查：

- 主命令 baseline 直接接受场景；
- round 1 改善场景；
- round 1 改善、round 2 plateau 场景；
- fixture 的 round 1/2/3 连续改善和 round 2 resume；
- 至少一个当前 HEAD 的真实 baseline + candidate；
- `None` 不进入 argv；
- approved == rendered == realized；
- hard regression 不被 N50 覆盖；
- 所有 attempt 不覆盖；
- 最终 Markdown 可从参数追溯到实际 argv、指标源文件和 checksum。

## 10. 最终意见

本项目不是“只有设计没有实现”。相反，输入验证、QC、组装、post-QC、规则、参数契约、RAG/LLM 安全、候选隔离、比较策略和报告器都已经有相当扎实的代码与测试，portable 工程门禁表现良好。

当前未达标的核心原因也很集中：

> **V2 已经把端到端闭环所需的零件做出来了，但公开主控制器仍停留在 Stage 3；真实发布证据链又在当前工作区中断。**

优先完成主控制器集成、恢复当前可重放的真实验收、统一 attempt 目录和预算/报告后，项目才可以严格宣称达到 V2 任务书。此前建议对外描述为“V2 staged implementation / component-complete prototype”，不要描述为“一个命令完成三轮真实闭环”。
