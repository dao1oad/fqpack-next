# Symphony Merging Cleanup 硬门禁 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 FreshQuant 的 `Merging -> Done` 语义扩展为“merge + deploy + health check + cleanup”，并落地远端分支、workspace 与旧 artifacts 的正式 cleanup 机制。

**Architecture:** 先补治理文档、RFC 与迁移记录，再引入宿主机 Codex wrapper 和 cleanup request/finalizer 脚本。Merging session 只负责准备 cleanup request；真正的 workspace 删除、最终 deployment comment 和 `Done` 状态推进由 Codex 子进程退出后的宿主机 finalizer 完成。

**Tech Stack:** Markdown, PowerShell, Linear GraphQL, Git, Symphony workflow templates

---

### Task 1: 落盘治理文档与 RFC 0033

**Files:**
- Create: `docs/plans/2026-03-12-symphony-merging-cleanup-gate-design.md`
- Create: `docs/plans/2026-03-12-symphony-merging-cleanup-gate-implementation-plan.md`
- Create: `docs/rfcs/0033-symphony-merging-cleanup-gate.md`
- Modify: `docs/migration/progress.md`

**Step 1: 写 RFC 0033**

明确：
- `Done` 真值新增 cleanup
- cleanup 范围只含 remote branch / workspace / old artifacts
- 不新增 Linear 状态

**Step 2: 更新 progress**

新增 `0033` 条目，记录为当前进行中的治理变更。

**Step 3: 文档检索**

Run: `rg -n "0033|cleanup|Done =|workspace" docs/rfcs docs/plans docs/migration/progress.md -S`
Expected: 新文档和进度记录都能被检出

### Task 2: 更新治理文档与模板语义

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/rfcs/0028-symphony-first-governance.md`
- Modify: `docs/agent/Symphony正式接入治理说明.md`
- Modify: `docs/agent/Symphony宿主机服务部署说明.md`
- Modify: `runtime/symphony/README.md`
- Modify: `runtime/symphony/WORKFLOW.freshquant.md`
- Modify: `runtime/symphony/prompts/merging.md`
- Modify: `runtime/symphony/templates/deployment_comment.md`

**Step 1: 更新 `Done` 语义**

写清：
- `Done` 不再只要求 merge/deploy/health check
- 还要求 cleanup 成功

**Step 2: 更新宿主机运行说明**

写清：
- Merging session 生成 cleanup request
- wrapper/finalizer 在 Codex 退出后执行 cleanup

**Step 3: 更新 deployment comment 模板**

新增：
- `Cleanup Results`

**Step 4: 文本检查**

Run: `rg -n "cleanup|Cleanup Results|Done|workspace|feature branch" AGENTS.md docs/rfcs/0028-symphony-first-governance.md docs/agent runtime/symphony -S`
Expected: 所有治理文档与模板都出现 cleanup 语义

### Task 3: 引入 Codex wrapper 与 cleanup request/finalizer

**Files:**
- Create: `runtime/symphony/scripts/run_freshquant_codex_session.ps1`
- Create: `runtime/symphony/scripts/request_freshquant_symphony_cleanup.ps1`
- Create: `runtime/symphony/scripts/invoke_freshquant_symphony_cleanup_finalizer.ps1`
- Modify: `runtime/symphony/scripts/sync_freshquant_symphony_service.ps1`
- Modify: `runtime/symphony/WORKFLOW.freshquant.md`

**Step 1: 新增 request 脚本**

要求：
- 把 cleanup request 写到 `ServiceRoot\\artifacts\\cleanup-requests\\<ISSUE>.json`
- 校验 issue identifier、workspace path、branch name、comment body 非空

**Step 2: 新增 finalizer 脚本**

职责：
- 读取 cleanup request
- 删除远端分支
- 删除 workspace
- 清理 old artifacts
- 调用 Linear GraphQL 写 deployment comment、推进 `Done`
- 将结果写到 `cleanup-results\\<ISSUE>.json`

**Step 3: 新增 wrapper**

职责：
- 在 workspace 中启动 Codex child
- child 退出后切回安全目录
- 对当前 issue 执行 finalizer

**Step 4: 更新 workflow 与同步脚本**

把 `codex.command` 改为 wrapper，并确保新脚本会同步到宿主机服务目录。

### Task 4: 实现 guard、幂等与 artifacts 保留期逻辑

**Files:**
- Modify: `runtime/symphony/scripts/request_freshquant_symphony_cleanup.ps1`
- Modify: `runtime/symphony/scripts/invoke_freshquant_symphony_cleanup_finalizer.ps1`

**Step 1: 加 workspace guard**

要求：
- 目标目录必须位于 `workspace.root`
- 目录名必须等于 issue identifier

**Step 2: 加 branch guard**

要求：
- 禁删 `main`
- 空分支名直接失败
- 远端分支已不存在视为成功

**Step 3: 加 artifacts 保留期清理**

要求：
- 默认 14 天
- 跳过 cleanup 系统目录
- 跳过 active issues 对应条目

### Task 5: 加入 Linear GraphQL 集成

**Files:**
- Modify: `runtime/symphony/scripts/invoke_freshquant_symphony_cleanup_finalizer.ps1`

**Step 1: 查询 issue 与 Done state**

按 issue identifier 解析：
- team key
- issue number

再查：
- issue id
- `Done` state id

**Step 2: 写最终 deployment comment**

comment body = request 中的 deployment comment body + cleanup result section。

**Step 3: 推进 issue 到 `Done`**

仅在 cleanup 全成功后执行。

### Task 6: 最小验证与收尾

**Files:**
- Modify: touched files from tasks 1-5 as needed
- Modify: `docs/migration/breaking-changes.md`
- Modify: `docs/migration/progress.md`
- Modify: `docs/rfcs/0033-symphony-merging-cleanup-gate.md`

**Step 1: PowerShell 干跑验证**

Run:
- `powershell -ExecutionPolicy Bypass -File runtime\\symphony\\scripts\\request_freshquant_symphony_cleanup.ps1 ...`
- `powershell -ExecutionPolicy Bypass -File runtime\\symphony\\scripts\\invoke_freshquant_symphony_cleanup_finalizer.ps1 ... -WhatIf`

Expected:
- request JSON 生成
- finalizer 输出将执行的 branch/workspace/artifacts cleanup

**Step 2: 文本与 patch 检查**

Run: `git diff --check`
Expected: 无 patch 格式问题

**Step 3: 更新最终状态**

实现完成后：
- 将 RFC 0033 标记为 `Done`
- 在 `progress.md` 将 `0033` 标记为 `Done`
- 在 `breaking-changes.md` 追加 cleanup 硬门禁变更

**Step 4: 最终验证**

Run:
- `rg -n "cleanup|run_freshquant_codex_session|request_freshquant_symphony_cleanup|invoke_freshquant_symphony_cleanup_finalizer" runtime/symphony docs AGENTS.md -S`
- `git status --short --branch`

Expected:
- 新门禁、脚本和文档均可检出
- 工作树状态可解释
