# Global Stewardship Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 `Symphony` 的正式治理边界收缩到 PR merge，并引入由单个 Codex app 自动化驱动的 `Global Stewardship` merge 后治理闭环。

**Architecture:** 这次改造先固定治理规则和状态契约，再把 `Merging` 从“merge 后全包”改成“merge + 交接”，最后补上全局自动化所需的评论契约、follow-up issue 契约和故障排障文档。全局 Codex 自动化不直接写代码，只负责巡检、批量 deploy / cleanup、发现问题并创建 follow-up issue。

**Tech Stack:** Markdown governance docs, PowerShell prompt validators, GitHub labels/state conventions, Codex app automation

---

## Scope

- 需要修改：
  - `AGENTS.md`
  - `runtime/symphony/WORKFLOW.freshquant.md`
  - `runtime/symphony/prompts/merging.md`
  - `runtime/symphony/scripts/assert_freshquant_workflow_prompt.ps1`
  - `runtime/symphony/scripts/assert_freshquant_merging_prompt.ps1`
  - `docs/current/runtime.md`
  - `docs/current/deployment.md`
  - `docs/current/troubleshooting.md`
- 需要新增：
  - 一个用于全局 Codex 自动化的提示词文档或模板文件
  - 一个 follow-up issue 模板文档
- 明确不做：
  - 不在本计划内直接实现业务代码修复
  - 不在本计划内让全局自动化直接建修复 PR
  - 不把 merge 改成 `Done`

## Non-Goals

- 不改变 `Design Review` 是唯一人工门的规则
- 不改成“每个 PR 一个自动化”
- 不让 `Blocked` 承担通用等待语义

### Task 1: 先为新治理契约补充 prompt 校验

**Files:**
- Modify: `runtime/symphony/scripts/assert_freshquant_workflow_prompt.ps1`
- Modify: `runtime/symphony/scripts/assert_freshquant_merging_prompt.ps1`

**Step 1: Add the failing contract checks**

在 workflow validator 中新增以下必需模式：

```powershell
@{ Name = 'global stewardship state rule'; Pattern = 'Global Stewardship' },
@{ Name = 'merged PR to global stewardship rule'; Pattern = 'merged PR, pending ops -> `Global Stewardship`' },
@{ Name = 'follow-up issue only rule'; Pattern = 'only create follow-up issue' }
```

在 merging validator 中新增以下必需模式：

```powershell
@{ Name = 'merge handoff only rule'; Pattern = 'write the merge handoff comment and move the issue to `Global Stewardship`' },
@{ Name = 'no deploy in merging rule'; Pattern = 'Do not deploy, run health checks, or cleanup in the `Merging` session' }
```

**Step 2: Run the validators to verify they fail against current prompts**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File runtime/symphony/scripts/assert_freshquant_workflow_prompt.ps1 -WorkflowPath runtime/symphony/WORKFLOW.freshquant.md
```

Expected: FAIL because `Global Stewardship` contract is not present yet

Run:

```powershell
powershell -ExecutionPolicy Bypass -File runtime/symphony/scripts/assert_freshquant_merging_prompt.ps1 -PromptPath runtime/symphony/prompts/merging.md
```

Expected: FAIL because current `Merging` prompt still requires deploy / cleanup

**Step 3: Commit**

```bash
git add runtime/symphony/scripts/assert_freshquant_workflow_prompt.ps1 runtime/symphony/scripts/assert_freshquant_merging_prompt.ps1
git commit -m "test: require global stewardship prompt contract"
```

### Task 2: 改正式 workflow，把 merge 后 owner 切到 Global Stewardship

**Files:**
- Modify: `AGENTS.md`
- Modify: `runtime/symphony/WORKFLOW.freshquant.md`

**Step 1: Update the workflow text**

把正式工作流改成：

```md
Issue -> Draft PR -> Design Review(仅高风险) -> In Progress -> Merging -> Global Stewardship -> Done
```

并在 workflow 中补齐以下规则：

```md
- `Merging`: merge the PR, write a merge handoff comment, and move the issue to `Global Stewardship`.
- `Global Stewardship`: global Codex automation handles deploy, health check, cleanup, and follow-up issue creation.
- merged PR, pending ops -> `Global Stewardship`
```

**Step 2: Run the validators to verify workflow passes and merging still fails**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File runtime/symphony/scripts/assert_freshquant_workflow_prompt.ps1 -WorkflowPath runtime/symphony/WORKFLOW.freshquant.md
```

Expected: PASS

Run:

```powershell
powershell -ExecutionPolicy Bypass -File runtime/symphony/scripts/assert_freshquant_merging_prompt.ps1 -PromptPath runtime/symphony/prompts/merging.md
```

Expected: FAIL until Task 3 completes

**Step 3: Commit**

```bash
git add AGENTS.md runtime/symphony/WORKFLOW.freshquant.md
git commit -m "docs: shift merge aftermath into global stewardship"
```

### Task 3: 重写 Merging prompt，只保留 merge + handoff

**Files:**
- Modify: `runtime/symphony/prompts/merging.md`

**Step 1: Replace the current responsibilities**

把现有 `Merging` prompt 中的以下职责删掉：

- deploy every required runtime surface
- run post-deploy health checks
- register cleanup request
- host cleanup finalizer closes the issue

改成：

