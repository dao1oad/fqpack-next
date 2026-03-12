# FreshQuant Symphony Workflow Templates

本目录保存 FreshQuant 的 repo-versioned `Symphony` 正式 workflow 模板。

## 目标

- 固化 `GitHub-first` 轻量治理
- 固化 `Design Review` 为唯一人工评审点
- 固化 `Symphony + superpowers` 执行链
- 固化 deploy、health check、cleanup 与 `Done` 判定
- 让仓库治理与 `Symphony` 运行模板保持一致

## 正式真值

- GitHub Issue：正式任务入口
- GitHub Draft PR：唯一 `Design Review` 评审面
- GitHub PR + CI：代码交付真值

`Linear` 不再作为正式任务入口、评审面或批准真值来源。

## 当前工作流

正式工作流固定为：

`Issue -> Draft PR -> Design Review(仅高风险) -> In Progress -> CI -> Deploy -> Health Check -> Cleanup -> Done`

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

## 运行方式

- tracker：GitHub Issue + Draft PR
- 感知方式：第一阶段默认 `30s` 轮询
- secrets：不入仓
- 正式工作流文件：`WORKFLOW.freshquant.md`
- 正式宿主机脚本：
  - `scripts/run_freshquant_codex_session.ps1`
  - `scripts/request_freshquant_symphony_cleanup.ps1`
  - `scripts/invoke_freshquant_symphony_cleanup_finalizer.ps1`
  - `scripts/start_freshquant_symphony.ps1`
  - `scripts/sync_freshquant_symphony_service.ps1`

## 任务标签建议

Issue labels：

- `symphony`
- `blocked`
- `rework`
- `todo`
- `in-progress`
- `merging`

标签使用规则：

- 新建 Issue 默认只打 `symphony` 与 `todo`
- `design-review` 只在确认高风险后追加
- 不要把 `design-review` 当成新任务默认标签

PR 信号：

- 评论 `APPROVED`
- 评论 `REVISE: ...`
- 评论 `REJECTED: ...`
- PR review `Approve`
