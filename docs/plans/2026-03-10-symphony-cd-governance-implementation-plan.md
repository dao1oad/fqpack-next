# Symphony CD Governance Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 Docker 与 Symphony 宿主机自动部署固化到 FreshQuant 的 Symphony 正式治理中，并把部署成功改成进入 `Done` 的前提。

**Architecture:** 本次只改治理文档和 repo-versioned workflow 模板，不直接实现新的自动部署执行器。核心做法是同步更新 `AGENTS.md`、RFC 0028、Symphony 正式治理文档和 `runtime/symphony` 模板，使 `Merging`/`Done` 的语义、部署触发矩阵、失败回路和权限边界保持一致。

**Tech Stack:** Markdown, YAML-frontmatter docs, Symphony workflow template, PowerShell deployment commands

---

### Task 1: 更新设计文档与实施计划归档

**Files:**
- Create: `docs/plans/2026-03-10-symphony-cd-governance-design.md`
- Create: `docs/plans/2026-03-10-symphony-cd-governance-implementation-plan.md`

**Step 1: 写入设计文档**

写清：

- `Merging` 固化自动部署
- `Done` 以部署成功为前提
- Docker / 宿主机触发矩阵
- 自动重试与 `Rework` 转入条件

**Step 2: 写入实施计划**

把后续治理文件修改拆成明确任务和验证步骤。

**Step 3: Commit**

```bash
git add docs/plans/2026-03-10-symphony-cd-governance-design.md docs/plans/2026-03-10-symphony-cd-governance-implementation-plan.md
git commit -m "docs: 补充 symphony cd 治理设计与计划"
```

### Task 2: 更新仓库治理基线

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/rfcs/0028-symphony-first-governance.md`
- Modify: `docs/migration/progress.md`
- Modify: `docs/migration/breaking-changes.md`

**Step 1: 更新 AGENTS.md**

补充：

- `Merging` 负责 merge + deploy + health check
- `Done` 以部署成功为前提
- CD 触发矩阵与失败回路
- 自动部署边界从“默认禁止”调整为“允许在本地/并行运行面自动执行”

**Step 2: 更新 RFC 0028**

同步修改：

- Scope / Non-Goals
- Public API
- Data / Config
- Acceptance Criteria
- 破坏性变更说明

**Step 3: 更新迁移记录**

- `progress.md` 里为 RFC 0028 增补本次 CD 治理收口说明
- `breaking-changes.md` 追加“Done 语义从 merge 扩展到 deploy success”的记录

**Step 4: Commit**

```bash
git add AGENTS.md docs/rfcs/0028-symphony-first-governance.md docs/migration/progress.md docs/migration/breaking-changes.md
git commit -m "docs: 固化 symphony cd 治理语义"
```

### Task 3: 更新 Symphony 正式治理文档

**Files:**
- Modify: `docs/agent/Symphony正式接入治理说明.md`
- Modify: `docs/agent/Symphony宿主机服务部署说明.md`
- Modify: `docs/agent/index.md`

**Step 1: 更新正式接入治理说明**

加入：

- `Merging` 阶段自动部署
- `Done` 进入条件
- Docker 与宿主机部署矩阵
- 部署失败重试与转 `Rework`

**Step 2: 更新宿主机服务部署说明**

明确：

- `runtime/symphony` 变更合并后必须同步部署到 `symphony-service`
- 与 Docker 部署并列的正式 CD 责任

**Step 3: 更新索引**

让文档索引中当前状态快照和 `Symphony正式接入治理说明` 的用途描述包含 CD 语义。

**Step 4: Commit**

```bash
git add docs/agent/Symphony正式接入治理说明.md docs/agent/Symphony宿主机服务部署说明.md docs/agent/index.md
git commit -m "docs: 更新 symphony 正式治理与部署说明"
```

### Task 4: 更新 repo-versioned workflow 模板

**Files:**
- Modify: `runtime/symphony/README.md`
- Modify: `runtime/symphony/WORKFLOW.freshquant.md`
- Modify: `runtime/symphony/prompts/in_progress.md`
- Create: `runtime/symphony/prompts/merging.md`

**Step 1: 更新 README**

把自动部署和 `Done` 判定加入模板说明。

**Step 2: 更新 WORKFLOW.freshquant.md**

把 `Merging` 的说明从“finalize verification, CI, merge preparation, and completion bookkeeping”改成包含：

- merge
- deploy
- health check
- retry / Rework handoff

**Step 3: 更新 in_progress prompt**

保持“禁止在 `In Progress` 自动部署”，避免提前越过 `Merging`。

**Step 4: 新增 merging prompt**

明确：

- 部署矩阵
- 健康检查
- 自动重试
- 转 `Rework` 条件
- `Done` 进入条件

**Step 5: Commit**

```bash
git add runtime/symphony/README.md runtime/symphony/WORKFLOW.freshquant.md runtime/symphony/prompts/in_progress.md runtime/symphony/prompts/merging.md
git commit -m "docs: 更新 symphony workflow 的 cd 语义"
```

### Task 5: 验证与收尾

**Files:**
- Verify only

**Step 1: 运行最小基线验证**

Run: `py -3 -m pytest test_enum_serialization.py -q`  
Expected: `1 passed`

**Step 2: 做一致性检查**

Run:

```bash
rg -n "Merging|Done|部署|deploy|health check|Rework" AGENTS.md docs/rfcs/0028-symphony-first-governance.md docs/agent runtime/symphony -S
```

Expected:

- `AGENTS.md`
- RFC 0028
- `docs/agent` 说明
- `runtime/symphony` 模板

都体现一致的 CD 语义。

**Step 3: 检查 git 差异与状态**

Run:

```bash
git diff --check
git status --short --branch
```

Expected:

- 无 diff 格式错误
- 只包含本次治理文档变更

**Step 4: Commit**

```bash
git add AGENTS.md docs/rfcs/0028-symphony-first-governance.md docs/migration/progress.md docs/migration/breaking-changes.md docs/agent docs/plans runtime/symphony
git commit -m "docs: 将 cd 固化到 symphony 正式治理"
```
