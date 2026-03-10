# Symphony First 全仓治理 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 FreshQuant 的正式开发治理切换为 `Linear-first + Symphony-first + design-approval-first`，并落地配套 RFC、仓库治理文档、迁移记录与 repo-versioned Symphony workflow 模板。

**Architecture:** 先把治理合法化，再写运行模板。第一段只处理仓库内治理工件：RFC、`AGENTS.md`、迁移记录、`docs/agent`；第二段把正式 `Linear` 状态机与 Symphony 提示词/评论模板固化到仓库内 `runtime/symphony/`。运行时继续采用当前 30 秒轮询，不先改成 webhook。

**Tech Stack:** Markdown, Git, Linear, Symphony workflow templates, PowerShell, GitHub PR conventions

---

### Task 1: 起草治理 RFC 并登记迁移进度

**Files:**
- Create: `docs/rfcs/0028-symphony-first-governance.md`
- Modify: `docs/migration/progress.md`
- Reference: `docs/plans/2026-03-10-symphony-governance-design.md`
- Reference: `docs/rfcs/0000-template.md`

**Step 1: 写失败前提检查**

Run:

```powershell
Test-Path docs/rfcs/0028-symphony-first-governance.md
```

Expected: `False`

**Step 2: 起草 RFC 0028**

按模板落盘，并覆盖这些内容：

- 背景：现有 `AGENTS.md` 与 Symphony 默认模式冲突
- 目标：全仓统一切到 Symphony-first
- 非目标：不先引入 webhook、不自动执行部署/删库/.env 修改
- 范围：Linear 状态机、分支/PR 策略、设计批准门、自动化权限边界
- 模块边界：`Linear issue` 是唯一入口，`Symphony-managed workspace` 是合法工作区
- Public API：Linear 状态机与 Symphony 模板/评论协议
- Data/Config：`runtime/symphony/WORKFLOW.freshquant.md`、`LINEAR_API_KEY`、project slug
- Breaking Changes：废止全仓强制 `git worktree + feature branch`、废止 reviewer-first
- 迁移映射：当前 `AGENTS.md` 规则如何收口到 Symphony-first
- Acceptance Criteria：状态机、设计批准门、PR/CI、风险边界均可验证

**Step 3: 在 `progress.md` 增加 RFC 0028 行**

新增一行，初始状态为 `Draft`，备注写清：

- 这是全仓治理切换 RFC
- 影响 `AGENTS.md`、`docs/agent`、`runtime/symphony`

**Step 4: 验证 RFC 与进度行**

Run:

```powershell
Select-String -Path docs/rfcs/0028-symphony-first-governance.md -Pattern "Linear-first|Symphony-first|Human Review|In Progress"
Select-String -Path docs/migration/progress.md -Pattern "0028|Symphony"
```

Expected:

- RFC 中能命中核心治理词
- `progress.md` 中出现 RFC 0028 行

**Step 5: Commit**

```bash
git add docs/rfcs/0028-symphony-first-governance.md docs/migration/progress.md
git commit -m "docs: 起草 symphony first 治理 RFC"
```

### Task 2: 完成 RFC 评审状态切换并锁定审批门

**Files:**
- Modify: `docs/rfcs/0028-symphony-first-governance.md`
- Modify: `docs/migration/progress.md`

**Step 1: 先把 RFC 推到 Review**

将 RFC 状态改为 `Review`，并在 `progress.md` 同步状态。

**Step 2: 明确唯一人工门**

在 RFC 中显式写死：

- 唯一审批真值是 `Human Review -> In Progress`
- `Linear comment` 只承载意见，不承载批准真值
- 设计阶段不开 PR

**Step 3: 审批通过后改为 `Approved`**

当设计被人工批准后：

- RFC 状态改为 `Approved`
- `progress.md` 同步改为 `Approved`

**Step 4: 验证状态同步**

Run:

```powershell
Select-String -Path docs/rfcs/0028-symphony-first-governance.md -Pattern "状态.*Approved|Human Review -> In Progress"
Select-String -Path docs/migration/progress.md -Pattern "0028.*Approved"
```

Expected:

- RFC 中出现 `Approved`
- 进度表中的 RFC 0028 也为 `Approved`

**Step 5: Commit**

