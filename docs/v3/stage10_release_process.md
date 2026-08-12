# 阶段 10 发布与 clean-room 复验

阶段 10 只允许从干净、已提交且通过真实验收的代码生成发布资产。发布目录属于构建产物，不进入
Git；其 `acceptance_manifest.json`、`SHA256SUMS` 和 annotated tag 共同绑定源码、wheel、sdist 与真实
运行证据。

## 发布顺序

1. 运行 Ruff、format、mypy、普通 pytest、核心 branch coverage 和真实 Nextflow resume 测试；
2. 构建 wheel/sdist，并从隔离安装的 wheel 运行 portable 三轮闭环；
3. 在 clean clone 中重新安装并重复 portable、workflow 和旧接口拒绝门禁；
4. 在同一 commit 上完成真实 baseline/candidate、deep/real verifier、live provider smoke 和零跳过
   real suite；
5. 生成 evidence bundle，要求 commit、wheel、source config、input、environment、live receipt 和真实
   JUnit report 的哈希一致；
6. 创建 annotated release tag；
7. 生成 `release/v3.0.0/`，校验 tag、HEAD、run identity、evidence manifest 和发行包版本完全一致。

## 硬性拒绝

- 工作树不干净、tag 不指向 HEAD 或 run commit 不等于 HEAD；
- wheel 缺少 Python source、Nextflow、comparison policy 或 governed knowledge；
- 旧 schema/旧字段被接受，或 CLI 出现迁移、reader、export、旧执行入口；
- portable/real suite 出现 failed、error 或 release-only skip；
- verifier、secret scan、Schema、Safety Arbiter 或 evidence bundle 任一不为 PASS；
- 发布说明声称候选已改善、全局最优或临床适用。

## 发布边界

本发布仅覆盖单样本 PacBio HiFi、Linux x86_64、hifiasm 和冻结参数白名单。无参考时 QUAST
misassembly 指标不可用；使用同一 HiFi reads 的 Merqury 仅为 advisory；真实果蝇验收不能代表所有
物种、倍性、覆盖度和复杂度。任何临床、诊断、多租户或 SLA 用途均需独立验证与治理。
