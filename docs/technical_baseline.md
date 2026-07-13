# 技术基线

于 2026-06-25 在 `/data/gw/code/HiFiAgent` 中收集。

## 开发环境

- 目标操作系统：Linux。
- 所需工作流引擎：Nextflow DSL2。
- 所需 conda 环境名称：`hifiAgent`。
- 检测到的现有 conda 环境：`/home/gw/miniconda3/envs/hifiAgent`。
- `hifiAgent` 中的 Python：3.12.3。

## 服务器资源

- CPU 架构：x86_64。
- CPU 型号：AMD EPYC 9V94 128 核处理器。
- 插槽：2。
- 每插槽核心数：128。
- 每核心线程数：2。
- 逻辑 CPU：512。
- 内存：总计 1.0 TiB，收集时可用约 664 GiB。
- 交换空间：无。
- 项目路径的文件系统：`/dev/sda1`。
- 文件系统大小：102T。
- 已用：75T。
- 可用：22T。
- 使用率：78%。

## 当前工具状态

`hifiAgent` conda 环境存在，交互式 shell 中激活该环境后可以直接运行 Nextflow。

于 2026-06-25 验证：

- `conda run -n hifiAgent python --version` 报告 Python 3.12.3。
- 交互式 shell 中执行 `conda activate hifiAgent; which java` 返回 `/home/gw/software/jdk21/bin/java`。
- 交互式 shell 中执行 `java -version` 报告 OpenJDK 21.0.8。
- `/home/gw/software/nextflow -version` 报告 Nextflow 25.04.7 build 5955。
- 交互式 shell 中执行 `conda activate hifiAgent; nextflow -version` 成功。
- `workflow/main.nf` 可通过 local executor 成功运行。
- `workflow/main.nf -resume` 可成功复用缓存任务。

剩余注意事项：

- Codex 当前长驻进程曾继承旧环境变量，非交互 login shell 仍可能看到 `JAVA_HOME=/home/gw/software/jdk8` 和 `JAVA_CMD=/home/gw/software/jdk8/bin/java`。
- 如果某个非交互进程未重新读取更新后的 shell 配置，直接运行 `nextflow` 可能仍会失败；重新打开终端、重新加载 `.bashrc`，或显式设置 Java 21 可解决。
- 当前检测到的 Nextflow 可执行文件是 `/home/gw/software/nextflow`，不是安装在 `hifiAgent` conda 环境内的包。
- 当前代理变量使用 `socks5h://`，Nextflow 会提示这不是有效的 Java HTTP proxy；本地 workflow 执行不受影响。

## 推荐的环境修复

如果希望 Java 和 Nextflow 完全由 conda 管理，使用 `environment.yml` 作为预期的项目环境定义。环境名称固定为 `hifiAgent`。

建议的更新命令：

```bash
conda env update -n hifiAgent -f environment.yml
```

更新后验证：

```bash
conda run -n hifiAgent java -version
conda run -n hifiAgent nextflow -version
conda run -n hifiAgent python --version
```

当前交互式终端中的推荐验证方式：

```bash
conda activate hifiAgent
which java
nextflow -version
hifi-agent run --resume examples/candida_sample_config.yaml
```

如果遇到未重新加载 `.bashrc` 的非交互进程，可使用以下显式覆盖方式：

```bash
conda run -n hifiAgent env \
  JAVA_CMD=/home/gw/software/jdk21/bin/java \
  JAVA_HOME=/home/gw/software/jdk21 \
  hifi-agent run examples/candida_sample_config.yaml
```

## Git 状态

此工作目录包含 `.git` 目录条目，但 `git status` 报告它不是有效的 Git 存储库。远程 GitHub 存储库创建、问题标签、项目板设置和分支保护必须在本地第 0 阶段文件工作之外完成。
