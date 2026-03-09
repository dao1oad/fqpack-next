# KlineSlim 多周期缠论图层显示 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在当前 `KlineSlim` 页面布局不变的前提下，恢复旧仓 `1m / 5m / 15m / 30m` 多周期缠论图层、旧仓配色与线宽规则，以及按 legend 驱动的懒加载和可见性联动。

**Architecture:** 保持现有 `KlineSlim.vue`、`/api/stock_data` 和右侧缠论结构面板不变，不新增后端接口。把四周期常量、样式映射和 legend 可见性规则抽到一个轻量 `.mjs` 辅助模块，`kline-slim.js` 负责按可见周期懒加载与轮询，`draw-slim.js` 负责把每周期的 `笔 / 段 / 高级别段 / 中枢 / 段中枢 / 高级段中枢` 图层 remap 到当前主图时间轴并生成 legend 分组。

**Tech Stack:** Vue 3、ECharts、Node test runner、现有 `/api/stock_data` fullcalc payload、Python 3.12 pytest 回归测试

---

### Task 1: 锁定四周期配置、旧仓样式映射与 legend 纯函数

**Files:**
- Create: `morningglory/fqwebui/src/views/js/kline-slim-chanlun-periods.mjs`
- Create: `morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs`
- Reference: `docs/plans/2026-03-09-kline-slim-multi-period-chanlun-display-design.md`

**Step 1: 先写失败测试，锁定周期、默认可见性、样式和实时刷新集合语义**

```javascript
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  SUPPORTED_CHANLUN_PERIODS,
  DEFAULT_MAIN_PERIOD,
  DEFAULT_VISIBLE_CHANLUN_PERIODS,
  PERIOD_STYLE_MAP,
  PERIOD_WIDTH_FACTOR,
  buildLegendSelectionState,
  getRealtimeRefreshPeriods
} from '../src/views/js/kline-slim-chanlun-periods.mjs'

test('supported periods stay within redis producer periods and default to 5m', () => {
  assert.deepEqual(SUPPORTED_CHANLUN_PERIODS, ['1m', '5m', '15m', '30m'])
  assert.equal(DEFAULT_MAIN_PERIOD, '5m')
  assert.deepEqual(DEFAULT_VISIBLE_CHANLUN_PERIODS, ['5m'])
})

test('period style map matches legacy color families and width factors', () => {
  assert.equal(PERIOD_STYLE_MAP['1m'].bi, '#ffffff')
  assert.equal(PERIOD_STYLE_MAP['5m'].duan, '#3b82f6')
  assert.equal(PERIOD_STYLE_MAP['15m'].higherDuan, '#ef4444')
  assert.equal(PERIOD_STYLE_MAP['30m'].duanZhongshu, '#ef4444')
  assert.deepEqual(PERIOD_WIDTH_FACTOR, { '1m': 1, '5m': 3, '15m': 4, '30m': 5 })
})

test('legend selection defaults to only 5m plus enabled zhongshu groups', () => {
  assert.deepEqual(
    buildLegendSelectionState(),
    {
      '1m': false,
      '5m': true,
      '15m': false,
      '30m': false,
      '中枢': true,
      '段中枢': true
    }
  )
})

test('realtime refresh periods keep current period first and visible extras unique', () => {
  assert.deepEqual(
    getRealtimeRefreshPeriods({
      currentPeriod: '5m',
      visiblePeriods: ['30m', '1m', '5m', '30m']
    }),
    ['5m', '1m', '30m']
  )
})
```

**Step 2: 运行测试，确认失败**

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Workdir: `D:\fqpack\freshquant-2026.2.23\.worktrees\brainstorm-kline-slim-display\morningglory\fqwebui`

Expected:
- FAIL，提示 `kline-slim-chanlun-periods.mjs` 或导出函数不存在

**Step 3: 写最小实现**

```javascript
export const SUPPORTED_CHANLUN_PERIODS = ['1m', '5m', '15m', '30m']
export const DEFAULT_MAIN_PERIOD = '5m'
export const DEFAULT_VISIBLE_CHANLUN_PERIODS = ['5m']

export const PERIOD_STYLE_MAP = {
  '1m': {
    bi: '#ffffff',
    duan: '#facc15',
    higherDuan: '#3b82f6',
    zhongshu: 'rgba(255, 255, 255, 0.14)',
    duanZhongshu: 'rgba(250, 204, 21, 0.16)',
    higherDuanZhongshu: 'rgba(59, 130, 246, 0.18)'
  },
  ...
}

export const PERIOD_WIDTH_FACTOR = {
  '1m': 1,
  '5m': 3,
  '15m': 4,
  '30m': 5
}

export function buildLegendSelectionState(previousSelected = null) {
  ...
}

export function getRealtimeRefreshPeriods({ currentPeriod, visiblePeriods = [] } = {}) {
  ...
}
```

