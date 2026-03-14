# FreshQuant Symphony Workflow Templates

本目录保存 FreshQuant 的 repo-versioned `Symphony` 正式 workflow 模板。

## 目标

- 固化 `GitHub-first` 轻量治理
- 固化 direct `feature branch -> PR` 轻量入口，以及 `Issue-managed` 的 `Symphony` 治理入口
- 固化 `Symphony` 到 merge 为止、`Global Stewardship` 接手 merge 后收口
- 固化 deploy、health check、runtime ops check、cleanup 与 `Done` 判定
- 让仓库治理与 `Symphony` 运行模板保持一致

## 正式真值

- GitHub Issue：对 `Symphony` 接管的 Issue-managed 任务，是正式任务入口，也是需求与方案真值
- GitHub PR + CI + merge gate：所有代码更新的代码交付真值；仓库允许 direct `feature branch -> PR`
- 单个全局 Codex 自动化完成的 `deploy + health check + runtime ops check + cleanup`：运行交付真值

`Linear` 不再作为正式任务入口、评审面或批准真值来源。

## 当前工作流

本目录只定义 `Symphony` 的 Issue-managed 工作流。仓库级轻量更新允许 direct `feature branch -> PR`，不强制先建 Issue。

Issue-managed 正式工作流固定为：

`Issue -> In Progress -> Rework -> Merging -> Global Stewardship -> Done`

例外状态仅保留：

`Blocked`

GitHub 文本规则：

- 所有提交到 GitHub 的正式说明默认使用简体中文
- 包括 Issue 描述、PR 标题与正文、PR / Issue 评论、部署说明、Done 总结

## Issue 即执行合同

- 对 `Symphony` 接管的任务，正式任务在进入 `In Progress` 前，方案应已在 Issue body 中明确
- Issue body 至少应包含：背景、目标、范围、非目标、验收标准、部署影响
- Symphony 不再管理 `Design Review` 或人工审批
- 如果 Issue 合同仍有事实缺口，Symphony 只补足执行所需事实，不额外创建审批环节

## 状态职责

- `In Progress`
  - 实现、测试、同步 `docs/current/**`
- `Rework`
  - 仅处理未 merge 前的确定性仓库内修复
- `Merging`
  - 一次性检查 GitHub PR 真值、merge、写 handoff comment、转入 `Global Stewardship`
- `Global Stewardship`
  - 统一处理 deploy、health check、runtime ops check、cleanup、follow-up issue
- `Blocked`
  - 仅用于真实外部阻塞

`Rework` 进入时必须记录：

- `blocker_class`
- `evidence`
- `next_action`
- `exit_condition`

允许进入 `Rework` 的原因仅包括：

- `checks_failed`
- `review_threads_unresolved`
- `merge_conflict`
- `ruleset_policy_block`
- `docs_guard_failed`

不允许把以下情况记为 `Rework`：

- 等待人工审批
- 等待检查完成
- merge 后部署问题
- 外部权限或平台故障

## superpowers 执行链

- 普通 bugfix：
  - `using-superpowers`
  - `systematic-debugging`
  - `test-driven-development`
  - `verification-before-completion`

- 现有模块增强：
  - `using-superpowers`
  - `brainstorming`（仅用于本地梳理，不形成审批环节）
  - `test-driven-development`
  - `verification-before-completion`

- 跨模块或高影响改动：
  - `using-superpowers`
  - `brainstorming`（仅用于本地梳理，不形成审批环节）
  - `writing-plans`（必要时）
  - `test-driven-development`
  - `verification-before-completion`

## 正式文档

仓库正式文档只保留：

- `docs/index.md`
- `docs/current/**`

如果当前系统事实发生变化，必须在同一 PR 同步更新 `docs/current/**`。

## 部署与 Done

硬规则：

- 代码更新后，受影响模块必须重新部署
- 未部署完成，不算 `Done`
- merge 后的 deploy、health check、runtime ops check、cleanup 由单个全局 Codex 自动化统一收口

`Done` 的定义是：

