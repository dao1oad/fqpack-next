# Runtime Observability Home Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 `/runtime-observability` 页面重构为“异常优先 -> 最近链路流 -> 组件看板”的无输入首页，并把现有 5 个查询输入框降级为默认隐藏的高级筛选抽屉。

**Architecture:** 保持后端 `/api/runtime/*` 契约不变，只改前端消费层。新的首页数据全部从现有 `traces` 和 `health/summary` 响应在前端派生，重用现有 trace 详情、raw drawer 和 step inspector。所有新聚合逻辑尽量下沉到 `runtimeObservability.mjs`，让 `RuntimeObservability.vue` 只负责状态编排和展示。

**Tech Stack:** Vue 3、Element Plus、Node test runner (`node --test`)、Vite、现有 `runtimeObservability.mjs` 纯函数 helper。

---

### Task 1: 为首页三段式聚合逻辑补纯函数测试

**Files:**
- Modify: `morningglory/fqwebui/src/views/runtime-observability.test.mjs`
- Reference: `morningglory/fqwebui/src/views/runtimeObservability.mjs`

**Step 1: 写失败测试，覆盖异常优先卡片聚合**

补测试数据，断言新 helper 产出：

```javascript
test('buildIssuePriorityCards prioritizes failed traces before warnings', () => {
  const cards = buildIssuePriorityCards(sampleTraces)
  assert.equal(cards[0].status, 'failed')
  assert.ok(cards[0].headline.includes('position_gate'))
})
```

**Step 2: 运行测试并确认失败**

Run:

```bash
node --test src/views/runtime-observability.test.mjs
```

Expected:

- 失败于 `buildIssuePriorityCards is not defined` 或断言不成立

**Step 3: 写失败测试，覆盖最近链路流与默认条数**

```javascript
test('buildRecentTraceFeed returns latest 20 rows by default', () => {
  const feed = buildRecentTraceFeed(sampleTraces)
  assert.equal(feed.length, 20)
  assert.equal(feed[0].last_ts, '2026-03-09T10:00:20+08:00')
})
```

**Step 4: 写失败测试，覆盖组件看板聚合与组件点击过滤**

```javascript
test('buildComponentBoard summarizes core component issue counts', () => {
  const board = buildComponentBoard(sampleTraces, sampleHealthCards)
  assert.equal(board.cards[0].component, 'order_submit')
  assert.ok(board.cards[0].issue_trace_count >= 1)
})

test('applyBoardFilter narrows traces by selected component', () => {
  const filtered = applyBoardFilter(sampleTraces, { component: 'order_submit' })
  assert.ok(filtered.every((trace) => trace.steps.some((step) => step.component === 'order_submit')))
})
```

**Step 5: 运行测试并确认以上新增用例全部失败**

Run:

```bash
node --test src/views/runtime-observability.test.mjs
```

Expected:

- 新增测试失败
- 旧测试仍通过

**Step 6: Commit**

```bash
git add morningglory/fqwebui/src/views/runtime-observability.test.mjs
git commit -m "test: 覆盖运行观测首页三段式聚合"
```

### Task 2: 在 helper 层实现首页三段式数据派生

**Files:**
- Modify: `morningglory/fqwebui/src/views/runtimeObservability.mjs`
- Test: `morningglory/fqwebui/src/views/runtime-observability.test.mjs`

**Step 1: 实现异常优先卡片 helper**

新增纯函数，输入 `traces`，输出卡片数组：

```javascript
export const buildIssuePriorityCards = (traces = [], options = {}) => {
  const limit = Number(options.limit || 6)
  return normalizeTraces(traces)
    .map((trace) => {
      const detail = buildTraceDetail(trace)
      const meta = buildTraceSummaryMeta(detail)
      return {
        trace_key: detail.trace_key,
        trace_id: detail.trace_id,
        symbol: detail.symbol,
        status: meta.first_issue?.status || detail.last_status,
        headline: meta.first_issue ? `${meta.first_issue.component}.${meta.first_issue.node}` : '当前无异常',
        subline: meta.last_issue ? `${meta.last_issue.component}.${meta.last_issue.node}` : detail.last_node,
        issue_count: detail.issue_count,
        total_duration_label: detail.total_duration_label,
      }
    })
    .filter((card) => card.issue_count > 0)
    .sort(compareIssueCards)
    .slice(0, limit)
}
```

**Step 2: 实现最近链路流 helper**

新增：

