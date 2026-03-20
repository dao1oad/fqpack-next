# 工作流规则

- `GitHub PR + CI + merge gate` 是代码交付真值；允许直接走 `feature branch -> PR`。
- 高影响、破坏性变更应先建 GitHub Issue。
- 正式运行真值是“最新远程 `main` + formal deploy + health check + runtime ops check”。
- 默认工作流是 `local session -> feature branch -> PR -> merge remote main -> deploy`。
- 本地会话只负责开发、测试和预检查，不是正式 deploy 真值。
- formal deploy 只能基于最新远程 `main` 已合并 SHA。
- `deploy + health check + cleanup` 是运行交付真值；如果某一轮发生了真实部署，关闭前还必须完成 runtime ops check。
- 上面三条真值面共同构成正式真值；memory 只负责提供启动引导。
- Issue body 应提前写清背景、目标、范围、非目标、验收标准和部署影响。
- 不要在本地 `main` 上做任务开发；必须使用 feature branch 和 PR。
- 如果 merge 后发现需要代码修复，应创建或复用后续 issue。
- memory context 只是启动辅助信息，不能覆盖 GitHub 状态、`docs/current/**` 或真实 deploy 证据。