- PR 已合并
- CI 通过
- `docs/current/**` 已同步
- 受影响模块已重新部署
- 健康检查通过
- cleanup 完成

即：

`Done = merge + ci + docs sync + deploy + health check + cleanup`

## Cleanup

Cleanup 只清理任务级资源：

- 删除已合并远端 `feature branch`
- 删除当前任务 workspace / repo copy
- 删除当前任务临时脚本、截图、scratch 文件、临时 artifacts

不清理共享运行资源：

- `.venv`
- Mongo / Redis 正式数据
- 正式日志目录
- 在线服务
- `docs/current/**`

## Global Stewardship

- `Merging` 只负责 merge 到 remote `main`、写 merge handoff comment，并把 issue 转入 `Global Stewardship`
- 单个全局 Codex 自动化统一巡检所有 `Global Stewardship` issue
- 全局自动化允许按当前 `main` 和部署面并集批量 deploy 多个 merged issue
- 如果发现需要代码修复的问题，全局自动化只创建 follow-up issue，不直接建修复 PR
- 原 issue 只有在 `deploy + health check + runtime ops check + cleanup` 全部完成且无 open follow-up issue 阻塞时，才能 `Done`

## 运行方式

- tracker：GitHub Issue + PR
- 感知方式：第一阶段默认 `30s` 轮询
- secrets：不入仓
- 正式工作流文件：`WORKFLOW.freshquant.md`
- 全局自动化提示词：`prompts/global_stewardship.md`
- 关键模板：
  - `templates/merge_handoff_comment.md`
  - `templates/global_stewardship_progress_comment.md`
  - `templates/global_stewardship_done_comment.md`
  - `templates/follow_up_issue.md`
- `Global Stewardship` 的共享部署辅助脚本位于仓库根目录 `script/`：
  - `script/freshquant_deploy_plan.py`
  - `script/fqnext_host_runtime_ctl.ps1`
- `sync_freshquant_symphony_service.ps1` / `start_freshquant_symphony.ps1` 会同时校验 `WORKFLOW.freshquant.md`、`prompts/merging.md` 与 `prompts/global_stewardship.md` 的关键 contract，避免正式 prompt 被过度简化
- 如果当前 Codex 会话没有管理员权限，可预装一个按需触发的 Windows 计划任务，由它以 `SYSTEM` 身份重启 `fq-symphony-orchestrator` 并写回状态文件；普通会话只负责触发任务和读取结果
- 正式宿主机脚本：
  - `scripts/run_freshquant_codex_session.ps1`
  - `scripts/assert_freshquant_merging_prompt.ps1`
  - `scripts/check_freshquant_runtime_post_deploy.ps1`
  - `scripts/request_freshquant_symphony_cleanup.ps1`
  - `scripts/invoke_freshquant_symphony_cleanup_finalizer.ps1`
  - `scripts/start_freshquant_symphony.ps1`
  - `scripts/sync_freshquant_symphony_service.ps1`
  - `scripts/install_freshquant_symphony_restart_task.ps1`
  - `scripts/invoke_freshquant_symphony_restart_task.ps1`
  - `scripts/run_freshquant_symphony_restart_task.ps1`

`request_freshquant_symphony_cleanup.ps1` 的部署说明正文支持两种入口：

- `-DeploymentCommentBody`：兼容旧调用，只适合短 ASCII 文本
- `-DeploymentCommentBodyPath`：推荐入口，从 UTF-8 markdown 文件读取正文，避免 PowerShell 命令行把中文和反引号 markdown 破坏成 `?` 或控制字符

## 任务标签建议

Issue labels：

- `symphony`
- `in-progress`
- `rework`
- `merging`
- `blocked`
- `global-stewardship`

标签使用规则：

- 新建 Issue 默认只打 `symphony` 与 `in-progress`
- `rework` 只在确定性仓库内失败时使用
- `blocked` 只在真实外部阻塞时使用

PR 信号：

- comments 不是 merge 真值
- `Merging` 只认 GitHub PR 的 required checks、review threads、mergeability 与 ruleset