- 只提供纯函数，不依赖 Vue 实例或 ECharts。
- `buildLegendSelectionState()` 默认只选中 `5m`，全局 `中枢` 与 `段中枢` 默认开启。
- `getRealtimeRefreshPeriods()` 必须去重，并把当前主周期放在返回值第一位。

**Step 4: 回跑测试，确认通过**

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Workdir: `D:\fqpack\freshquant-2026.2.23\.worktrees\brainstorm-kline-slim-display\morningglory\fqwebui`

Expected:
- PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/js/kline-slim-chanlun-periods.mjs morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs
git commit -m "test: lock kline slim chanlun period rules"
```

### Task 2: 锁定 `kline-slim.js` 的多周期缓存、懒加载入口与固定 overlay 清理

**Files:**
- Modify: `morningglory/fqwebui/src/views/js/kline-slim.js`
- Modify: `morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs`

**Step 1: 先写失败测试，固定状态字段和方法名**

```javascript
import { readFile } from 'node:fs/promises'

test('kline-slim controller uses multi-period chanlun state instead of fixed overlay', async () => {
  const content = await readFile(new URL('../src/views/js/kline-slim.js', import.meta.url), 'utf8')

  assert.match(content, /chanlunMultiData/)
  assert.match(content, /visibleChanlunPeriods/)
  assert.match(content, /loadedChanlunPeriods/)
  assert.match(content, /chanlunPeriodLoading/)
  assert.match(content, /ensureChanlunPeriodLoaded/)
  assert.match(content, /handleSlimLegendSelectChanged/)
  assert.match(content, /refreshVisibleChanlunPeriods/)
  assert.doesNotMatch(content, /overlayData/)
  assert.doesNotMatch(content, /overlayTimer/)
  assert.doesNotMatch(content, /OVERLAY_PERIOD/)
})
```

**Step 2: 运行测试，确认失败**

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Workdir: `D:\fqpack\freshquant-2026.2.23\.worktrees\brainstorm-kline-slim-display\morningglory\fqwebui`

Expected:
- FAIL，提示当前脚本仍包含 `overlayData / overlayTimer / OVERLAY_PERIOD`

**Step 3: 写最小实现**

```javascript
data() {
  return {
    ...,
    currentPeriod: DEFAULT_MAIN_PERIOD,
    chanlunMultiData: {},
    visibleChanlunPeriods: [...DEFAULT_VISIBLE_CHANLUN_PERIODS],
    loadedChanlunPeriods: [],
    chanlunPeriodLoading: {},
    chanlunLegendSelected: buildLegendSelectionState(),
    chanlunRefreshTimer: null
  }
},
methods: {
  async ensureChanlunPeriodLoaded(period) {
    ...
  },
  handleSlimLegendSelectChanged(event) {
    ...
  },
  async refreshVisibleChanlunPeriods() {
    ...
  }
}
```

- 删除固定 `overlayPeriod / overlayData / overlayTimer / overlayVersion / overlayLoading` 状态。
- `ensureChanlunPeriodLoaded(period)` 只负责单周期取数与缓存，不直接管渲染。
- `handleSlimLegendSelectChanged(event)` 只解析 legend 选中状态和触发必要的懒加载。
- `refreshVisibleChanlunPeriods()` 只刷新 `getRealtimeRefreshPeriods()` 返回的周期集合。

**Step 4: 回跑测试，确认通过**

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Workdir: `D:\fqpack\freshquant-2026.2.23\.worktrees\brainstorm-kline-slim-display\morningglory\fqwebui`

Expected:
- PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/js/kline-slim.js morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs
git commit -m "refactor: replace fixed overlay with multi-period chanlun state"
```

### Task 3: 锁定 `draw-slim.js` 的多周期缠论层、旧仓配色和全局中枢 legend

**Files:**
- Modify: `morningglory/fqwebui/src/views/js/draw-slim.js`
- Modify: `morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs`
- Reference: `D:\fqpack\freshquant\morningglory\fqwebui\src\views\js\draw-slim.js`

