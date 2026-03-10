# FreshQuant Symphony Workflow Templates

本目录保存 FreshQuant 的 repo-versioned `Symphony` 正式 workflow 模板。

## 目标

- 固化正式 `Linear` 状态机
- 固化设计批准门
- 固化默认 `subagent + TDD` 方法论
- 让仓库治理与 `Symphony` 运行模板保持一致

## 当前约束

- tracker：`Linear`
- 感知方式：默认 `30s` 轮询
- secrets：**不入仓**
- 正式工作流文件：`WORKFLOW.freshquant.md`
- 阶段 prompt：
  - `prompts/todo.md`
  - `prompts/in_progress.md`
- 审批评论模板：
  - `templates/human_review_comment.md`
- 正式宿主机脚本：
  - `scripts/freshquant_runner.exs`
  - `scripts/start_freshquant_symphony.ps1`
  - `scripts/sync_freshquant_symphony_service.ps1`
  - `scripts/install_freshquant_symphony_service.ps1`

## 使用说明

- 本目录中的文件是 **版本化模板**
- 真实运行时的 `LINEAR_API_KEY`、project slug、GitHub/Codex 凭据通过环境变量或外部安全注入提供
- 当前不强制先接 webhook，继续使用 30 秒轮询
- 宿主机正式运行说明见：`docs/agent/Symphony宿主机服务部署说明.md`
