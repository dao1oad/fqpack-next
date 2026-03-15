# Gantt Shouban30 UI Adjustments Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让 `/gantt/shouban30` 的工作区行也能驱动标的详情，把工作区操作列移动到名称列后，并支持把当前多条件筛选结果批量追加到 `pre_pools`。

**Architecture:** 继续以 `GanttShouban30Phase1.vue` 作为页面编排层，复用现有的 `selectedStockCode6 -> loadStockReasons()` 详情加载链路，不新增后端接口。批量加入 `pre_pools` 复用 `shouban30PoolWorkspace.mjs` 里已有的 payload 生成逻辑，并通过测试先锁定顺序、去重和 extra filter 透传语义。

**Tech Stack:** Vue 3 SFC、Element Plus、Node test runner、Vite

---

### Task 1: 锁定工作区 payload 语义

**Files:**
- Modify: `morningglory/fqwebui/src/views/shouban30PoolWorkspace.test.mjs`
- Modify: `morningglory/fqwebui/src/views/shouban30PoolWorkspace.mjs`
- Test: `morningglory/fqwebui/src/views/shouban30PoolWorkspace.test.mjs`

**Step 1: Write the failing test**

在 `shouban30PoolWorkspace.test.mjs` 新增测试，覆盖 `buildCurrentFilterReplacePrePoolPayload(...)`：

- 输入两个板块、多个标的
- 断言输出保持“页面板块顺序 + 板块内标的顺序”
- 断言跨板块重复 `code6` 会被去重
- 断言 `days / end_date / selected_extra_filters` 会正确保留

**Step 2: Run test to verify it fails**

Run: `node --test src/views/shouban30PoolWorkspace.test.mjs`
Expected: FAIL，因为新测试引用的行为当前还没有被显式锁定或导出使用。

**Step 3: Write minimal implementation**

如果测试暴露当前 helper 的行为不完整，就在 `shouban30PoolWorkspace.mjs` 做最小补强，保持：

- 不引入新 helper 层级
- 只补当前筛选结果 payload 所需的最小逻辑

**Step 4: Run test to verify it passes**

Run: `node --test src/views/shouban30PoolWorkspace.test.mjs`
Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/shouban30PoolWorkspace.mjs morningglory/fqwebui/src/views/shouban30PoolWorkspace.test.mjs
git commit -m "test: lock shouban30 current-filter pre-pool payload"
```

### Task 2: 实现页面交互改动

**Files:**
- Modify: `morningglory/fqwebui/src/views/GanttShouban30Phase1.vue`
- Modify: `morningglory/fqwebui/src/views/shouban30PoolWorkspace.mjs`
- Test: `morningglory/fqwebui/src/views/shouban30PoolWorkspace.test.mjs`

**Step 1: Write the failing test**

如果 Task 1 后还缺少可复用字段，在 `shouban30PoolWorkspace.test.mjs` 继续补最小测试，锁定工作区 tab row 能暴露详情所需字段，例如：

- `code6`
- `name`
- `provider`
- `plate_name`

**Step 2: Run test to verify it fails**

Run: `node --test src/views/shouban30PoolWorkspace.test.mjs`
Expected: FAIL，说明工作区映射结果还缺少页面要消费的数据。

**Step 3: Write minimal implementation**

在 `GanttShouban30Phase1.vue` 完成以下最小实现：

- 新增“当前详情上下文”计算属性，优先使用热点标的，其次回退到工作区选中行
- 工作区表格增加 `@row-click`，点击后设置当前选中 `code6`
- 工作区表格复用 `row-class-name` 高亮当前选中行
- 标题和理由弹层副标题改为读取“当前详情上下文”
- 把工作区“操作”列移动到“名称”列后
- 在“筛选”按钮后新增“全部加入 pre_pools”，调用 `appendShouban30PrePool(buildCurrentFilterReplacePrePoolPayload(...))`
- 当前筛选结果为空时弹出 warning，不发请求

**Step 4: Run test to verify it passes**

Run: `node --test src/views/shouban30PoolWorkspace.test.mjs`
Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/GanttShouban30Phase1.vue morningglory/fqwebui/src/views/shouban30PoolWorkspace.mjs morningglory/fqwebui/src/views/shouban30PoolWorkspace.test.mjs
git commit -m "feat: improve shouban30 workspace interactions"
```

### Task 3: 回归验证与文档确认

**Files:**
- Modify: `docs/current/modules/shouban30-screening.md`（仅当当前系统事实发生变化时）
- Test: `morningglory/fqwebui/package.json`

**Step 1: Write the failing test**

本任务不新增测试文件，直接做完整验证。

**Step 2: Run test to verify it fails**

如果 `npm run test:shouban30` 或 `npm run build` 失败，先记录真实失败点，再回到前一任务修复。

**Step 3: Write minimal implementation**

仅在页面事实描述发生变化时，同步更新 `docs/current/modules/shouban30-screening.md`：

- 工作区点击也会联动标的详情
- 条件筛选区支持“全部加入 pre_pools”

**Step 4: Run test to verify it passes**

Run: `npm run test:shouban30`
Expected: PASS

Run: `npm run build`
Expected: exit 0

**Step 5: Commit**

```bash
git add docs/current/modules/shouban30-screening.md morningglory/fqwebui/src/views/GanttShouban30Phase1.vue morningglory/fqwebui/src/views/shouban30PoolWorkspace.mjs morningglory/fqwebui/src/views/shouban30PoolWorkspace.test.mjs
git commit -m "docs: sync shouban30 workspace UI behavior"
```
