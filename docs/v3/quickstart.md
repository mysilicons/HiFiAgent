# V3 Quickstart

## Portable 闭环

在 Python 3.12 环境安装开发依赖后运行：

```bash
python scripts/run_portable_demo.py --workspace /tmp/hifi-agent-portable --scenario three-rounds
```

脚本创建一个最小 FASTQ、显式 executable overrides 和原生 `schema_id: "hifi-agent"` 配置，随后通过
真实 CLI 子进程调用生产 `RunCoordinator`、`NextflowAssemblyRunner` 与文件解析器。预期
`exit_codes: [0]`，终态为 `STOP_MAX_ROUNDS`，共有 baseline 加三次 candidate。可用以下命令复验：

```bash
python -m hifi_agent verify-run /tmp/hifi-agent-portable/run --deep
```

另有 `llm-replay`、`resume`、`human-review` 和 `tool-failure` 场景用于开发验收。fixture 只验证
wiring、恢复、契约和报告，不能替代真实数据验收。

## 真实运行

1. 复制 `examples/candida_sample_config.yaml`，将 reads、reference、outdir 和资源改为本机值；
2. 用 `hifi-agent validate sample.yaml` 生成输入 checksum 和验证 receipt；
3. 用 `hifi-agent plan sample.yaml` 完成只读环境预检；
4. 用 `hifi-agent assemble sample.yaml` 运行；
5. 中断后只对同一个 YAML 使用 `--resume`；
6. 结束后运行 `hifi-agent verify-run RUN_DIR --deep`。

不要把 fixture 的指标或 `STOP_MAX_ROUNDS` 当作生物学结论。真实结果应按
[结果解释](result_interpretation.md)审阅。
