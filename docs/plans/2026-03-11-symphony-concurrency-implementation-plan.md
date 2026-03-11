# Symphony 按状态并发配置 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 FreshQuant 正式 Symphony workflow 从全局串行改为按状态并发，允许最多两个 `In Progress` issue 并行执行。

**Architecture:** 先更新设计稿与迁移进度，再修改正式 workflow 模板和治理说明，最后同步宿主机运行目录并通过状态接口确认服务仍正常提供 UI/API。

**Tech Stack:** Markdown, YAML, PowerShell, Symphony workflow templates

---

### Task 1: 落设计稿与进度记录

**Files:**
- Create: `docs/plans/2026-03-11-symphony-concurrency-design.md`
- Create: `docs/plans/2026-03-11-symphony-concurrency-implementation-plan.md`
- Modify: `docs/migration/progress.md`

**Step 1: 写设计稿**

把并发目标、方案对比、推荐方案和验收标准写入设计稿。

**Step 2: 更新进度表**

在 `0028` 的说明里追加“按状态并发配置”增量。

**Step 3: 自检文件路径**

Run: `rg -n "symphony-concurrency|max_concurrent_agents_by_state" docs/plans docs/migration/progress.md -S`
Expected: 新设计稿和进度更新可被检出

### Task 2: 修改正式 workflow 模板

**Files:**
- Modify: `runtime/symphony/WORKFLOW.freshquant.md`

**Step 1: 把全局并发上限改为 2**

将：

- `max_concurrent_agents: 1`

改为：

- `max_concurrent_agents: 2`

**Step 2: 增加状态级并发覆盖**

新增：

```yaml
max_concurrent_agents_by_state:
  Todo: 1
  In Progress: 2
  Rework: 1
  Merging: 1
```

**Step 3: 自检配置字段**

Run: `rg -n "max_concurrent_agents|max_concurrent_agents_by_state|Todo: 1|In Progress: 2|Rework: 1|Merging: 1" runtime/symphony/WORKFLOW.freshquant.md -S`
Expected: 新并发字段全部可被检出

### Task 3: 更新治理文档

**Files:**
- Modify: `runtime/symphony/README.md`
- Modify: `docs/agent/Symphony正式接入治理说明.md`

**Step 1: 更新 README**

明确：

- 正式运行继续使用单实例 orchestrator
- issue 级并发采用按状态策略
- `Todo/Rework/Merging` 保守串行
- `In Progress` 允许双并发

**Step 2: 更新治理说明**

在运行与轮询说明里补充按状态并发规则和原因。

**Step 3: 运行关键词检查**

Run: `rg -n "并发|max_concurrent_agents_by_state|Todo=1|In Progress=2|Rework=1|Merging=1" runtime/symphony/README.md docs/agent/Symphony正式接入治理说明.md -S`
Expected: 两份文档都能检出新规则

### Task 4: 同步服务运行目录并验证

**Files:**
- Modify: `runtime/symphony/WORKFLOW.freshquant.md`
- Modify: `runtime/symphony/README.md`
- Modify: `docs/agent/Symphony正式接入治理说明.md`
- Modify: `docs/migration/progress.md`

**Step 1: 同步宿主机运行目录**

Run: `powershell -ExecutionPolicy Bypass -File runtime/symphony/scripts/sync_freshquant_symphony_service.ps1`
Expected: 输出 `synchronized symphony service runtime`

**Step 2: 检查部署后的 workflow 文件**

Run: `Get-Content D:\\fqpack\\runtime\\symphony-service\\config\\WORKFLOW.freshquant.md -TotalCount 40`
Expected: 能看到 `max_concurrent_agents: 2` 和 `max_concurrent_agents_by_state`

**Step 3: 验证服务状态接口**

Run: `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:40123/api/v1/state`
Expected: 返回 `200`

### Task 5: 最小验证与提交

**Files:**
- Modify: all files touched above

**Step 1: 运行最小测试**

Run: `py -3 -m pytest test_enum_serialization.py -q`
Expected: `1 passed`

**Step 2: 检查 patch 完整性**

Run: `git diff --check`
Expected: 无 trailing whitespace、无 patch 错误

**Step 3: 检查工作树状态**

Run: `git status --short --branch`
Expected: 仅包含本轮改动

**Step 4: 提交**

```bash
git add docs/plans/2026-03-11-symphony-concurrency-design.md docs/plans/2026-03-11-symphony-concurrency-implementation-plan.md docs/migration/progress.md runtime/symphony/WORKFLOW.freshquant.md runtime/symphony/README.md docs/agent/Symphony正式接入治理说明.md
git commit -m "ops: 调整 Symphony 的按状态并发配置"
```
