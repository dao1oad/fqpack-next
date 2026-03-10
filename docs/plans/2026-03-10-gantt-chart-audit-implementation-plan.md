# Gantt Chart Audit Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
>
> **Phase 2 override for this task:** 实际执行必须使用 `superpowers:subagent-driven-development`；每个实现子 agent 在任何代码修改前，必须先使用 `superpowers:test-driven-development`。

**Goal:** 让 `GanttHistory.vue` 在不恢复搜索抽屉和“加入近期涨停池”的前提下，对齐 legacy 图表的颜色语义、legend、tooltip、zoom/pan、hover 与 reset 行为。

**Architecture:** 先把可测试的颜色映射、streak 计算和 reset 视口计算抽到一个纯 `.mjs` helper，再让 `GanttHistory.vue` 只负责模板、ECharts 绑定和 DOM 级交互。组件保留当前 API/props 形状，但恢复 legacy 的交互配置，并继续承载当前 `reason_text` tooltip 增强。

**Tech Stack:** Vue 3 `<script setup>`、ECharts 6、Node `node:test` (`.mjs`) 文件级/纯函数测试。

---

### Task 1: 提取并锁定纯图表规则

**Files:**
- Create: `morningglory/fqwebui/src/views/js/gantt-history-chart.mjs`
- Create: `morningglory/fqwebui/tests/gantt-history-chart.test.mjs`
- Modify: `morningglory/fqwebui/src/views/components/GanttHistory.vue`

**Step 1: Write the failing test**

```js
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  getStreakColor,
  processSeriesWithStreaks,
  getResetViewportWindow
} from '../src/views/js/gantt-history-chart.mjs'

test('getStreakColor returns legacy palette entries', () => {
  assert.equal(getStreakColor(1, 1), '#ffd666')
  assert.equal(getStreakColor(4, 4), '#52c41a')
})

test('processSeriesWithStreaks appends color and streak metadata', () => {
  const result = processSeriesWithStreaks({
    dates: ['2026-03-05', '2026-03-06'],
    yAxisRaw: [{ id: 1, name: '机器人' }],
    seriesData: [
      [0, 0, 1, 5, 2, ['000001']],
      [1, 0, 1, 4, 1, ['000001']]
    ],
    level: 'plate'
  })

  assert.equal(result.seriesData[0][6], '#ffd666')
  assert.equal(result.seriesData[0][7], 1)
  assert.equal(result.seriesData[1][8], 2)
})

test('getResetViewportWindow keeps latest x-span and top y-span', () => {
  assert.deepEqual(
    getResetViewportWindow({ start: 30, end: 90 }, { start: 20, end: 60 }),
    { xStart: 40, xEnd: 100, yStart: 0, yEnd: 40 }
  )
})
```

**Step 2: Run test to verify it fails**

Run: `node --test morningglory/fqwebui/tests/gantt-history-chart.test.mjs`
Expected: FAIL with `ERR_MODULE_NOT_FOUND` or missing export errors for `gantt-history-chart.mjs`.

**Step 3: Write minimal implementation**

```js
export const streakPalettes = {
  1: ['#ffd666', '#ffc53d', '#faad14', '#d48806', '#ad6800', '#874d00'],
  2: ['#91caff', '#69b1ff', '#409eff', '#1677ff', '#0958d9', '#003eb3'],
  3: ['#ffa39e', '#ff7875', '#ff4d4f', '#d9363e', '#b3242b', '#8c161c'],
  4: ['#b7eb8f', '#95de64', '#73d13d', '#52c41a', '#389e0d', '#237804']
}

export const getStreakColor = (order, day) => {
  const palette = streakPalettes[Math.min(order || 1, 4)] || []
  return palette[Math.min(Math.max((day || 1) - 1, 0), palette.length - 1)] || '#d9d9d9'
}

export const processSeriesWithStreaks = ({ dates, yAxisRaw, seriesData, level }) => {
  // 基于 legacy 规则追加 color / streakOrder / streakDay，保留原始 point 结构
}

export const getResetViewportWindow = (xZoom = {}, yZoom = {}) => {
  // 返回 { xStart, xEnd, yStart, yEnd }，语义与 legacy handleResetView 一致
}
```

**Step 4: Run test to verify it passes**

Run: `node --test morningglory/fqwebui/tests/gantt-history-chart.test.mjs`
Expected: PASS for palette, streak metadata, and reset window math.

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/js/gantt-history-chart.mjs morningglory/fqwebui/tests/gantt-history-chart.test.mjs morningglory/fqwebui/src/views/components/GanttHistory.vue
git commit -m "feat: extract gantt chart audit helpers"
```

### Task 2: 对齐 legend、tooltip、hover 与 ECharts 配置

**Files:**
- Modify: `morningglory/fqwebui/src/views/components/GanttHistory.vue`
- Modify: `morningglory/fqwebui/tests/gantt-history-chart.test.mjs`

**Step 1: Write the failing test**

```js
import { readFile } from 'node:fs/promises'

