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

1. 在 `configs/runtime.yaml` 中一次性设置 data/output/cache 根目录、128 线程、内存、预算和工具；
2. 复制 `configs/samples/Malus_domestica.yaml`，只修改 reads 和物种科学元数据；
3. 用 `hifi-agent plan configs/samples/Malus_domestica.yaml` 完成只读环境预检；
4. 用 `hifi-agent assemble configs/samples/Malus_domestica.yaml` 完整运行；
5. 中断后原样重发第 4 步命令，`resume_mode: auto` 会验证不可变证据并续跑；
6. 结束后运行 `hifi-agent verify-run results/Malus_domestica --deep`。

样本路径只能是全局 `data_root` 下的相对路径。首次运行若缺少声明的 BUSCO lineage，会在共享
`cache_root` 中加锁下载。标准保留策略只在 deep verification 为 `PASS` 后清除可再生的 work 目录。

不要把 fixture 的指标或 `STOP_MAX_ROUNDS` 当作生物学结论。真实结果应按
[结果解释](result_interpretation.md)审阅。