**Step 1: 先写失败测试，锁定 renderer 必须接入的层与 legend**

```javascript
test('draw-slim consumes all multi-period chanlun layer fields and global zhongshu legends', async () => {
  const content = await readFile(new URL('../src/views/js/draw-slim.js', import.meta.url), 'utf8')

  assert.match(content, /higherDuanData/)
  assert.match(content, /duan_zsdata/)
  assert.match(content, /higher_duan_zsdata/)
  assert.match(content, /PERIOD_STYLE_MAP/)
  assert.match(content, /PERIOD_WIDTH_FACTOR/)
  assert.match(content, /'中枢'/)
  assert.match(content, /'段中枢'/)
  assert.match(content, /markArea/)
})
```

**Step 2: 运行测试，确认失败**

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Workdir: `D:\fqpack\freshquant-2026.2.23\.worktrees\brainstorm-kline-slim-display\morningglory\fqwebui`

Expected:
- FAIL，提示 `draw-slim.js` 仍只处理 `bidata / duandata / zsdata`

**Step 3: 写最小实现**

```javascript
function normalizeChanlunData(data) {
  return {
    biValues: buildLinePairs(data?.bidata),
    duanValues: buildLinePairs(data?.duandata),
    higherDuanValues: buildLinePairs(data?.higherDuanData),
    zhongshuValues: Array.isArray(data?.zsdata) ? data.zsdata : [],
    zhongshuFlags: Array.isArray(data?.zsflag) ? data.zsflag : [],
    duanZhongshuValues: Array.isArray(data?.duan_zsdata) ? data.duan_zsdata : [],
    duanZhongshuFlags: Array.isArray(data?.duan_zsflag) ? data.duan_zsflag : [],
    higherDuanZhongshuValues: Array.isArray(data?.higher_duan_zsdata) ? data.higher_duan_zsdata : [],
    higherDuanZhongshuFlags: Array.isArray(data?.higher_duan_zsflag) ? data.higher_duan_zsflag : []
  }
}
```

```javascript
const legendNames = ['1m', '5m', '15m', '30m', '中枢', '段中枢']
const style = PERIOD_STYLE_MAP[period]
const factor = PERIOD_WIDTH_FACTOR[period]
```

- 让 `drawSlim()` 读取 `extraChanlunMap` 中每个周期的完整 payload，而不是固定 `overlayPeriod`。
- 每周期生成 6 类图层：`笔 / 段 / 高级别段 / 中枢 / 段中枢 / 高级段中枢`。
- `higher_duan_zsdata` 为空时按空数组处理，不报错、不补请求。
- 保留 `resolveSelectedState()`，确保刷新数据后 legend 选中状态不丢失。
- 中枢类图层继续使用 `markArea`，并保留“同一根 bar 直接丢弃”的过滤规则。

**Step 4: 回跑测试，确认通过**

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Workdir: `D:\fqpack\freshquant-2026.2.23\.worktrees\brainstorm-kline-slim-display\morningglory\fqwebui`

Expected:
- PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/js/draw-slim.js morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs
git commit -m "feat: restore multi-period chanlun layers in draw slim"
```

### Task 4: 接上 legend 可见性联动、单周期懒加载和页面状态文案

**Files:**
- Modify: `morningglory/fqwebui/src/views/js/kline-slim.js`
- Modify: `morningglory/fqwebui/src/views/KlineSlim.vue`
- Modify: `morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs`

**Step 1: 先写失败测试，锁定模板文案和图例驱动行为入口**

```javascript
test('KlineSlim removes fixed overlay status copy and hints legend-driven extra periods', async () => {
  const content = await readFile(new URL('../src/views/KlineSlim.vue', import.meta.url), 'utf8')

  assert.doesNotMatch(content, /叠加/)
  assert.match(content, /图例控制额外周期缠论层/)
})