```bash
git add docs/rfcs/0028-symphony-first-governance.md docs/migration/progress.md
git commit -m "docs: 批准 symphony first 治理 RFC"
```

### Task 3: 改写 `AGENTS.md` 为 Symphony-first 治理

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/migration/progress.md`
- Reference: `docs/rfcs/0028-symphony-first-governance.md`

**Step 1: 写差异检查**

Run:

```powershell
Select-String -Path AGENTS.md -Pattern "git worktree \+ feature branch|reviewer Approve|禁止在本地 `main` 分支直接开发"
```

Expected: 当前仍命中旧治理文案

**Step 2: 重写治理关键段落**

把以下内容改成新治理：

- 开发入口：`Linear issue` 是唯一任务入口
- 编排器：`Symphony` 是默认执行编排器
- 人工门：只保留设计批准
- 工作区：允许并默认使用 `Symphony-managed workspace/repo copy`
- Git/GitHub：保留 `feature branch -> PR -> merge` 与 `禁止直推 main`
- reviewer 规则：不再把 GitHub reviewer approve 当成强制仓内人工门

**Step 3: 保留但重写 RFC / progress / breaking-changes 规则**

确保 `AGENTS.md` 仍保留：

- RFC 前置
- `docs/migration/progress.md`
- `docs/migration/breaking-changes.md`

但描述要改成由 Symphony 在 issue 分支上自动产出和更新。

**Step 4: 同步 `progress.md` 到 `Implementing`**

开始实际改写治理文档时，将 RFC 0028 状态改为 `Implementing`，并在备注里写明：

- `AGENTS.md` 改写进行中
- `docs/agent` 与 `runtime/symphony` 待同步

**Step 5: 验证新旧文案切换**

Run:

```powershell
Select-String -Path AGENTS.md -Pattern "Linear issue|Symphony-managed workspace|Human Review|In Progress"
Select-String -Path AGENTS.md -Pattern "强制使用 git worktree \\+ feature 分支开展修改"
Select-String -Path docs/migration/progress.md -Pattern "0028.*Implementing"
```

Expected:

- 新治理关键字命中
- 旧的 worktree 强制文案不再命中
- RFC 0028 处于 `Implementing`

**Step 6: Commit**

```bash
git add AGENTS.md docs/migration/progress.md
git commit -m "docs: 改写 AGENTS 为 symphony first 治理"
```

### Task 4: 更新 `docs/agent` 的正式接入说明

**Files:**
- Create: `docs/agent/Symphony正式接入治理说明.md`
- Modify: `docs/agent/Symphony本地安装与使用指南.md`
- Modify: `docs/agent/index.md`

**Step 1: 写文件存在性检查**

Run:

```powershell
Test-Path docs/agent/Symphony正式接入治理说明.md
```

Expected: `False`

**Step 2: 新增正式接入说明**

新文档至少覆盖：

- 任务粒度：一个需求一个 Linear issue
- Linear 状态机：`Todo / Human Review / In Progress / Rework / Merging / Done`
- 审批规则：`Human Review -> In Progress`
- 分支/PR 策略
- 默认 `subagent + TDD`
- 自动化权限边界

**Step 3: 改写本地安装指南中的“当前不做”结论**

把旧结论更新为：

- 本地安装仍可用于 smoke test
- 正式接入已转为仓库治理目标
- 引用新建的正式接入治理说明与 RFC 0028

**Step 4: 更新文档索引**

在 `docs/agent/index.md` 增加：

- 正式接入治理说明入口
- 本地安装指南与正式治理说明的交叉引用

**Step 5: 验证文档入口**

Run:

```powershell
Select-String -Path docs/agent/Symphony正式接入治理说明.md -Pattern "Linear issue|Human Review|subagent|TDD"
Select-String -Path docs/agent/Symphony本地安装与使用指南.md -Pattern "正式接入|RFC 0028"
Select-String -Path docs/agent/index.md -Pattern "Symphony正式接入治理说明"
```

Expected:

- 三个文件都能命中新增正式接入内容

**Step 6: Commit**

```bash
git add docs/agent/Symphony正式接入治理说明.md docs/agent/Symphony本地安装与使用指南.md docs/agent/index.md
git commit -m "docs: 补充 symphony 正式接入治理说明"
```

### Task 5: 固化 repo-versioned Symphony 正式 workflow 模板

**Files:**
- Create: `runtime/symphony/README.md`
- Create: `runtime/symphony/WORKFLOW.freshquant.md`
- Create: `runtime/symphony/prompts/todo.md`
- Create: `runtime/symphony/prompts/in_progress.md`
- Create: `runtime/symphony/templates/human_review_comment.md`
- Reference: `docs/rfcs/0028-symphony-first-governance.md`

**Step 1: 写失败前提检查**

Run:

```powershell
Test-Path runtime/symphony/WORKFLOW.freshquant.md
Test-Path runtime/symphony/prompts/todo.md
```

Expected: 都是 `False`

**Step 2: 创建 `README.md`**

说明：

- 这是 FreshQuant 正式 Symphony workflow 模板目录
- 继续使用 30 秒轮询
- 当前 tracker 是 `Linear`
- 这里的文件是 versioned template，不直接保存 secrets

**Step 3: 创建 `WORKFLOW.freshquant.md`**

至少写清：

- `tracker.kind = linear`
- `active_states = Todo, In Progress, Rework, Merging`
- `Human Review` 不在 active states
- workspace 为 `Symphony-managed workspace/repo copy`
- 设计阶段不开 PR，实现阶段开 `Draft PR`
- 默认方法论：`subagent-driven-development + TDD`

**Step 4: 创建阶段 prompt 与评论模板**

- `prompts/todo.md`：只允许调研/设计/RFC/实施计划，禁止编码
- `prompts/in_progress.md`：默认 `subagent + TDD + verification`
- `templates/human_review_comment.md`：要求输出 RFC、计划、任务清单、风险、批准说明

**Step 5: 验证模板内容**

Run:

```powershell
Select-String -Path runtime/symphony/WORKFLOW.freshquant.md -Pattern "linear|Todo|Human Review|In Progress|Rework|Merging"
Select-String -Path runtime/symphony/prompts/todo.md -Pattern "不允许编码|RFC|implementation plan"
Select-String -Path runtime/symphony/prompts/in_progress.md -Pattern "subagent|TDD|RED|GREEN"
Select-String -Path runtime/symphony/templates/human_review_comment.md -Pattern "RFC|task checklist|Human Review|In Progress"
```

Expected:

- 4 个文件都命中对应状态机和方法论关键词

**Step 6: Commit**

```bash
git add runtime/symphony/README.md runtime/symphony/WORKFLOW.freshquant.md runtime/symphony/prompts/todo.md runtime/symphony/prompts/in_progress.md runtime/symphony/templates/human_review_comment.md
git commit -m "docs: 固化 symphony 正式 workflow 模板"
```

### Task 6: 登记破坏性变更并完成一致性校验

**Files:**
- Modify: `docs/migration/breaking-changes.md`
- Modify: `docs/migration/progress.md`
- Reference: `AGENTS.md`
- Reference: `docs/rfcs/0028-symphony-first-governance.md`

**Step 1: 追加 breaking change 记录**

登记：

- 废止全仓强制 `git worktree + feature branch`
- 废止 reviewer-first 人工门
- 切换到 `Linear issue -> Symphony workspace -> feature branch -> PR -> merge`
- 影响面、迁移步骤、回滚方案

**Step 2: 将 RFC 0028 标记为 `Done`**

在 `progress.md` 中把 RFC 0028 改为 `Done`，备注写明：

- `AGENTS.md` 已完成改写
- `docs/agent` 已同步
- `runtime/symphony` 正式模板已入仓

**Step 3: 做一致性检查**

Run:

```powershell
Select-String -Path docs/migration/breaking-changes.md -Pattern "0028|git worktree|Linear issue|Symphony"
Select-String -Path docs/migration/progress.md -Pattern "0028.*Done"
Select-String -Path AGENTS.md -Pattern "Linear issue|Symphony-managed workspace|Human Review|In Progress"
Select-String -Path runtime/symphony/WORKFLOW.freshquant.md -Pattern "Todo|In Progress|Rework|Merging"
```

Expected:

- breaking change 已登记 RFC 0028
- progress 显示 `Done`
- `AGENTS.md` 与 workflow 模板的状态机表述一致

**Step 4: Commit**

```bash
git add docs/migration/breaking-changes.md docs/migration/progress.md AGENTS.md runtime/symphony
git commit -m "docs: 完成 symphony first 治理切换"
```
