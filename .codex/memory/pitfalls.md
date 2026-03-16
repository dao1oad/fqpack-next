# 常见陷阱

- 不要把 merge 误判成 `Done`；deploy、health check 和 cleanup 仍然是完成门槛。
- 不要让 `Global Stewardship` 直接创建修复 PR；代码问题应进入后续 issue。
- 不要把每个小改动都强行塞进 issue 状态机；`Symphony` 之外允许直接走 `feature branch -> PR`。
- 不要把 merge 后的 deploy 或 runtime 故障回退到 `Rework`；它们属于 `Global Stewardship` 的后续处理范围。
- 不要把 pending 的 GitHub checks 当成 `Rework`；`Merging` 应等待 GitHub 真值变化。
- 不要直接在本地 `main` 上工作；必须使用 feature branch 和 PR。若任务由 `Symphony` 管理，则使用确定性的 issue branch。
- 当 issue 状态、branch 和 memory context 已经明确后，不要重新全仓扫描整个仓库。
- 如果 memory context 与最新 GitHub 或运行证据冲突，应以正式真值为准，并重新刷新 memory。
