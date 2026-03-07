# FreshQuant 文档现状对齐 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 更新项目核心文档，使其准确反映 2026-03-07 当前 `main` 分支的代码现状、迁移进度和运行约束。

**Architecture:** 先做文档盘点，只修正与代码事实冲突的高优先级文档；核心总览文档重写为“现状快照”，索引文档补上当前阅读顺序与状态说明，专项运行文档按已落地 RFC 同步，治理文档修正编号和缺失项，最后做交叉一致性校验。

**Tech Stack:** Markdown、PowerShell、git worktree、ripgrep

---

### Task 1: 盘点当前文档漂移点

**Files:**
- Modify: `docs/plans/2026-03-07-docs-current-state-refresh.md`
- Check: `docs/agent/index.md`
- Check: `docs/agent/项目目标与代码现状调研.md`
- Check: `docs/agent/旧仓库freshquant-重点迁移模块调研.md`
- Check: `docs/agent/TradingAgents-CN接入与运行说明.md`
- Check: `docs/migration/progress.md`
- Check: `docs/migration/breaking-changes.md`
- Check: `CLAUDE.md`

**Step 1: 列出过时结论与编号漂移**

Run: `rg -n "为空表|仅 1 个用例|尚未登记|0011-stock-etf-tpsl-module|FastAPI/Flask|Dagster/Celery/APScheduler|live_trading" docs README.md CLAUDE.md`

**Step 2: 记录需要更新的文档清单**

预期：识别出核心 agent 文档、TradingAgents 运行文档、治理文档和 `CLAUDE.md` 的高优先级漂移。

### Task 2: 重写项目现状总览文档

**Files:**
- Modify: `docs/agent/项目目标与代码现状调研.md`

**Step 1: 按当前代码重写“项目目标 / 仓库结构 / 关键入口 / 配置 / 存储 / 测试 / 已落地 RFC / 风险与剩余空白”**

预期：删除“progress 为空”“测试只有 1 个”的过时结论，替换为 2026-03-07 当前状态。

**Step 2: 明确文档中的“当前事实”和“旧调研结论”边界**

预期：读者能直接把该文档当作当前接手入口。

### Task 3: 更新索引和旧仓迁移调研入口

**Files:**
- Modify: `docs/agent/index.md`
- Modify: `docs/agent/旧仓库freshquant-重点迁移模块调研.md`

**Step 1: 在索引文档中加入当前状态快照与推荐阅读顺序**

预期：新接手者先看当前现状，再看旧仓模块调研。

**Step 2: 在旧仓调研文档顶部补充“截至 2026-03-07 的目标仓迁移落点与 RFC 对照”**

预期：避免读者把旧仓实现误认为目标仓当前实现。

### Task 4: 同步专项运行与治理文档

**Files:**
- Modify: `docs/agent/TradingAgents-CN接入与运行说明.md`
- Modify: `docs/migration/breaking-changes.md`
- Add: `docs/rfcs/0004-powershell-utf8-display.md`
- Modify: `CLAUDE.md`

**Step 1: 修正 TradingAgents-CN 配置来源描述**

预期：与 RFC 0016 和当前 Docker 启动语义一致，根 `.env` 为单一真相源。

**Step 2: 修正 breaking changes 中 TPSL 旧编号漂移和格式问题**

预期：不再出现 `0011-stock-etf-tpsl-module` 误导性记录。

**Step 3: 为 progress 中已存在的 `0004` 补齐 RFC 文档**

预期：`progress.md`、`docs/rfcs/`、`breaking-changes.md` 三者编号关系一致。

**Step 4: 更新 `CLAUDE.md` 的仓库结构与技术栈描述**

预期：移除明显过时的架构表述。

### Task 5: 一致性校验

**Files:**
- Check: `docs/agent/index.md`
- Check: `docs/agent/项目目标与代码现状调研.md`
- Check: `docs/agent/旧仓库freshquant-重点迁移模块调研.md`
- Check: `docs/agent/TradingAgents-CN接入与运行说明.md`
- Check: `docs/migration/progress.md`
- Check: `docs/migration/breaking-changes.md`
- Check: `docs/rfcs/0004-powershell-utf8-display.md`
- Check: `CLAUDE.md`

**Step 1: 运行文本校验**

Run: `rg -n "为空表|仅 1 个用例|尚未登记任何 RFC|0011-stock-etf-tpsl-module" docs CLAUDE.md`

Expected: 只保留明确历史语境下的文字，不再出现在当前事实描述中。

**Step 2: 运行 git diff 自审**

Run: `git diff -- docs/agent docs/migration docs/rfcs CLAUDE.md`

Expected: 变更集中在文档现状对齐，没有无关代码改动。
