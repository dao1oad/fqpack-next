# Frontend Dense Workbench Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让导航以新浏览器标签页打开并显示正确标题，同时把 stock-control、gantt/shouban30、runtime-observability、system-settings 收口为桌面一屏工作台和局部滚动布局。

**Architecture:** 先抽离导航标题真值与页面标题同步，再增强公共 workbench 布局壳子，最后逐页做结构与样式调整。尽量把可测试逻辑提取为纯函数，把模板改造控制在明确的局部区域内。

**Tech Stack:** Vue 3、vue-router、Element Plus、Vite、Node test、Stylus/CSS

---

### Task 1: 导航元数据与页面标题

**Files:**
- Create: `morningglory/fqwebui/src/router/pageMeta.mjs`
- Modify: `morningglory/fqwebui/src/router/index.js`
- Modify: `morningglory/fqwebui/src/views/MyHeader.vue`
- Test: `morningglory/fqwebui/src/router/pageMeta.test.mjs`

**Step 1: Write the failing test**

```javascript
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  getHeaderNavTarget,
  resolveDocumentTitle,
} from './pageMeta.mjs'

test('header nav target returns label, route and query title', () => {
  assert.deepEqual(getHeaderNavTarget('runtime'), {
    label: '运行观测',
    path: '/runtime-observability',
    query: { tabTitle: '运行观测' },
  })
})

test('resolveDocumentTitle prefers query title then route meta title', () => {
  assert.equal(resolveDocumentTitle({
    query: { tabTitle: '首板选股' },
    meta: { title: '板块趋势' },
  }), '首板选股')
})
```

**Step 2: Run test to verify it fails**

Run: `node --test src/router/pageMeta.test.mjs`
Expected: FAIL with module not found or missing export.

**Step 3: Write minimal implementation**

实现 `pageMeta.mjs`，集中维护导航按钮、路由路径和标题；在 `router/index.js` 增加标题同步；在 `MyHeader.vue` 改为 `window.open(resolvedUrl, '_blank', 'noopener')`。

**Step 4: Run test to verify it passes**

Run: `node --test src/router/pageMeta.test.mjs`
Expected: PASS

**Step 5: Commit**

```bash
git add docs/plans/2026-03-16-frontend-dense-workbench-design.md docs/plans/2026-03-16-frontend-dense-workbench.md morningglory/fqwebui/src/router/pageMeta.mjs morningglory/fqwebui/src/router/pageMeta.test.mjs morningglory/fqwebui/src/router/index.js morningglory/fqwebui/src/views/MyHeader.vue
git commit -m "feat: add frontend page title navigation metadata"
```

### Task 2: Stock Control 双监控布局

**Files:**
- Modify: `morningglory/fqwebui/src/views/StockControl.vue`
- Modify: `morningglory/fqwebui/src/style/stock-control.styl`
- Test: `morningglory/fqwebui/tests/stock-control-signal-lists.test.mjs`

**Step 1: Write the failing test**

在 `tests/stock-control-signal-lists.test.mjs` 增加断言：

```javascript
assert.doesNotMatch(content, /<StockPositionList/)
assert.match(content, /stock-control-shell/)
assert.match(content, /monitor-column monitor-column--signals/)
assert.match(content, /monitor-column monitor-column--model/)
```

**Step 2: Run test to verify it fails**

Run: `node --test tests/stock-control-signal-lists.test.mjs`
Expected: FAIL because current template still includes `StockPositionList`.

**Step 3: Write minimal implementation**

删除 `StockPositionList` 引用；把页面改成左右两列布局并为列内列表提供滚动容器。

**Step 4: Run test to verify it passes**

Run: `node --test tests/stock-control-signal-lists.test.mjs`
Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/StockControl.vue morningglory/fqwebui/src/style/stock-control.styl morningglory/fqwebui/tests/stock-control-signal-lists.test.mjs
git commit -m "feat: rebalance stock control monitoring layout"
```

### Task 3: Gantt / Shouban30 固定工作区与文案修正

**Files:**
- Modify: `morningglory/fqwebui/src/views/GanttShouban30Phase1.vue`
- Modify: `morningglory/fqwebui/src/views/shouban30PoolWorkspace.mjs` (only if layout helper data needs extension)
- Test: `morningglory/fqwebui/src/views/shouban30PoolWorkspace.test.mjs`

**Step 1: Write the failing test**

在 `src/views/shouban30PoolWorkspace.test.mjs` 增加结构/文案断言：

```javascript
import { readFile } from 'node:fs/promises'

test('shouban30 page keeps workspace region in fixed layout and uses 韭研公社 label', async () => {
  const content = await readFile(new URL('./GanttShouban30Phase1.vue', import.meta.url), 'utf8')
  assert.match(content, /panel-card-workspace/)
  assert.match(content, /shouban30-grid/)
  assert.match(content, /韭研公社/)
  assert.doesNotMatch(content, /韭研公式/)
})
```

**Step 2: Run test to verify it fails**

Run: `node --test src/views/shouban30PoolWorkspace.test.mjs`
Expected: FAIL because current source still lacks the corrected label or fixed layout markers.

**Step 3: Write minimal implementation**

把页面改成上三下一区固定 grid，确保 `panel-table`、workspace tabs、详情区全部 `min-height: 0` 且内部滚动；修正文案为“韭研公社”。

**Step 4: Run test to verify it passes**

Run: `node --test src/views/shouban30PoolWorkspace.test.mjs`
Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/GanttShouban30Phase1.vue morningglory/fqwebui/src/views/shouban30PoolWorkspace.test.mjs
git commit -m "feat: fix shouban30 workspace viewport layout"
```

