# KlineSlim Guardian 价格层级与止盈网格 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 `KlineSlim` 页面复用现有标的真值，支持 Guardian 三层价格与止盈三层价格的查看/编辑，并在主图直接渲染 6 条价格横线和轻量价格网格。

**Architecture:** 前端复用 `/api/subject-management/<symbol>` 聚合详情和现有保存接口，不新增后端真值。`KlineSlim` 增加独立的价格详情状态与编辑面板，图表层在现有 scene/controller/renderer 架构里增加 `priceGuides`、price line series 和 price band custom series，并把这些价格纳入 Y 轴范围计算。

**Tech Stack:** Vue 3、Element Plus、ECharts 6、Node test runner、Vite、现有 Flask API

---

### Task 1: 抽出可复用的标的价格归一模块

**Files:**
- Create: `morningglory/fqwebui/src/views/js/subject-price-guides.mjs`
- Create: `morningglory/fqwebui/src/views/js/subject-price-guides.test.mjs`
- Modify: `morningglory/fqwebui/src/views/subjectManagement.mjs`
- Test: `morningglory/fqwebui/src/views/js/subject-price-guides.test.mjs`

**Step 1: Write the failing test**

在 `morningglory/fqwebui/src/views/js/subject-price-guides.test.mjs` 写测试，锁定共享归一逻辑：

```javascript
import test from 'node:test'
import assert from 'node:assert/strict'
import {
  buildKlineSubjectPriceDetail,
  buildGuardianPriceGuides,
  buildTakeprofitPriceGuides,
  validateGuardianGuideDraft,
  validateTakeprofitDrafts,
} from './subject-price-guides.mjs'

test('buildKlineSubjectPriceDetail keeps guardian, takeprofit and runtime state', () => {
  const detail = buildKlineSubjectPriceDetail({
    guardian_buy_grid_config: { enabled: true, buy_1: 10.2, buy_2: 9.9, buy_3: 9.5 },
    guardian_buy_grid_state: { buy_active: [true, false, true] },
    takeprofit: {
      tiers: [
        { level: 1, price: 10.8, enabled: true },
        { level: 3, price: 11.8, enabled: false },
      ],
      state: { armed_levels: { 1: true, 2: false, 3: true } },
    },
  })

  assert.equal(detail.guardianDraft.buy_1, 10.2)
  assert.equal(detail.takeprofitDrafts.length, 3)
  assert.equal(detail.takeprofitDrafts[1].price, null)
})
```

再补：

- Guardian 三条线按高到低蓝红绿
- Takeprofit 三条线按低到高蓝红绿
- Guardian 顺序校验失败时返回错误信息
- Takeprofit 价格为空时返回错误信息

**Step 2: Run test to verify it fails**

Run: `node --test morningglory/fqwebui/src/views/js/subject-price-guides.test.mjs`
Expected: FAIL，提示模块或导出函数不存在。

**Step 3: Write minimal implementation**

在 `morningglory/fqwebui/src/views/js/subject-price-guides.mjs` 实现最小纯函数：

- `normalizeGuardianConfig`
- `buildTakeprofitDrafts`
- `buildKlineSubjectPriceDetail`
- `buildGuardianPriceGuides`
- `buildTakeprofitPriceGuides`
- `validateGuardianGuideDraft`
- `validateTakeprofitDrafts`

只做纯数据归一和校验，不写页面逻辑。

**Step 4: Run test to verify it passes**

