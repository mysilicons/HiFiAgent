# V3 任务板

| ID | 优先级 | Owner | 阶段 | 状态 | 出口证据 |
|---|---:|---|---:|---|---|
| V3-P0-01 | P0 | maintainer | 5 | ACCEPTED | public coordinator 12-scenario matrix |
| V3-P0-02 | P0 | maintainer | 2/5 | ACCEPTED | one state/journal through TERMINAL |
| V3-P0-03 | P0 | maintainer | 0/9 | IN_PROGRESS | run2 scientific PASS; clean-commit run/live/release evidence pending |
| V3-P0-04 | P0 | maintainer | 5/8 | ACCEPTED | executable toolchain + real CLI baseline/three-round/deep verification |
| V3-P1-01 | P1 | maintainer | 1/5 | ACCEPTED | runtime config fully consumed by coordinator |
| V3-P1-02 | P1 | maintainer | 3 | ACCEPTED | common executor + deep verifier |
| V3-P1-03 | P1 | maintainer | 2 | ACCEPTED | budget ledger/tamper tests |
| V3-P1-04 | P1 | maintainer | 2 | ACCEPTED | transaction fault tests |
| V3-P1-05 | P1 | maintainer | 6 | ACCEPTED | six canonical terminal reports + deep verifier |
| V3-P1-06 | P1 | maintainer | 3 | ACCEPTED | baseline/candidate six-piece contract tests |
| V3-P1-07 | P1 | maintainer | 1 | ACCEPTED | real preflight/environment gate |
| V3-P1-08 | P1 | maintainer | 1/8 | ACCEPTED | exact README portable command runs in subprocess suite |

状态只能在验收报告记录实际命令和结果后改为 `ACCEPTED`。本文不连接外部 issue tracker，
因此 ID 是仓库内稳定 issue key；未来迁移到 GitHub/Linear 时必须保留这些 key。

阶段 0～8 的阶段任务均已 ACCEPTED。阶段 9 的 registry、配置、真实 verifier、release-only suite、
live smoke 和 evidence builder 已实现。第一次真实 baseline 因 Merqury 根目录解析缺陷安全终止；失败
证据、修复和真实 Merqury smoke 已记录。run2 已完成真实 baseline、单变量 candidate、comparison、
deep verifier 和 real verifier，科学结论通过；但它运行于未提交工作树，live 外部调用也未获明确授权。
`V3-P0-03` 仍为 `IN_PROGRESS`，直到干净 commit 上的 run3、成功 live receipt、0-skip suite 和 bundle
产生实际证据。stage-8 fixture、run1 和 dirty-commit run2 均不能替代它。