```javascript
export const buildRecentTraceFeed = (traces = [], options = {}) => {
  const limit = Number(options.limit || 20)
  return sortTraceSummaries(traces.map((trace) => summarizeTrace(trace)))
    .sort((left, right) => String(right.last_ts || '').localeCompare(String(left.last_ts || '')))
    .slice(0, limit)
    .map((row) => ({
      ...row,
      path_summary: buildTracePathSummary(row),
      spotlight_nodes: row.path_nodes?.slice(0, 3) || [],
    }))
}
```

**Step 3: 实现组件看板 helper**

新增：

```javascript
export const buildComponentBoard = (traces = [], components = []) => {
  return {
    cards: buildComponentStatusCards(traces, components),
    distribution: buildComponentIssueDistribution(traces),
  }
}
```

并限定核心组件白名单，避免页面被无关组件刷满。

**Step 4: 实现首页过滤 helper**

新增：

```javascript
export const applyBoardFilter = (traces = [], filter = {}) => {
  const component = toText(filter.component)
  if (!component) return normalizeTraces(traces)
  return normalizeTraces(traces).filter((trace) =>
    Array.isArray(trace.steps) && trace.steps.some((step) => toText(step?.component) === component)
  )
}
```

**Step 5: 运行测试并确认 helper 逻辑通过**

Run:

```bash
node --test src/views/runtime-observability.test.mjs
```

Expected:

- 所有 helper 测试通过

**Step 6: Commit**

```bash
git add morningglory/fqwebui/src/views/runtimeObservability.mjs morningglory/fqwebui/src/views/runtime-observability.test.mjs
git commit -m "feat: 增加运行观测首页聚合 helper"
```

### Task 3: 重排页面主视图为三段式首页

**Files:**
- Modify: `morningglory/fqwebui/src/views/RuntimeObservability.vue`
- Reference: `morningglory/fqwebui/src/views/runtimeObservability.mjs`

**Step 1: 写最小模板改造，移除首页直出输入框**

将当前：

- `trace-toolbar`
- `trace-list-summary`
- `trace-layout`

重排为：

- 顶部轻量工具行
- `issue-priority-section`
- `recent-trace-feed-section`
- `component-board-section`
- 详情区继续保留在下半区或右侧

保留现有 `trace-detail` 和 `step-inspector` 结构，不重造详情面板。

**Step 2: 新增首页状态**

新增本地状态：

```javascript
const advancedFilterVisible = ref(false)
const autoRefresh = ref(false)
const boardFilter = reactive({ component: '' })
const recentTraceLimit = ref(20)
```

**Step 3: 新增三段式 computed**

新增：

```javascript
const boardFilteredTraces = computed(() => applyBoardFilter(traces.value, boardFilter))
const issuePriorityCards = computed(() => buildIssuePriorityCards(boardFilteredTraces.value))
const recentTraceFeed = computed(() => buildRecentTraceFeed(boardFilteredTraces.value, { limit: recentTraceLimit.value }))
const componentBoard = computed(() => buildComponentBoard(boardFilteredTraces.value, healthCards.value))
```

**Step 4: 让卡片、链路流、组件卡都复用现有 trace 选择逻辑**

卡片和链路流点击都走：

```javascript
await handleTraceClick(rowLikeObject)
```

组件点击走：

```javascript
const handleComponentFilter = (component) => {
  boardFilter.component = component
}
```

**Step 5: 运行构建，确认模板与脚本都能通过**

Run:

```bash
npm run build
```

Expected:

- 构建成功
- 无 `RuntimeObservability.vue` 编译错误

**Step 6: Commit**

```bash
git add morningglory/fqwebui/src/views/RuntimeObservability.vue
git commit -m "feat: 重排运行观测首页为三段式"
```

### Task 4: 将旧查询栏降级为高级筛选抽屉

**Files:**
- Modify: `morningglory/fqwebui/src/views/RuntimeObservability.vue`
- Reference: `morningglory/fqwebui/src/views/runtimeObservability.mjs`

**Step 1: 将 5 个输入框迁入抽屉**

新增 `el-drawer`：

```vue
<el-drawer v-model="advancedFilterVisible" title="高级筛选" size="420px">
  <div class="advanced-filter-grid">
    <el-input v-model="query.trace_id" clearable placeholder="trace_id" />
    <el-input v-model="query.request_id" clearable placeholder="request_id" />
    <el-input v-model="query.internal_order_id" clearable placeholder="internal_order_id" />
    <el-input v-model="query.symbol" clearable placeholder="symbol" />
    <el-input v-model="query.component" clearable placeholder="component" />
  </div>
  <div class="advanced-filter-actions">
    <el-button @click="resetAdvancedFilter">清空</el-button>
    <el-button type="primary" @click="applyAdvancedFilter">应用</el-button>
  </div>
</el-drawer>
```