test('GanttHistory restores legend and legacy hover config', async () => {
  const content = await readFile(new URL('../src/views/components/GanttHistory.vue', import.meta.url), 'utf8')

  assert.match(content, /class="color-legend"/)
  assert.match(content, /axisPointer:/)
  assert.match(content, /updateAxisPointer/)
  assert.match(content, /position: \(point, params, dom, rect, size\) =>/)
})
```

**Step 2: Run test to verify it fails**

Run: `node --test morningglory/fqwebui/tests/gantt-history-chart.test.mjs`
Expected: FAIL because `GanttHistory.vue` 还没有 legend、axisPointer 和 tooltip 限位实现。

**Step 3: Write minimal implementation**

```vue
<div class="color-legend">
  <div v-for="legend in legendItems" :key="legend.key" class="legend-item">
    <span class="legend-dot" :style="{ background: legend.color }"></span>
    <span class="legend-label">{{ legend.label }}</span>
  </div>
</div>
```

```js
const option = {
  axisPointer: {
    link: [{ xAxisIndex: 'all' }],
    label: { show: false },
    snap: false
  },
  tooltip: {
    trigger: 'item',
    confine: true,
    position: (point, params, dom, rect, size) => {
      const x = Math.min(point[0], size.viewSize[0] - size.contentSize[0] - 10)
      const y = Math.min(point[1] + 12, size.viewSize[1] - size.contentSize[1] - 10)
      return [Math.max(10, x), Math.max(10, y)]
    }
  }
}
```

**Step 4: Run test to verify it passes**

Run: `node --test morningglory/fqwebui/tests/gantt-history-chart.test.mjs`
Expected: PASS and `GanttHistory.vue` 明确包含 legend、hover 配置和 tooltip 限位逻辑。

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/components/GanttHistory.vue morningglory/fqwebui/tests/gantt-history-chart.test.mjs
git commit -m "feat: align gantt legend and hover behavior"
```

### Task 3: 恢复 stock drag-pan 与 plate 侧栏 viewport 同步

**Files:**
- Modify: `morningglory/fqwebui/src/views/components/GanttHistory.vue`
- Modify: `morningglory/fqwebui/tests/gantt-history-chart.test.mjs`

**Step 1: Write the failing test**

```js
test('GanttHistory keeps stock drag-pan fallback and viewport-synced sidebar', async () => {
  const content = await readFile(new URL('../src/views/components/GanttHistory.vue', import.meta.url), 'utf8')

  assert.match(content, /const syncPlateSidebarFromChart = \(\) =>/)
  assert.match(content, /chartInstance\.on\('dataZoom'/)
  assert.match(content, /const handleStockPanMouseDown = \(evt\) =>/)
})
```

**Step 2: Run test to verify it fails**

Run: `node --test morningglory/fqwebui/tests/gantt-history-chart.test.mjs`
Expected: FAIL because 当前组件没有 stock drag-pan fallback，也没有基于 viewport 的侧栏同步。

**Step 3: Write minimal implementation**

```js
const syncPlateSidebarFromChart = () => {
  // 读取 yAxis dataZoom 百分比，只渲染当前可视 slice
}

const handleStockPanMouseDown = (evt) => {
  // 仅在 stock 视图且 pointer 落在 grid 外时启动 DOM 级平移兜底
}

chartInstance.on('dataZoom', () => {
  syncPlateSidebarFromChart()
})
```

**Step 4: Run test to verify it passes**

Run: `node --test morningglory/fqwebui/tests/gantt-history-chart.test.mjs`
Expected: PASS and `restoreViewport()` / `dataZoom` / `globalout` 都会驱动侧栏与 hover 状态同步。

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/components/GanttHistory.vue morningglory/fqwebui/tests/gantt-history-chart.test.mjs
git commit -m "feat: restore gantt pan and sidebar sync"
```

### Final Verification

**Files:**
- Modify: `morningglory/fqwebui/src/views/components/GanttHistory.vue`
- Create/Modify: `morningglory/fqwebui/src/views/js/gantt-history-chart.mjs`
- Create/Modify: `morningglory/fqwebui/tests/gantt-history-chart.test.mjs`

**Step 1: Run focused tests**

Run: `node --test morningglory/fqwebui/tests/gantt-history-chart.test.mjs`
Expected: PASS

**Step 2: Run build verification**

Run: `npm --prefix morningglory/fqwebui run build`
Expected: PASS with Vite production build output and no new ECharts/Vue compile errors.

**Step 3: Prepare review handoff**

Run: `git status --short`
Expected: 仅包含本任务相关文件变更，便于进入 Human Review / PR review。
