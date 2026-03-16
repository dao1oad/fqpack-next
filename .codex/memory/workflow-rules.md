# 工作流规则

- `GitHub PR + CI + merge gate` 是代码交付真值；允许直接走 `feature branch -> PR`。
- 高影响、破坏性或需要 stewardship 跟踪的工作，应先创建 GitHub Issue。
- 对 `Symphony` 管理的任务，GitHub Issue 是正式任务入口，也是执行合同。
- `deploy + health check + cleanup` 是运行交付真值；如果某一轮发生了真实部署，关闭前还必须完成 runtime ops check。
- 上面三条真值面共同构成正式真值；memory 只负责提供启动引导。
- Issue body 应提前写清背景、目标、范围、非目标、验收标准和部署影响。
- 正式工作流里不再存在独立的设计审批或人工批准关卡。
- 正式的 issue-managed 状态流固定为 `Issue -> In Progress -> Rework -> Merging -> Global Stewardship -> Done`；`Blocked` 只用于真实外部阻塞。
- `Rework` 只处理 merge 前、仓库内、可确定复现的问题；merge 后的部署或运行问题不能回退到 `Rework`。
- 不要在本地 `main` 上做任务开发；必须使用 feature branch 和 PR。若任务由 `Symphony` 管理，则使用该 issue 对应 branch 与 PR。
- `Global Stewardship` 负责 issue-managed 任务的 deploy、health check、runtime ops check、cleanup 和后续 issue 创建。
- 如果 merge 后发现需要代码修复，应创建或复用后续 issue；不要直接从 `Global Stewardship` 新建修复 PR。
- memory context 只是启动辅助信息，不能覆盖 GitHub 状态、`docs/current/**` 或真实 deploy 证据。
