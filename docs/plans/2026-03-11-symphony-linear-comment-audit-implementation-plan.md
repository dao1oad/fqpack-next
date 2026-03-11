# Symphony Linear 留痕与决策审计 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 Human Review 决策项、PR 结果留痕和部署留痕固化到 FreshQuant 的 Symphony 正式治理中。

**Architecture:** 先更新治理文档定义新的审计语义，再补齐 `runtime/symphony` 的评论模板和 prompt 门禁，最后更新同步脚本与进度记录，确保运行面可部署这些新增模板。

**Tech Stack:** Markdown, PowerShell, Symphony workflow templates

---

### Task 1: 更新设计与进度文档入口

**Files:**
- Modify: `docs/migration/progress.md`
- Create: `docs/plans/2026-03-11-symphony-linear-comment-audit-design.md`
- Create: `docs/plans/2026-03-11-symphony-linear-comment-audit-implementation-plan.md`

**Step 1: 确认进度表里 `0028` 的当前状态与描述位置**

Run: `rg -n "0028" docs/migration/progress.md`
Expected: 能定位到 `0028` 当前记录

**Step 2: 更新 `0028` 的说明**

在 `docs/migration/progress.md` 中补充本次“Linear 留痕与决策审计”增量。

**Step 3: 自检文档路径**

Run: `rg -n "symphony-linear-comment-audit" docs/plans docs/migration/progress.md`
Expected: 新设计稿和计划文件名可被检出

**Step 4: Commit**

```bash
git add docs/plans/2026-03-11-symphony-linear-comment-audit-design.md docs/plans/2026-03-11-symphony-linear-comment-audit-implementation-plan.md docs/migration/progress.md
git commit -m "docs: 增补 Symphony Linear 留痕治理设计"
```

### Task 2: 更新治理文档

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/rfcs/0028-symphony-first-governance.md`
- Modify: `docs/agent/Symphony正式接入治理说明.md`

**Step 1: 写入 Human Review 决策项规则**

明确：
- Human Review 评论必须一次性列出待决策项、推荐方案、理由
- 未决事项未清零时，不允许进入 `In Progress`

**Step 2: 写入 PR 结果评论规则**

明确：
- `In Progress / Rework -> Merging` 前必须写 PR 结果评论
- 评论必须含解决问题、方案、理由、修改文件、验证、经验、PR 链接

**Step 3: 写入部署评论规则**

明确：
- `Merging -> Done` 前必须写部署评论
- 没有部署留痕不得 Done

**Step 4: 运行文本检查**

Run: `rg -n "待决策项|推荐方案|PR 结果评论|部署评论|Done" AGENTS.md docs/rfcs/0028-symphony-first-governance.md docs/agent/Symphony正式接入治理说明.md -S`
Expected: 三份文档都能检出新规则关键词

**Step 5: Commit**

```bash
git add AGENTS.md docs/rfcs/0028-symphony-first-governance.md docs/agent/Symphony正式接入治理说明.md
git commit -m "docs: 强化 Symphony 的 Linear 留痕门禁"
```

### Task 3: 补齐 Linear 评论模板

**Files:**
- Modify: `runtime/symphony/templates/human_review_comment.md`
- Create: `runtime/symphony/templates/pr_completion_comment.md`
- Create: `runtime/symphony/templates/deployment_comment.md`

**Step 1: 扩展 Human Review 模板**

新增：
- `Decision items`
- `No open decision items`

**Step 2: 新增 PR 结果模板**

写出结构化栏目：
- `Problems solved`
- `Chosen solution`
- `Why this solution`
- `Files changed`
- `Verification`
- `Lessons learned`
- `PR`

**Step 3: 新增部署模板**

写出结构化栏目：
- `Deployment scope`
- `Executed actions`
- `Health checks`
- `Retry / failure notes`
- `Final deployment result`

**Step 4: 运行模板关键字检查**

Run: `rg -n "Decision items|Problems solved|Deployment scope" runtime/symphony/templates -S`
Expected: 三类模板关键字可被检出

**Step 5: Commit**

```bash
git add runtime/symphony/templates/human_review_comment.md runtime/symphony/templates/pr_completion_comment.md runtime/symphony/templates/deployment_comment.md
git commit -m "feat: 增加 Symphony 的 Linear 留痕模板"
```

### Task 4: 更新 workflow prompt 与同步脚本

**Files:**
- Modify: `runtime/symphony/prompts/todo.md`
- Modify: `runtime/symphony/prompts/in_progress.md`
- Modify: `runtime/symphony/prompts/merging.md`
- Modify: `runtime/symphony/README.md`
- Modify: `runtime/symphony/scripts/sync_freshquant_symphony_service.ps1`

**Step 1: 更新 Todo prompt**

明确：
- Human Review 评论必须带决策项/无未决项声明
- 未完成该评论包不得进入 `Human Review`

**Step 2: 更新 In Progress prompt**

明确：
- 进入 `Merging` 前必须把 PR 结果评论写入 Linear

**Step 3: 更新 Merging prompt**

明确：
- `Done` 前必须写部署评论
- 部署留痕与健康检查都是 Done 门禁

**Step 4: 更新 README 与同步脚本**

README 记录新模板职责。
同步脚本新增：
- `templates\\pr_completion_comment.md`
- `templates\\deployment_comment.md`

**Step 5: 运行文本检查**

Run: `rg -n "Decision items|PR result|deployment comment|Done" runtime/symphony/prompts runtime/symphony/README.md runtime/symphony/scripts/sync_freshquant_symphony_service.ps1 -S`
Expected: prompt、README、同步脚本都能检出对应规则

**Step 6: Commit**

```bash
git add runtime/symphony/prompts/todo.md runtime/symphony/prompts/in_progress.md runtime/symphony/prompts/merging.md runtime/symphony/README.md runtime/symphony/scripts/sync_freshquant_symphony_service.ps1
git commit -m "feat: 固化 Symphony 的 Linear 评论门禁"
```

### Task 5: 最小验证与收尾

**Files:**
- Modify: touched files from tasks 1-4 as needed

**Step 1: 运行基线测试**

Run: `py -3 -m pytest test_enum_serialization.py -q`
Expected: `1 passed`

**Step 2: 运行 diff 检查**

Run: `git diff --check`
Expected: 无 trailing whitespace、无 patch 错误

**Step 3: 检查工作树状态**

Run: `git status --short --branch`
Expected: 分支干净，或仅剩本轮待提交改动

**Step 4: 最终提交**

```bash
git add AGENTS.md docs/rfcs/0028-symphony-first-governance.md docs/agent/Symphony正式接入治理说明.md docs/migration/progress.md docs/plans/2026-03-11-symphony-linear-comment-audit-design.md docs/plans/2026-03-11-symphony-linear-comment-audit-implementation-plan.md runtime/symphony/templates/human_review_comment.md runtime/symphony/templates/pr_completion_comment.md runtime/symphony/templates/deployment_comment.md runtime/symphony/prompts/todo.md runtime/symphony/prompts/in_progress.md runtime/symphony/prompts/merging.md runtime/symphony/README.md runtime/symphony/scripts/sync_freshquant_symphony_service.ps1
git commit -m "governance: 强化 Symphony 的 Linear 审计留痕"
```
