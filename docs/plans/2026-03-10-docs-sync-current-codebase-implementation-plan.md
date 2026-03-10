# Docs Sync Current Codebase Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将项目入口文档、代码现状总览与迁移治理文档同步到 2026-03-10 当前 `origin/main` 代码状态。

**Architecture:** 先以当前代码树、最近合并记录和 `progress.md` 为单一事实源，找出过期描述；再回写 `docs/agent` 主入口、项目总览与治理记录，最后用文本检索做一致性校验。

**Tech Stack:** Markdown, Git, PowerShell, ripgrep

---

### Task 1: 收集代码事实与文档差异

**Files:**
- Modify: `docs/plans/2026-03-10-docs-sync-current-codebase-implementation-plan.md`
- Review: `docs/agent/index.md`
- Review: `docs/agent/项目目标与代码现状调研.md`
- Review: `docs/migration/progress.md`
- Review: `docs/migration/breaking-changes.md`
- Review: `freshquant/rear/api_server.py`
- Review: `morningglory/fqwebui/src/router/index.js`
- Review: `morningglory/fqwebui/src/views/MyHeader.vue`

**Step 1: 读取当前代码事实**

Run: `git log --oneline --decorate -n 12`
Expected: 能看到 `origin/main` 最新合入记录，包括 2026-03-10 的甘特图审计相关提交。

**Step 2: 对照文档找出过期项**

Run: `rg -n "2026-03-09|0001 到 0025|等待 PR|准备合入|54 个测试文件|73 个 tracked 文件" docs`
Expected: 能定位到 `docs/agent/index.md`、`docs/agent/项目目标与代码现状调研.md` 以及可能残留旧状态的迁移记录。

### Task 2: 更新主入口与项目现状文档

**Files:**
- Modify: `docs/agent/index.md`
- Modify: `docs/agent/项目目标与代码现状调研.md`

**Step 1: 回写当前状态快照**

- 将日期更新到 `2026-03-10`
- 将已登记 RFC 范围更新到 `0001` 到 `0027`
- 将运行观测、Shouban30、KlineSlim、多周期缠论和甘特图审计对齐等当前能力写入快照

**Step 2: 更新仓库结构、入口与测试规模**

- 用当前 `git ls-files` 统计替换旧数量
- 补齐 `/gantt/shouban30` 等当前页面
- 更新 `freshquant/tests/` 与 `morningglory/fqwebui/tests/` 规模说明

### Task 3: 更新迁移治理文档

**Files:**
- Modify: `docs/migration/progress.md`
- Modify: `docs/migration/breaking-changes.md`

**Step 1: 修正旧状态描述**

- 将 `0023` 中“准备合入 main”改为已合入后的表述

**Step 2: 追加需要登记的界面语义调整**

- 若甘特图审计对齐已改变用户可见默认语义，则在 `breaking-changes.md` 追加一条“无接口破坏但页面语义调整”的记录

### Task 4: 校验文档一致性

**Files:**
- Review: `docs/agent/index.md`
- Review: `docs/agent/项目目标与代码现状调研.md`
- Review: `docs/migration/progress.md`
- Review: `docs/migration/breaking-changes.md`

**Step 1: 文本检索旧快照残留**

Run: `rg -n "0001 到 0025|等待 PR|准备合入|54 个测试文件|73 个 tracked 文件|427 个 tracked 文件|483 个 tracked 文件|1045 个" docs/agent docs/migration`
Expected: 不再命中需要本轮修正的旧描述。

**Step 2: 查看最终 diff**

Run: `git diff -- docs/agent/index.md docs/agent/项目目标与代码现状调研.md docs/migration/progress.md docs/migration/breaking-changes.md docs/plans/2026-03-10-docs-sync-current-codebase-implementation-plan.md`
Expected: 只包含文档变更，且内容与当前代码一致。