Run: `node --test morningglory/fqwebui/src/views/js/subject-price-guides.test.mjs`
Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/js/subject-price-guides.mjs morningglory/fqwebui/src/views/js/subject-price-guides.test.mjs morningglory/fqwebui/src/views/subjectManagement.mjs
git commit -m "test: extract shared subject price guide model"
```

### Task 2: 给 KlineSlim 增加标的价格详情读写状态

**Files:**
- Modify: `morningglory/fqwebui/src/views/js/kline-slim.js`
- Modify: `morningglory/fqwebui/src/api/subjectManagementApi.js`
- Create: `morningglory/fqwebui/src/views/js/kline-slim-price-panel.test.mjs`
- Test: `morningglory/fqwebui/src/views/js/kline-slim-price-panel.test.mjs`

**Step 1: Write the failing test**

在 `morningglory/fqwebui/src/views/js/kline-slim-price-panel.test.mjs` 锁定 KlineSlim 的价格详情行为：

```javascript
test('route symbol change loads subject detail once and builds price guide state', async () => {
  const calls = []
  const api = {
    async getDetail(symbol) {
      calls.push(symbol)
      return {
        subject: { symbol, name: '浦发银行' },
        guardian_buy_grid_config: { enabled: true, buy_1: 10.2, buy_2: 9.9, buy_3: 9.5 },
        guardian_buy_grid_state: { buy_active: [true, false, true] },
        takeprofit: { tiers: [{ level: 1, price: 10.8, manual_enabled: true }], state: { armed_levels: { 1: true } } },
      }
    },
  }

  // 断言 controller/vm 只在 symbol 切换时刷新 detail，
  // period 切换不重复拉取 detail。
})
```

再补：

- 保存 Guardian 后重新拉 detail
- 保存 Takeprofit 后重新拉 detail
- `renderVersion` 包含价格 guide 版本

**Step 2: Run test to verify it fails**

Run: `node --test morningglory/fqwebui/src/views/js/kline-slim-price-panel.test.mjs`
Expected: FAIL，说明 KlineSlim 还没有这套状态。

**Step 3: Write minimal implementation**

在 `morningglory/fqwebui/src/views/js/kline-slim.js` 增加最小状态：

- `subjectDetailLoading`
- `subjectDetailError`
- `subjectPriceDetail`
- `guardianDraft`
- `takeprofitDrafts`
- `showPriceGuidePanel`
- `priceGuideVersion`

增加方法：

- `loadSubjectPriceDetail(symbol)`
- `handleSaveGuardianPriceGuides()`
- `handleSaveTakeprofitGuides()`
- `buildScenePriceGuides()`

复用现有 API：

- `subjectManagementApi.getDetail`
- `subjectManagementApi.saveGuardianBuyGrid`
- `subjectManagementApi.saveTakeprofitProfile`

**Step 4: Run test to verify it passes**

Run: `node --test morningglory/fqwebui/src/views/js/kline-slim-price-panel.test.mjs`
Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/js/kline-slim.js morningglory/fqwebui/src/api/subjectManagementApi.js morningglory/fqwebui/src/views/js/kline-slim-price-panel.test.mjs
git commit -m "feat: load subject price guides in kline slim"
```

### Task 3: 先锁定图表 price guide scene 和 Y 轴逻辑

**Files:**
- Modify: `morningglory/fqwebui/src/views/js/kline-slim-chart-renderer.mjs`
- Modify: `morningglory/fqwebui/src/views/js/kline-slim-chart-controller.mjs`
- Create: `morningglory/fqwebui/src/views/js/kline-slim-chart-price-guides.test.mjs`
- Test: `morningglory/fqwebui/src/views/js/kline-slim-chart-price-guides.test.mjs`

**Step 1: Write the failing test**

在 `morningglory/fqwebui/src/views/js/kline-slim-chart-price-guides.test.mjs` 写两个核心测试：

```javascript
test('buildKlineSlimChartScene carries guardian and takeprofit price guides', () => {
  const scene = buildKlineSlimChartScene({
    mainData: makeMainData(),
    currentPeriod: '30m',
    visiblePeriods: ['30m'],
    priceGuides: {
      lines: [
        { id: 'g-b1', price: 10.2, group: 'guardian', color: '#3b82f6', label: 'G-B1 10.20' },
        { id: 'tp-l1', price: 10.8, group: 'takeprofit', color: '#3b82f6', label: 'TP-L1 10.80' },
      ],
      bands: [
        { id: 'g-band-1', top: 10.2, bottom: 9.9, color: '#3b82f6' },
      ],
    },
  })

  assert.equal(scene.priceGuideLines.length, 2)
  assert.equal(scene.priceGuideBands.length, 1)
})
```