```md
- Confirm the PR is ready to merge.
- Merge the PR to the remote `main` branch.
- Write the merge handoff comment.
- Move the issue to `Global Stewardship`.
- Do not deploy, run health checks, or cleanup in the `Merging` session.
```

**Step 2: Run the merging validator**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File runtime/symphony/scripts/assert_freshquant_merging_prompt.ps1 -PromptPath runtime/symphony/prompts/merging.md
```

Expected: PASS

**Step 3: Commit**

```bash
git add runtime/symphony/prompts/merging.md
git commit -m "docs: narrow merging to merge handoff only"
```

### Task 4: 为全局 Codex 自动化补充提示词与 follow-up issue 契约

**Files:**
- Create: `runtime/symphony/prompts/global_stewardship.md`
- Create: `runtime/symphony/templates/follow_up_issue.md`
- Modify: `runtime/symphony/scripts/sync_freshquant_symphony_service.ps1`

**Step 1: Write the new prompt and template**

`global_stewardship.md` 至少要写清：

```md
- inspect all open `Global Stewardship` issues
- batch deploy against current `main`
- run health checks
- cleanup covered issues
- if code repair is needed, only create a follow-up issue
```

`follow_up_issue.md` 至少要包含：

```md
- Source Issue
- Source PR
- Source Commit
- Blocks Done Of
- Symptom Class
- Evidence
- Suggested Symphony handoff
```

**Step 2: Verify sync script includes the new files**

Run:

```powershell
Select-String -Path runtime/symphony/scripts/sync_freshquant_symphony_service.ps1 -Pattern 'global_stewardship.md|follow_up_issue.md'
```

Expected: both new files are included in the sync map

**Step 3: Commit**

```bash
git add runtime/symphony/prompts/global_stewardship.md runtime/symphony/templates/follow_up_issue.md runtime/symphony/scripts/sync_freshquant_symphony_service.ps1
git commit -m "feat: add global stewardship automation assets"
```

### Task 5: 同步当前文档事实

**Files:**
- Modify: `docs/current/runtime.md`
- Modify: `docs/current/deployment.md`
- Modify: `docs/current/troubleshooting.md`

**Step 1: Update runtime and deployment docs**

文档必须显式写出：

```md
- `Symphony` 只负责到 merge remote main
- merge 后 issue 进入 `Global Stewardship`
- 单个全局 Codex 自动化统一处理 deploy / health check / cleanup
- 发现代码问题时只创建 follow-up issue，由下一轮 `Symphony` 接手
```

**Step 2: Update troubleshooting**

补以下排障场景：

```md
- issue 长时间停在 `Global Stewardship`
- follow-up issue 重复创建
- merge 后没有写 handoff comment
- 全局自动化误把代码问题当成运维收口问题
```

**Step 3: Verify docs consistency**

Run:

```powershell
Select-String -Path docs/current/runtime.md,docs/current/deployment.md,docs/current/troubleshooting.md -Pattern 'Global Stewardship|follow-up issue|merge 后|批量 deploy'
```

Expected: all three docs mention the new merge-after boundary and follow-up issue rule

**Step 4: Commit**

```bash
git add docs/current/runtime.md docs/current/deployment.md docs/current/troubleshooting.md
git commit -m "docs: document global stewardship governance"
```

### Task 6: 验证正式 contract 与工作树状态

**Files:**
- Test only: `runtime/symphony/scripts/assert_freshquant_workflow_prompt.ps1`
- Test only: `runtime/symphony/scripts/assert_freshquant_merging_prompt.ps1`
- Test only: `runtime/symphony/scripts/sync_freshquant_symphony_service.ps1`

**Step 1: Run final verification**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File runtime/symphony/scripts/assert_freshquant_workflow_prompt.ps1 -WorkflowPath runtime/symphony/WORKFLOW.freshquant.md
```

Expected: PASS

Run:

```powershell
powershell -ExecutionPolicy Bypass -File runtime/symphony/scripts/assert_freshquant_merging_prompt.ps1 -PromptPath runtime/symphony/prompts/merging.md
```

Expected: PASS

Run:

```powershell
git status --short
```

Expected: only files from this governance change are modified

**Step 2: Commit**

```bash
git add AGENTS.md runtime/symphony/WORKFLOW.freshquant.md runtime/symphony/prompts/merging.md runtime/symphony/prompts/global_stewardship.md runtime/symphony/templates/follow_up_issue.md runtime/symphony/scripts/assert_freshquant_workflow_prompt.ps1 runtime/symphony/scripts/assert_freshquant_merging_prompt.ps1 runtime/symphony/scripts/sync_freshquant_symphony_service.ps1 docs/current/runtime.md docs/current/deployment.md docs/current/troubleshooting.md
git commit -m "feat: introduce global stewardship governance"
```

## Execution Notes

- 初期实现先只落治理文本、prompt 契约和自动化提示词，不在同一轮把所有宿主机脚本都重构完
- 如果执行中发现 `Global Stewardship` 需要独立 label / state 映射，优先同步 `AGENTS.md`、workflow 和文档，不要只改其中一处
- follow-up issue 去重建议优先基于 `Source Issue + Symptom Class`
- 如果执行中发现当前全局自动化方案会触发新的“部署/运行面变化”，需要先在 Draft PR 中完成 `Design Review`
