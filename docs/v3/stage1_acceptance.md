# V3 阶段 1 严格验收报告

- 验收日期：2026-08-10
- 基线 commit：`1786dcd3cd5b8ecae20b767a5a0c7328656bac6a`
- 验收 worktree：`DIRTY`（阶段 0～2 实现尚未提交）
- 阶段结论：`ACCEPTED`

## 功能出口

- native V3 配置强制 `schema_id: hifi-agent` 与显式 `read_technology: pacbio_hifi`；
- 旧字段和未知字段 fail closed，并生成 CLI/config/default 来源映射；
- `ExecutionBudgetConfig`、三种 decision mode、LLM 约束和 assembly 上限已覆盖边界测试；
- `OptimizationConfig` 全部字段编译为生产 execution policy，required LLM 非 hybrid 时
  fail closed；
- `plan` 只读，README 示例和 Candida 示例均通过实际命令；
- `assemble --decision-mode`、`verify-run` 帮助与 Schema 一致，旧命令不存在；
- environment preflight 记录 Python/agent/CPU/内存/临时目录/磁盘和完整工具链；
- `environment.yml` 锁定 OpenJDK 21、Nextflow 25.04.7、GenomeScope 2.0.1/R 4.3 和 QC 工具；
- production workflow、executors 和验收脚本不再包含个人工具目录或 `/data/gw/BUSCO` fallback。

## 实际命令证据

| 命令 | 结果 |
|---|---|
| `conda run -n hifiAgent hifi-agent plan examples/candida_sample_config.yaml` | PASS，exit 0；未写 run artifact |
| `conda run -n hifiAgent nextflow -version` | PASS，25.04.7 build 5955 |
| `conda run -n hifiAgent java -version` | PASS，OpenJDK 21.0.8 |
| real preflight | Java/Nextflow/hifiasm/gfatools/SeqKit/NanoPlot/meryl/QUAST/BUSCO/Merqury/minimap2/samtools/R/GenomeScope/bedtools 全部 PASS |
| hidden fallback `rg` 扫描 | 0 match |
| `nextflow config workflow` | PASS |
| production old-surface 扫描 | PASS，旧脚本和旧 workflow entry 均已删除 |

Candida 示例的 preflight 状态为 `WARNING`，唯一原因是显式 BUSCO lineage 尚未预下载，运行时
需要受审计下载；这不是工具缺失或隐藏目录回退，`plan` 按契约成功。昂贵执行前仍会在 manifest
中保留 `BUSCO_LINEAGE_DOWNLOAD_REQUIRED`。