第二个测试锁定：

- `deriveViewportStateForScene()` 计算 `yRange` 时，会把 price guide 的 `price/top/bottom` 一并纳入

**Step 2: Run test to verify it fails**

Run: `node --test morningglory/fqwebui/src/views/js/kline-slim-chart-price-guides.test.mjs`
Expected: FAIL，说明 scene/controller 还不认识 price guides。

**Step 3: Write minimal implementation**

在 renderer 最小增加：

- `buildPriceGuideLineSeries()`
- `buildPriceGuideBandSeries()`
- `scene.priceGuideLines`
- `scene.priceGuideBands`

在 controller 最小增加：

- `collectVisibleValues()` 收集 `scene.priceGuideLines[].price`
- `collectVisibleValues()` 收集 `scene.priceGuideBands[].top/bottom`

先不做标签，只先把横线和范围算对。

**Step 4: Run test to verify it passes**

Run: `node --test morningglory/fqwebui/src/views/js/kline-slim-chart-price-guides.test.mjs`
Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/js/kline-slim-chart-renderer.mjs morningglory/fqwebui/src/views/js/kline-slim-chart-controller.mjs morningglory/fqwebui/src/views/js/kline-slim-chart-price-guides.test.mjs
git commit -m "test: lock kline slim price guide scene and viewport"
```

### Task 4: 实现价格横线、价格带和标签渲染

**Files:**
- Modify: `morningglory/fqwebui/src/views/js/kline-slim-chart-renderer.mjs`
- Test: `morningglory/fqwebui/src/views/js/kline-slim-chart-price-guides.test.mjs`

**Step 1: Write the failing test**

在已有图表测试里追加断言：

- Guardian 线是实线
- Takeprofit 线是虚线
- band 是 `custom` series
- 右侧 label 文本包含 `G-B1` / `TP-L1`

示例：

```javascript
assert.equal(series.find((item) => item.id === 'g-b1').lineStyle.type, 'solid')
assert.equal(series.find((item) => item.id === 'tp-l1').lineStyle.type, 'dashed')
assert.equal(series.find((item) => item.id === 'g-band-1').type, 'custom')
```

**Step 2: Run test to verify it fails**

Run: `node --test morningglory/fqwebui/src/views/js/kline-slim-chart-price-guides.test.mjs`
Expected: FAIL，因为线型、band 或标签还没补全。

**Step 3: Write minimal implementation**

在 `kline-slim-chart-renderer.mjs` 完成：

- price line series
- price band custom series
- price label graphic 或 line label
- `buildSceneRenderSeries()` 的渲染顺序

规则固定：

- Guardian：蓝/红/绿实线
- Takeprofit：蓝/红/绿虚线
- 标签前缀分别是 `G-` 和 `TP-`

**Step 4: Run test to verify it passes**

Run: `node --test morningglory/fqwebui/src/views/js/kline-slim-chart-price-guides.test.mjs`
Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/js/kline-slim-chart-renderer.mjs morningglory/fqwebui/src/views/js/kline-slim-chart-price-guides.test.mjs
git commit -m "feat: render guardian and takeprofit price grids on kline"
```

### Task 5: 实现 KlineSlim 页面价格层级面板

**Files:**
- Modify: `morningglory/fqwebui/src/views/KlineSlim.vue`
- Modify: `morningglory/fqwebui/src/views/js/kline-slim.js`
- Test: `morningglory/fqwebui/src/views/js/kline-slim-price-panel.test.mjs`

**Step 1: Write the failing test**

给 `kline-slim-price-panel.test.mjs` 补交互约束：

