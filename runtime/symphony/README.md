# FreshQuant Symphony Workflow Templates

本目录保存 FreshQuant 的 repo-versioned `Symphony` 正式 workflow 模板。

## 目标

- 固化正式 `Linear` 状态机
- 固化设计批准门
- 固化默认 `subagent + TDD` 方法论
- 固化 `Merging` 自动部署、cleanup 与 `Done` 判定
- 让仓库治理与 `Symphony` 运行模板保持一致

## 当前约束

- tracker：`Linear`
- 感知方式：默认 `30s` 轮询
- secrets：**不入仓**
- 正式工作流文件：`WORKFLOW.freshquant.md`
- 阶段 prompt：
  - `prompts/todo.md`
  - `prompts/in_progress.md`
  - `prompts/merging.md`
- 审批评论模板：
  - `templates/human_review_comment.md`
- PR 结果评论模板：
  - `templates/pr_completion_comment.md`
- 部署评论模板：
  - `templates/deployment_comment.md`
- 正式宿主机脚本：
  - `scripts/run_freshquant_codex_session.ps1`
  - `scripts/freshquant_runner.exs`
  - `scripts/request_freshquant_symphony_cleanup.ps1`
  - `scripts/invoke_freshquant_symphony_cleanup_finalizer.ps1`
  - `scripts/start_freshquant_symphony.ps1`
  - `scripts/sync_freshquant_symphony_service.ps1`
  - `scripts/install_freshquant_symphony_service.ps1`

## 使用说明

- 本目录中的文件是 **版本化模板**
- 真实运行时的 `LINEAR_API_KEY`、project slug、GitHub/Codex 凭据通过环境变量或外部安全注入提供
- 当前不强制先接 webhook，继续使用 30 秒轮询
- 正式运行继续使用**单实例 orchestrator + 按状态并发**：
  - `Todo=1`
  - `In Progress=2`
  - `Rework=1`
  - `Merging=1`
- 只有实现阶段允许双并发；设计、返工和部署阶段保持保守串行
- `Merging` 阶段负责 merge、按变更矩阵执行部署、部署后健康检查和 cleanup；只有 cleanup 成功才能进入 `Done`
- `Human Review` 评论必须一次性列出全部待决策项、推荐方案与理由；未决项未清零前，不得进入 `In Progress`
- 进入 `Merging` 前必须在 Linear 留下 PR 结果评论
- 进入 `Merging` 后由 agent 先生成 cleanup request；宿主机 finalizer 会在 Codex 子进程退出后删除远端分支、删除 workspace、清理旧 artifacts，并写入最终 deployment comment
- 进入 `Done` 前必须在 Linear 留下包含 `Cleanup Results` 的最终部署评论
- 宿主机正式运行说明见：`docs/agent/Symphony宿主机服务部署说明.md`
