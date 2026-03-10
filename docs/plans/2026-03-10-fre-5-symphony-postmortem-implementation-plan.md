# FRE-5 Symphony Postmortem Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 沉淀 `FRE-5` 的真实运行复盘，形成后续真实 issue 可复用的 Symphony 运行经验文档。

**Architecture:** 在 `docs/agent/` 新增独立复盘文档，按“问题分层 -> 成功经验 -> 优化建议”组织内容；同步更新索引，把它并入正式 Symphony 文档族。

**Tech Stack:** Markdown, docs/agent 索引体系

---

### Task 1: 写 design 文档

**Files:**
- Create: `docs/plans/2026-03-10-fre-5-symphony-postmortem-design.md`

**Step 1: 写背景、目标、候选方案和推荐方案**

**Step 2: 明确文档落点与验收标准**

**Step 3: 自查 design 是否只讨论复盘文档，不引入额外实现**

### Task 2: 写 implementation plan

**Files:**
- Create: `docs/plans/2026-03-10-fre-5-symphony-postmortem-implementation-plan.md`

**Step 1: 明确文档任务、文件路径和组织方式**

**Step 2: 把“新增文档 + 更新索引 + 验证”拆成独立任务**

**Step 3: 自查计划是否足够让零上下文开发者执行**

### Task 3: 新增复盘文档

**Files:**
- Create: `docs/agent/Symphony真实Issue阻塞复盘与优化建议.md`

**Step 1: 写清 `FRE-5` 的时间线与分层问题**

**Step 2: 写清最终成功经验与代码侧经验**

**Step 3: 写清配置优化和流程优化建议**

**Step 4: 自查是否明确区分“运行面问题”与“业务代码问题”**

### Task 4: 更新索引

**Files:**
- Modify: `docs/agent/index.md`

**Step 1: 在 Symphony 相关文档区新增复盘文档入口**

**Step 2: 在“按任务类型查找”表格中补上该文档**

**Step 3: 自查链接文案与现有风格一致**

### Task 5: 验证并提交

**Files:**
- Verify: `docs/agent/Symphony真实Issue阻塞复盘与优化建议.md`
- Verify: `docs/agent/index.md`

**Step 1: 运行 `git diff --check`**

**Step 2: 运行 `git status --short --branch`**

**Step 3: 提交本次复盘文档更新**
