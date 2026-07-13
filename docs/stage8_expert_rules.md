# 阶段 8 专家规则标准

## 设计目标

规则引擎只做三种确定性结论：保留 `BASELINE`、安全 `STOP`、或提出有限 `RETRY` 候选。
它不调用 LLM、不执行候选命令，也不根据单一 N50 或单一 k-mer 信号修改参数。

阈值配置位于 `configs/thresholds.yaml`，规则位于 `rules/v1_rules.yaml`。两者分别具有独立
版本，加载时交叉校验。每个阈值都声明 warning/action/acceptance 层级、来源、来源版本和
说明。数值阈值属于 HiFi Agent V1 保守专家共识，不应被解释为 hifiasm、BUSCO 或 QUAST
官方推荐阈值。

## 专家阈值

| 信号 | Warning | Action/Acceptance | 专家解释 |
|---|---:|---:|---|
| 估计 coverage | `<20×` | `<15×` 停止搜索 | 低覆盖时参数搜索容易拟合噪声 |
| assembly-size ratio | `>1.15` | `>1.25` 才考虑偏大动作 | 必须结合 duplication，不单独 purge |
| assembly-size ratio | — | `<0.80` 视为强异常 | 与高 duplication 同时出现时判为冲突 |
| BUSCO duplicated | `>5%` | `>10%` 强信号 | 只有与 size 同向时允许 purge 候选 |
| BUSCO complete | — | `≥95%` baseline 接受条件 | 通用 V1 下限，不替代谱系判断 |
| k-mer completeness | — | `≥90%` baseline 接受条件 | 同源 HiFi 来源仍保留 limitation |
| filtered-read mapping | — | `≥95%` baseline 接受条件 | 防止只凭 contiguity 接受结果 |
| hom-cov / k-mer peak | — | `>1.5` 或 `<2/3` | 仅同源 HiFi、模型成功且无峰形 warning 时可触发 |
| reference-based misassembly | — | `>10/100 Mb` 且 N50 `≥1 Mb` | 仅 reference-based QUAST 可触发 `-u0` |

## 参数候选标准

候选参数严格限制为：

- `purge_level`：仅 `inbred=true` 可产生 `-l0`；
- `purge_similarity`：size ratio `>1.25` 且 BUSCO D `>10%` 时，最多产生一个 `-s0.50`；
- `hom_cov`：只从同源 HiFi 的清晰单峰动态取整；独立 Illumina 深度不与 HiFi hom-cov 直接比较；
- `disable_post_join`：只有 reference-based 结构错误证据充分时产生 `-u0`。

本机 hifiasm 0.25.0-r726 帮助信息显示：unzip 默认 purge level 为 3，其 `-s` 默认值为
0.55；`-l0` 表示不 purge；`--hom-cov` 覆盖自动推断；`-u0` 关闭 post-join。将 `-s` 降至
0.50 可能清除更多相似 haplotig，因此被定为中高风险，并要求 size 与 BUSCO duplication
双证据。任何候选都只输出结构化参数，不拼接或执行 shell。

## 优先级与冲突策略

1. 非 HiFi、非二倍体、工具失败、低覆盖等安全停止规则优先级最高；
2. 显式多指标冲突和核心指标缺失优先于任何 retry；
3. 候选规则按证据风险排序，每轮只采用最高优先级规则；
4. 同优先级规则若 decision、action 或同一参数值冲突，强制转为 `STOP`；
5. 全局候选上限为 2，每条当前 V1 规则最多输出 1 个候选；
6. 没有任何规则命中时返回 `STOP_INSUFFICIENT_EVIDENCE`，不猜测。

## V1 规则清单

当前规则集共 14 条：输入类型、倍性、评价失败、低覆盖停止、低覆盖警告、多指标冲突、核心指标缺失、
size+duplication 同向、size 偏大但 duplication 低、结构错误、hom-cov 冲突、genome-size
未知、inbred `-l0`、总体正常接受 baseline。

每条规则均有至少两个正向和两个反向用例；此外测试覆盖边界值、阈值来源、确定性、
冲突降级、动态候选、未知参数拒绝和 baseline/stop/retry 三类输出。
