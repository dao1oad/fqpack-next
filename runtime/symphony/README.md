# FreshQuant Symphony Workflow Templates

本目录保存 FreshQuant 的 repo-versioned `Symphony` 正式 workflow 模板。

## 目标

- 固化 `GitHub-first` 轻量治理
- 固化 `Design Review` 为唯一人工评审点
- 固化 `Symphony + superpowers` 执行链
- 固化 `Symphony` 到 merge 为止、`Global Stewardship` 接手 merge 后收口
- 固化 deploy、health check、runtime ops check、cleanup 与 `Done` 判定
- 让仓库治理与 `Symphony` 运行模板保持一致

## 正式真值

- GitHub Issue：正式任务入口
- GitHub Draft PR：唯一 `Design Review` 评审面
- GitHub PR + CI：代码交付真值
- 单个全局 Codex 自动化完成的 `deploy + health check + runtime ops check + cleanup`：运行交付真值

`Linear` 不再作为正式任务入口、评审面或批准真值来源。

## 当前工作流

正式工作流固定为：

`Issue -> Draft PR -> Design Review(仅高风险) -> In Progress -> CI -> Merging -> Global Stewardship -> Done`

低风险任务可跳过 `Design Review`，直接进入实现。

低风险任务规则：

- 不创建 `Design Review Packet`
- 不进入 `brainstorming` 审批闭环
- 不等待 `APPROVED`
- 在 `Todo` 完成一轮有效上下文梳理后，由 orchestrator 自动切到 `In Progress`
- 新建 GitHub Issue 默认只打 `symphony` 与 `todo`
- 不要在创建时预贴 `design-review`

GitHub 文本规则：

- 所有提交到 GitHub 的正式说明默认使用简体中文
- 包括 Issue 描述、Draft PR 标题与正文、PR / Issue 评论、部署说明、Done 总结
- 仅审批控制词保留英文：`APPROVED`、`REVISE:`、`REJECTED:`

## 唯一人工评审点

唯一人工评审点是：

- `Design Review`

规则：

- 高风险任务必须先创建 Draft PR
- `Design Review` 的 Draft PR bootstrap 由 orchestrator 自动完成，而不是由实现态 Codex 会话临场创建
- `brainstorming` 必须产出一份完整 `Design Review Packet`
- `Design Review Packet` 必须一次性列出全部待评审点、推荐方案和理由
- 不允许零碎多轮提审
- 人工在 Draft PR 中回复 `APPROVED`，或给出 PR review `Approve`
- 设计批准后，不再设置第二个人工评审点

## superpowers 执行链

- 普通 bugfix：
  - `using-superpowers`
  - `systematic-debugging`
  - `test-driven-development`
  - `verification-before-completion`
  - 不进入 `brainstorming`

- 现有模块增强：
  - `using-superpowers`
  - `brainstorming`
  - `test-driven-development`
  - `verification-before-completion`

- 跨模块或高风险改动：
  - `using-superpowers`
  - `brainstorming`
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

- tracker：GitHub Issue + Draft PR
- 感知方式：第一阶段默认 `30s` 轮询
- secrets：不入仓
- 正式工作流文件：`WORKFLOW.freshquant.md`
- 全局自动化提示词：`prompts/global_stewardship.md`
- 高风险 issue 进入 `Design Review` 后，orchestrator 会先 bootstrap issue branch 和 Draft PR；实现态工作区则会自动 checkout 到对应 issue branch
- 关键模板：
  - `templates/merge_handoff_comment.md`
  - `templates/global_stewardship_progress_comment.md`
  - `templates/global_stewardship_done_comment.md`
  - `templates/follow_up_issue.md`
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
- `blocked`
- `rework`
- `todo`
- `in-progress`
- `merging`
- `global-stewardship`

标签使用规则：

- 新建 Issue 默认只打 `symphony` 与 `todo`
- `design-review` 只在确认高风险后追加
- 不要把 `design-review` 当成新任务默认标签

PR 信号：

- 评论 `APPROVED`
- 评论 `REVISE: ...`
- 评论 `REJECTED: ...`
- PR review `Approve`