- Guardian 顺序不合法时阻止保存
- Takeprofit 有空价时阻止保存
- 保存成功后 `priceGuideVersion` 变化并触发重绘

**Step 2: Run test to verify it fails**

Run: `node --test morningglory/fqwebui/src/views/js/kline-slim-price-panel.test.mjs`
Expected: FAIL，说明保存校验或重绘链路还不完整。

**Step 3: Write minimal implementation**

在 `KlineSlim.vue` 增加：

- `价格层级` 开关按钮
- 右侧价格层级面板
- Guardian 三层输入
- Takeprofit 三层输入
- 保存按钮
- 状态标签：
  - Guardian `buy_active`
  - Takeprofit `armed_levels`

在 `kline-slim.js` 完成：

- 校验失败提示
- 保存成功提示
- 保存后重拉 detail
- 重新 `scheduleRender()`

**Step 4: Run test to verify it passes**

Run: `node --test morningglory/fqwebui/src/views/js/kline-slim-price-panel.test.mjs`
Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/KlineSlim.vue morningglory/fqwebui/src/views/js/kline-slim.js morningglory/fqwebui/src/views/js/kline-slim-price-panel.test.mjs
git commit -m "feat: add price guide editor to kline slim"
```

### Task 6: 同步正式文档并做前端验证

**Files:**
- Modify: `docs/current/modules/kline-webui.md`
- Modify: `docs/current/interfaces.md`
- Test: `morningglory/fqwebui/src/views/js/subject-price-guides.test.mjs`
- Test: `morningglory/fqwebui/src/views/js/kline-slim-price-panel.test.mjs`
- Test: `morningglory/fqwebui/src/views/js/kline-slim-chart-price-guides.test.mjs`
- Test: `morningglory/fqwebui/package.json`（仅用于执行现有 build）

**Step 1: Write the failing test**

本任务不新增代码测试，直接把已有测试与构建作为完成门槛。

**Step 2: Run test to verify it fails**

Run: `node --test morningglory/fqwebui/src/views/js/subject-price-guides.test.mjs morningglory/fqwebui/src/views/js/kline-slim-price-panel.test.mjs morningglory/fqwebui/src/views/js/kline-slim-chart-price-guides.test.mjs`
Expected: 如果失败，回到对应任务修复。

Run: `npm run build`
Workdir: `morningglory/fqwebui`
Expected: 如果失败，修前端编译问题。

**Step 3: Write minimal implementation**

更新 `docs/current/modules/kline-webui.md`：

- 写清 `KlineSlim` 已支持 Guardian 与止盈价格层级显示/编辑
- 写清颜色规则、图表横线和网格样式
- 写清保存接口来源和排障入口

必要时更新 `docs/current/interfaces.md`：

- 标注 KlineSlim 页面复用的现有接口

**Step 4: Run test to verify it passes**

Run: `node --test morningglory/fqwebui/src/views/js/subject-price-guides.test.mjs morningglory/fqwebui/src/views/js/kline-slim-price-panel.test.mjs morningglory/fqwebui/src/views/js/kline-slim-chart-price-guides.test.mjs`
Expected: PASS

Run: `npm run build`
Workdir: `morningglory/fqwebui`
Expected: PASS

**Step 5: Commit**

```bash
git add docs/current/modules/kline-webui.md docs/current/interfaces.md morningglory/fqwebui/src/views/KlineSlim.vue morningglory/fqwebui/src/views/js/kline-slim.js morningglory/fqwebui/src/views/js/kline-slim-chart-controller.mjs morningglory/fqwebui/src/views/js/kline-slim-chart-renderer.mjs morningglory/fqwebui/src/views/js/subject-price-guides.mjs morningglory/fqwebui/src/views/js/subject-price-guides.test.mjs morningglory/fqwebui/src/views/js/kline-slim-price-panel.test.mjs morningglory/fqwebui/src/views/js/kline-slim-chart-price-guides.test.mjs
git commit -m "feat: show guardian and takeprofit grids in kline slim"
```