### Task 4: Runtime Observability 高密全局 Trace 列表

**Files:**
- Modify: `morningglory/fqwebui/src/views/RuntimeObservability.vue`
- Modify: `morningglory/fqwebui/src/views/runtimeObservability.mjs` (if list row data extraction is needed)
- Test: `morningglory/fqwebui/src/views/runtime-observability.test.mjs`

**Step 1: Write the failing test**

在 `src/views/runtime-observability.test.mjs` 追加一条结构测试：

```javascript
import { readFile } from 'node:fs/promises'

test('runtime observability global trace uses dense list container instead of stacked cards', async () => {
  const content = await readFile(new URL('./RuntimeObservability.vue', import.meta.url), 'utf8')
  assert.match(content, /trace-feed-list/)
  assert.match(content, /trace-feed-row/)
  assert.doesNotMatch(content, /recent-feed-item--stacked/)
})
```

**Step 2: Run test to verify it fails**

Run: `node --test src/views/runtime-observability.test.mjs`
Expected: FAIL because template still uses stacked card rows.

**Step 3: Write minimal implementation**

把 traces 中间栏模板改为高密列表；补充需要的辅助展示字段，但不删现有信息；中间栏增加独立滚动容器。

**Step 4: Run test to verify it passes**

Run: `node --test src/views/runtime-observability.test.mjs`
Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/RuntimeObservability.vue morningglory/fqwebui/src/views/runtimeObservability.mjs morningglory/fqwebui/src/views/runtime-observability.test.mjs
git commit -m "feat: densify runtime trace list layout"
```

### Task 5: System Settings 列表化摘要与一屏工作台

**Files:**
- Modify: `morningglory/fqwebui/src/views/SystemSettings.vue`
- Create: `morningglory/fqwebui/src/views/system-settings.test.mjs`

**Step 1: Write the failing test**

```javascript
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

test('system settings uses list-based summary sections instead of panel cards', async () => {
  const content = await readFile(new URL('./SystemSettings.vue', import.meta.url), 'utf8')
  assert.match(content, /settings-summary-list/)
  assert.match(content, /settings-strategy-list/)
  assert.doesNotMatch(content, /class=\"panel-card\"/)
})
```

**Step 2: Run test to verify it fails**

Run: `node --test src/views/system-settings.test.mjs`
Expected: FAIL because current template is still card-based.

**Step 3: Write minimal implementation**

保留编辑表单，替换摘要/字典区为列表型结构；页面主体做固定高度和局部滚动。

**Step 4: Run test to verify it passes**

Run: `node --test src/views/system-settings.test.mjs`
Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/SystemSettings.vue morningglory/fqwebui/src/views/system-settings.test.mjs
git commit -m "feat: switch system settings summaries to dense lists"
```

### Task 6: 公共布局回归与最终验证

**Files:**
- Modify: `morningglory/fqwebui/src/style/workbench-density.css`
- Modify: `morningglory/fqwebui/src/App.vue` (only if root shell wrapper is needed)
- Verify: `morningglory/fqwebui/src/views/OrderManagement.vue`
- Verify: `morningglory/fqwebui/src/views/PositionManagement.vue`
- Verify: `morningglory/fqwebui/src/views/TpslManagement.vue`

**Step 1: Write the failing test**

新增公共布局结构测试：

```javascript
import { readFile } from 'node:fs/promises'

test('workbench shell uses viewport-locked layout', async () => {
  const content = await readFile(new URL('../style/workbench-density.css', import.meta.url), 'utf8')
  assert.match(content, /height:\s*100dvh/)
  assert.match(content, /overflow:\s*hidden/)
})
```

**Step 2: Run test to verify it fails**

Run: `node --test src/views/system-settings.test.mjs src/router/pageMeta.test.mjs src/views/runtime-observability.test.mjs src/views/shouban30PoolWorkspace.test.mjs tests/stock-control-signal-lists.test.mjs`
Expected: At least one new assertion fails before layout changes are complete.

**Step 3: Write minimal implementation**

增强 `workbench-density.css` 与必要页面样式，确保主要 workbench 页面不依赖屏幕滚动。

**Step 4: Run test to verify it passes**

Run:

```bash
node --test src/router/pageMeta.test.mjs src/views/runtime-observability.test.mjs src/views/shouban30PoolWorkspace.test.mjs src/views/system-settings.test.mjs tests/stock-control-signal-lists.test.mjs
pnpm build
```

Expected: PASS；build 成功。

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/style/workbench-density.css morningglory/fqwebui/src/App.vue morningglory/fqwebui/src/router/pageMeta.mjs morningglory/fqwebui/src/router/pageMeta.test.mjs morningglory/fqwebui/src/views/MyHeader.vue morningglory/fqwebui/src/views/StockControl.vue morningglory/fqwebui/src/style/stock-control.styl morningglory/fqwebui/tests/stock-control-signal-lists.test.mjs morningglory/fqwebui/src/views/GanttShouban30Phase1.vue morningglory/fqwebui/src/views/shouban30PoolWorkspace.test.mjs morningglory/fqwebui/src/views/RuntimeObservability.vue morningglory/fqwebui/src/views/runtimeObservability.mjs morningglory/fqwebui/src/views/runtime-observability.test.mjs morningglory/fqwebui/src/views/SystemSettings.vue morningglory/fqwebui/src/views/system-settings.test.mjs
git commit -m "feat: densify frontend workbench layouts"
```
