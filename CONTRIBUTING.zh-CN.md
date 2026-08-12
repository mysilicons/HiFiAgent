# 参与贡献

[English](CONTRIBUTING.md) | **简体中文**

请使用 Python 3.12，并通过 `environment.yml` 创建环境或安装 `.[dev]`。科学决策必须保持确定性，
阈值和来源需要版本化；未经设计评审和测试，不得加入审计白名单之外的 hifiasm 参数。

提交变更前请运行：

```bash
ruff check .
ruff format --check .
mypy
pytest --cov --cov-fail-under=85
python scripts/run_portable_demo.py --workspace /tmp/hifi-agent-portable --scenario three-rounds
```

请勿提交 FASTQ/BAM/CRAM、组装数据库、BUSCO 下载、meryl 数据库、凭据或可识别个人身份的绝对
路径。新增规则至少需要两个正向测试和两个反向测试。