test('kline-slim controller binds legend selection changes to lazy period loading', async () => {
  const content = await readFile(new URL('../src/views/js/kline-slim.js', import.meta.url), 'utf8')

  assert.match(content, /legendselectchanged/)
  assert.match(content, /ensureChanlunPeriodLoaded/)
  assert.match(content, /visibleChanlunPeriods =/)
})
```

**Step 2: 运行测试，确认失败**

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Workdir: `D:\fqpack\freshquant-2026.2.23\.worktrees\brainstorm-kline-slim-display\morningglory\fqwebui`

Expected:
- FAIL，提示页面仍保留固定 overlay 文案，且未绑定 legend 懒加载

**Step 3: 写最小实现**

```javascript
this.chart.on('legendselectchanged', this.handleSlimLegendSelectChanged)
```

```javascript
async handleSlimLegendSelectChanged(event) {
  const nextVisiblePeriods = ...
  this.visibleChanlunPeriods = nextVisiblePeriods
  await Promise.all(nextVisiblePeriods.map(period => this.ensureChanlunPeriodLoaded(period)))
  this.scheduleRender()
}
```

```vue
<span class="status-chip">主图 {{ currentPeriod }}</span>
<span class="status-chip">图例控制额外周期缠论层</span>
```

- 页面顶部只保留主图周期状态，不再展示固定“叠加 30m”。
- 切换标的后，重置 `visibleChanlunPeriods` 和 `chanlunLegendSelected` 为默认仅 `5m`。
- 只在用户首次打开某周期 legend 时请求该周期数据；再次开关只走缓存。
- 历史模式下允许加载用户打开的附加周期，但不启动实时轮询。

**Step 4: 回跑测试，确认通过**

Run: `node --test tests/kline-slim-multi-period-chanlun.test.mjs`

Workdir: `D:\fqpack\freshquant-2026.2.23\.worktrees\brainstorm-kline-slim-display\morningglory\fqwebui`

Expected:
- PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/js/kline-slim.js morningglory/fqwebui/src/views/KlineSlim.vue morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs
git commit -m "feat: lazy load chanlun periods from legend visibility"
```

### Task 5: 做前端聚合验证与现有后端接口回归

**Files:**
- No file changes

**Step 1: 跑前端相关 Node 测试**

Run: `node --test tests/kline-slim-default-symbol.test.mjs tests/kline-slim-sidebar.test.mjs tests/kline-slim-chanlun-structure.test.mjs tests/kline-slim-multi-period-chanlun.test.mjs`

Workdir: `D:\fqpack\freshquant-2026.2.23\.worktrees\brainstorm-kline-slim-display\morningglory\fqwebui`

Expected:
- PASS

**Step 2: 跑前端构建**

Run: `npm run build`

Workdir: `D:\fqpack\freshquant-2026.2.23\.worktrees\brainstorm-kline-slim-display\morningglory\fqwebui`

Expected:
- PASS

**Step 3: 跑现有后端回归测试，确保没有误伤行情与结构接口**

Run: `py -3.12 -m pytest freshquant/tests/test_stock_data_route_cache.py freshquant/tests/test_stock_data_chanlun_structure_route.py -q`

Workdir: `D:\fqpack\freshquant-2026.2.23\.worktrees\brainstorm-kline-slim-display`

Expected:
- PASS

**Step 4: 手动烟测清单**

```text
1. 打开 /kline-slim?symbol=sh510050，首屏只看到 5m K 线与 5m 缠论层
2. 图例里默认只选中 5m，1m / 15m / 30m 初始不请求
3. 依次点开 1m、15m、30m，浏览器只在首次点开时各发一次请求
4. 点关某周期后，该周期线条与中枢消失；重新点开直接走缓存
5. 全局“中枢”开关只影响普通中枢；全局“段中枢”开关影响段中枢和高级段中枢
6. 中枢不再出现竖线伪影或明显越界
7. 实时模式下隐藏周期不再持续刷新
8. 切换 symbol 后恢复默认仅 5m 可见
```

**Step 5: 合并前检查**

Run:
- `git status --short`
- `git log --oneline -5`

Workdir: `D:\fqpack\freshquant-2026.2.23\.worktrees\brainstorm-kline-slim-display`

Expected:
- 工作区干净
- 最近提交包含 helper、state、renderer、legend/lazy-load 四类提交

### Task 6: RFC 边界复核

**Files:**
- Verify only: `docs/plans/2026-03-09-kline-slim-multi-period-chanlun-display-design.md`

**Step 1: 实现前复核是否仍在既定边界内**

```text
- 仅修改 KlineSlim 前端页面与图表 renderer
- 不新增后端接口
- 不修改 /api/stock_data 参数语义
- 不新增外部依赖
- 周期范围仍限制在 1m / 5m / 15m / 30m
```

**Step 2: 若实现中触发以下任一条件，先停下补 RFC**

```text
- 需要修改 /api/stock_data 契约
- 需要新增对外 API 或 worker
- 需要把周期范围扩展到四个之外
- 需要引入新的数据源或外部依赖
```
