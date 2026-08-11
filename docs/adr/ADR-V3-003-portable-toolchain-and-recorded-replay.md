# ADR-V3-003：可执行 portable toolchain 与 recorded LLM replay

- 状态：Accepted
- 日期：2026-08-10
- 决策范围：V3 portable acceptance

## 背景

注入 `ScriptedRunner` 能测试状态机，却不能证明 CLI、环境预检、命令启动、信号退出码、磁盘布局和
生产 parser 共同工作；在线 LLM 又会引入网络、密钥和付费依赖。

## 决策

1. portable suite 把独立可执行副本配置到 `tools.executable_overrides`；
2. fixture `nextflow` 接受生产 argv，并只通过磁盘生成生产 runner 要求的 pre-QC/assembly/post-QC；
3. suite 必须通过真实 CLI 子进程运行 baseline 与三轮 candidate；
4. SIGINT/SIGTERM 退出码归类为 interruption，resume 复用同一 attempt/cache；
5. `optimization.llm_replay_transcript` 是 hybrid-only、路径解析、输入 checksum 和 immutable config
   绑定的高级离线审计输入；
6. replay response 唯一绑定 round，仍生成正常 receipt 并经过 Schema/Safety Arbiter；
7. fixture 证据只接受阶段 8 wiring，不替代真实数据或 live LLM 阶段 9。

## 后果

- clean clone 可以无大型数据、网络或 API key 完成三轮生产 wiring；
- 可稳定验收退出码 0/3/4/5 与 report contract；
- fixture 必须跟随生产 argv/artifact contract 更新；
- transcript 含模型输出，必须像其他输入一样审计来源和 checksum。
