# Daily Screening Layout And Workspace Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 优化每日选股页面的工作台布局和工作区交互，让 100% 缩放可用、工作区点击可看详情，并补齐交集列表单条加入 `pre_pools` 能力。

**Architecture:** 前端继续复用 `/gantt/shouban30` 的共享工作区接口；状态层在 `dailyScreeningPage.mjs` 中补默认筛选开关、分组元数据和单条 append payload helper；页面 `DailyScreening.vue` 负责工作区点击详情联动、右侧卡片重排和弹性高度布局。实现顺序遵守 TDD，先改测试，再做最小实现。

**Tech Stack:** Vue 3、Element Plus、Node test、Flask route 现有共享工作区 API

---

### Task 1: 落设计和计划文档

**Files:**
- Create: `docs/plans/2026-03-20-daily-screening-layout-and-workspace-design.md`
- Create: `docs/plans/2026-03-20-daily-screening-layout-and-workspace.md`

**Step 1: 写设计文档**

记录：
- 100% 缩放裁切的根因
- 单条加入 `pre_pools` 的复用链路
- 右侧卡片重排方案

**Step 2: 写实现计划**

把测试、实现、文档、验证拆成独立任务。

**Step 3: Run git add**

Run: `git add docs/plans/2026-03-20-daily-screening-layout-and-workspace-design.md docs/plans/2026-03-20-daily-screening-layout-and-workspace.md`

**Step 4: Commit**

```bash
git commit -m "docs: add daily screening layout workspace plan"
```

### Task 2: 为状态层写失败测试

**Files:**
- Modify: `morningglory/fqwebui/src/views/dailyScreeningPage.test.mjs`
- Modify: `morningglory/fqwebui/src/views/dailyScreeningPage.mjs`

**Step 1: Write the failing test**

新增测试覆盖：
- `buildDailyScreeningWorkbenchState()` 默认启用 `dayChanlunEnabled`
- `normalizeDailyScreeningFilterCatalog()` 输出“基础池（并集）/交集条件”分组结构
- 单条结果可构造单标的 `append pre_pool` payload

**Step 2: Run test to verify it fails**

Run: `node --test src/views/dailyScreeningPage.test.mjs`

Expected: FAIL，因为默认值、分组结构和单条 payload helper 还没实现。

**Step 3: Write minimal implementation**

在 `dailyScreeningPage.mjs` 中：
- 把默认 `dayChanlunEnabled` 改为 `true`
- 提供页面分组元数据 helper
- 新增单条追加到 `pre_pools` 的 payload 构造函数

**Step 4: Run test to verify it passes**

Run: `node --test src/views/dailyScreeningPage.test.mjs`

Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/dailyScreeningPage.test.mjs morningglory/fqwebui/src/views/dailyScreeningPage.mjs
git commit -m "test: cover daily screening layout state helpers"
```

### Task 3: 为页面结构写失败测试

**Files:**
- Modify: `morningglory/fqwebui/src/views/DailyScreening.test.mjs`
- Modify: `morningglory/fqwebui/src/views/dailyScreeningPage.test.mjs`

**Step 1: Write the failing test**

新增断言覆盖：
- “工作台说明”渲染为标签行
- 交集列表存在单条“加入 pre_pools”列
- 工作区表格存在 `row-click` 详情联动
- 右侧不存在独立“日线缠论涨幅”卡
- 右侧存在紧凑详情卡区和更高的“历史热门理由”区

**Step 2: Run test to verify it fails**

Run: `node --test src/views/dailyScreeningPage.test.mjs src/views/DailyScreening.test.mjs`

Expected: FAIL，因为模板和样式尚未调整。

**Step 3: Commit the failing test only**

```bash
git add morningglory/fqwebui/src/views/DailyScreening.test.mjs morningglory/fqwebui/src/views/dailyScreeningPage.test.mjs
git commit -m "test: define daily screening layout expectations"
```

### Task 4: 实现页面交互和布局

**Files:**
- Modify: `morningglory/fqwebui/src/views/DailyScreening.vue`
- Modify: `morningglory/fqwebui/src/api/ganttShouban30.js`
- Reference: `morningglory/fqwebui/src/views/shouban30PoolWorkspace.mjs`

**Step 1: 实现单条加入 pre_pools**

在 `DailyScreening.vue`：
- 为交集列表增加操作列
- 按行调用共享 `appendShouban30PrePool`
- 成功提示区分追加数和去重跳过数

**Step 2: 实现工作区点击详情联动**

在 `DailyScreening.vue`：
- 工作区表格增加 `@row-click`
- 点击 `pre_pools / stock_pools` 任一行都调用 `loadDetail`

**Step 3: 实现筛选分组与默认开关**

在 `DailyScreening.vue`：
- 把 `CLS 模型分组` 和 `热门窗口` 渲染到“基础池（并集）”组
- 其他条件渲染到“交集条件”组
- scope 切换重置时保持 `dayChanlunEnabled = true`

**Step 4: 重排右侧详情区**

在 `DailyScreening.vue`：
- 删除独立“日线缠论涨幅”卡
- 新增紧凑详情卡区
- 把“历史热门理由”放到剩余高度主区域

**Step 5: 修正弹性布局**

在 `DailyScreening.vue` 样式中：
- 去掉页面内部写死表格高度
- 用 `workbench-table-wrap` 和 `flex: 1 1 auto` 承载表格
- 让中间区、右侧区和历史热门理由区可在 100% 缩放下完整展示

**Step 6: Run tests to verify they pass**

Run: `node --test src/views/dailyScreeningPage.test.mjs src/views/DailyScreening.test.mjs`

Expected: PASS

**Step 7: Commit**

```bash
git add morningglory/fqwebui/src/views/DailyScreening.vue morningglory/fqwebui/src/api/ganttShouban30.js
git commit -m "feat: optimize daily screening layout and workspace"
```

### Task 5: 更新当前文档

**Files:**
- Modify: `docs/current/modules/daily-screening.md`

**Step 1: Write the doc update**

补充：
- 工作区点击行也会加载完整详情
- 交集列表支持单条加入 `pre_pools`
- `日线缠论涨幅` 默认启用
- 页面布局按弹性高度收口，适配 100% 缩放

**Step 2: Run docs consistency check**

人工核对接口、页面行为和文档描述一致。

**Step 3: Commit**

```bash
git add docs/current/modules/daily-screening.md
git commit -m "docs: sync daily screening layout behavior"
```

### Task 6: 验证与收口

**Files:**
- Modify if needed: `freshquant/tests/test_daily_screening_routes.py`
- Modify if needed: `freshquant/tests/test_gantt_routes.py`

**Step 1: Run frontend logic and structure tests**

Run: `node --test src/views/dailyScreeningPage.test.mjs src/views/DailyScreening.test.mjs`
Workdir: `morningglory/fqwebui`

Expected: PASS

**Step 2: Run targeted backend tests**

Run: `py -3.12 -m pytest freshquant/tests/test_daily_screening_routes.py freshquant/tests/test_gantt_routes.py -q`

Expected: PASS

**Step 3: Run build**

Run: `npm run build`
Workdir: `morningglory/fqwebui`

Expected: PASS

**Step 4: Inspect git status**

Run: `git status --short`

Expected: 只有本次任务相关变更。

**Step 5: Prepare PR branch**

Run: `git push origin codex/daily-screening-workbench-20260320`

Expected: 远端分支更新成功，可继续走 PR。