**Step 2: 保留现有查询逻辑**

`loadTraces()` 仍使用 `buildTraceQuery(query)`。

新增：

```javascript
const applyAdvancedFilter = async () => {
  await loadTraces()
  advancedFilterVisible.value = false
}
```

**Step 3: 在页面顶部展示轻量筛选摘要**

新增一个 chip 区，显示：

- 当前组件过滤
- 当前是否仅异常
- 高级筛选是否带了 `trace_id/request_id/order_id/symbol`

**Step 4: 运行测试和构建**

Run:

```bash
node --test src/views/runtime-observability.test.mjs
npm run build
```

Expected:

- helper 测试仍通过
- 抽屉改造未破坏页面构建

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/RuntimeObservability.vue
git commit -m "feat: 增加运行观测高级筛选抽屉"
```

### Task 5: 补首页交互细节并做最终验证

**Files:**
- Modify: `morningglory/fqwebui/src/views/RuntimeObservability.vue`
- Modify: `morningglory/fqwebui/src/views/runtime-observability.test.mjs`
- Verify: `morningglory/fqwebui/src/views/runtimeObservability.mjs`

**Step 1: 增加自动刷新与最近链路展开逻辑**

实现：

```javascript
let refreshTimer = null

watch(autoRefresh, (enabled) => {
  clearInterval(refreshTimer)
  if (enabled) refreshTimer = setInterval(loadOverview, 15000)
})

const expandRecentFeed = () => {
  recentTraceLimit.value = 50
}
```

并在组件卸载时清理定时器。

**Step 2: 增加无异常空态与滚动引导**

当 `issuePriorityCards.length === 0` 时，展示空态按钮：

```javascript
const scrollToRecentFeed = () => {
  recentFeedRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
```

**Step 3: 为首页交互新增纯函数或最小行为测试**

在测试文件补至少两类断言：

- 最近链路流展开到 `50`
- 组件过滤后异常区和最近链路流都被正确裁剪

**Step 4: 跑完整前端验证**

Run:

```bash
node --test src/views/runtime-observability.test.mjs
npm run build
```

Expected:

- `node --test` 全部通过
- `npm run build` 成功

**Step 5: 跑仓库级格式化/静态检查**

Run:

```bash
py -3.12 -m uv tool run pre-commit run --show-diff-on-failure --color=always --from-ref origin/main --to-ref HEAD
git diff --check
```

Expected:

- `pre-commit` 通过
- `git diff --check` 无输出

**Step 6: Commit**

```bash
git add morningglory/fqwebui/src/views/RuntimeObservability.vue morningglory/fqwebui/src/views/runtime-observability.test.mjs
git commit -m "feat: 完成运行观测首页无输入重构"
```

### Task 6: 手工验收与 PR 前检查

**Files:**
- Review: `morningglory/fqwebui/src/views/RuntimeObservability.vue`
- Review: `morningglory/fqwebui/src/views/runtimeObservability.mjs`
- Review: `docs/plans/2026-03-09-runtime-observability-home-redesign-design.md`

**Step 1: 启动本地前端或并行 Docker 环境**

如只验证前端构建产物，可直接依赖现有 `npm run build`。
如做完整页面验收，可使用：

```bash
docker compose -f docker/compose.parallel.yaml up -d --build fq_webui fq_apiserver
```

**Step 2: 手工验收页面**

检查以下路径：

- 打开 `/runtime-observability`
- 默认先看到：
  - 异常优先
  - 最近链路流
  - 组件看板
- 默认不看到 5 个输入框
- 点“高级筛选”才能展开查询表单
- 点异常卡片、最近链路流、组件卡都能联动详情

**Step 3: 准备 PR 描述**

记录验证命令与结果：

```text
node --test src/views/runtime-observability.test.mjs
npm run build
py -3.12 -m uv tool run pre-commit run --show-diff-on-failure --color=always --from-ref origin/main --to-ref HEAD
```

**Step 4: Commit（如手工验收未新增代码则跳过）**

如只产生说明更新，不新增提交；如手工验收发现小修复，单独提交：

```bash
git add <changed-files>
git commit -m "fix: 收口运行观测首页交互细节"
```
