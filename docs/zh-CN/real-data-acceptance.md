# 真实数据验收

[English](../real-data-acceptance.md) | **简体中文**

真实数据验收用于把外部数据 bytes、完成 run、比较结果、代码提交和发行 wheel 绑定为可复核证据。
仓库不包含真实数据、项目专用样本配置或固定物种注册表。

## 数据注册表

注册表由使用者保存在受控位置，数据本身位于 Git 之外。以下是 Schema 有效的中性模板；其中 hash、
字节数和科学事实必须替换为真实值：

```yaml
schema_id: hifi-agent
registry_id: private-acceptance-datasets
datasets:
  - dataset_id: acceptance_dataset
    species: Unspecified taxon
    taxon_id: 1
    read_technology: pacbio_hifi
    accession: USER_MANAGED_INPUT
    source_uri: https://example.invalid/reads
    source_archive: user-managed
    usage_policy: Authorized private acceptance input
    usage_policy_uri: https://example.invalid/policy
    approved_usage:
      - software acceptance
    locator:
      root_env: HIFI_AGENT_REAL_DATA_ROOT
      relative_path: sample/reads.fastq.gz
    bytes: 1
    sha256: "0000000000000000000000000000000000000000000000000000000000000000"
    read_count: 1
    total_bases: 1
    expected_genome_size: 1
    expected_genome_size_source: user-supplied evidence
    ploidy: 1
    inbred: null
    reference: null
    busco_lineage: eukaryota_odb12
    limitations:
      - Replace every placeholder before use
```

`root_env` 必须匹配 `HIFI_AGENT_[A-Z0-9_]+`，`relative_path` 不能是绝对路径或包含 `..`。注册表记录
source、usage policy、字节事实和科学事实，但不存 API key。

## 1. 校验外部 bytes

```bash
export HIFI_AGENT_REAL_DATA_ROOT=/path/to/data-root
hifi-agent check-dataset /path/to/datasets.yaml acceptance_dataset
```

只有本地文件字节数和完整 SHA-256 与注册表一致时通过。不要通过更新注册表 hash 掩盖意外变化；先
重新确认来源、传输和授权。

## 2. 运行并深度验证

使用与注册表事实一致的样本配置完成 baseline 和至少一个单变量候选，然后执行：

```bash
hifi-agent verify-run results/sample_001 --deep
hifi-agent verify-real \
  results/sample_001 \
  /path/to/datasets.yaml \
  acceptance_dataset
```

`verify-real` 要求：

- run 输入 checksum 与注册表一致；
- environment status 为 PASS，并有可验证 BUSCO lineage；
- baseline 和 candidate 都有比较资格；
- candidate 只改变一个批准参数；
- 两者使用相同 post-QC 协议；
- requested、approved、argv 和 realized 参数闭环；
- 必需 QC 指标存在；
- comparator 结果为接受候选或保留 incumbent；
- deep verification 为 PASS。

## 3. 外部服务烟雾测试

只有项目政策允许发送脱敏聚合上下文时执行：

```bash
export DEEPSEEK_API_KEY='set-in-your-secret-manager'
hifi-agent live-smoke results/sample_001 /path/to/live-smoke-output
```

目标输出目录必须是新的。manifest 记录 provider、model、Schema、安全仲裁和 hash，不记录 key。发送
边界见[配置与决策模式](decision-modes.md)。

## 4. 启用 release-only 测试

```bash
export HIFI_AGENT_REAL_ACCEPTANCE=1
export HIFI_AGENT_REAL_REGISTRY=/path/to/datasets.yaml
export HIFI_AGENT_REAL_DATASET_ID=acceptance_dataset
export HIFI_AGENT_REAL_DATA_ROOT=/path/to/data-root
export HIFI_AGENT_REAL_RUN=/path/to/completed-run
export HIFI_AGENT_LIVE_SMOKE_MANIFEST=/path/to/live-smoke-output/live_smoke_manifest.json

pytest -m real_acceptance \
  --junitxml=/path/to/real-suite.xml \
  tests/integration/test_real_acceptance.py
```

发行证据要求 tests、failures、errors、skipped 中后三项全部为 0；未显式设置
`HIFI_AGENT_REAL_ACCEPTANCE=1` 时，这些测试默认跳过，不会访问外部数据或服务。

## 5. 构建证据包

先从待验收提交构建 wheel，再运行：

```bash
hifi-agent build-evidence \
  results/sample_001 \
  /path/to/datasets.yaml \
  acceptance_dataset \
  --source-config configs/sample.yaml \
  --wheel /path/to/hifi_agent.whl \
  --live-manifest /path/to/live-smoke-output/live_smoke_manifest.json \
  --real-suite-report /path/to/real-suite.xml \
  --output-dir /path/to/evidence-bundle
```

证据包校验 wheel 的 package version、Python 源码和生产资源与当前源树字节一致，并绑定：注册表、源
配置、resolved/effective config、输入 manifest、environment manifest、live receipt、JUnit 报告、
run evidence hash 和代码提交。

## 安全与归档

- reads、assembly 和大中间文件始终留在受控存储；
- 对外只发布明确授权的小型脱敏证据；
- 注册表中的 source/usage policy 必须真实可追溯；
- 不在公共 issue、CI artifact 或 release 中上传 API key、私有路径或未授权数据；
- acceptance PASS 证明指定数据和指定提交满足这些门禁，不代表对所有数据集都适用。
