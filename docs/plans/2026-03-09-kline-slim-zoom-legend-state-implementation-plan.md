# KlineSlim 缩放平移与 Legend 状态修复 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复 `KlineSlim` 的缩放/平移状态在刷新后丢失，以及当前主周期 `5m` legend 无法控制当前周期缠论层的问题。

**Architecture:** 将 legend 选择状态和 dataZoom 窗口状态从 renderer 内部推断，收口到 `kline-slim.js` 的显式 UI 状态；`draw-slim.js` 只消费这些状态并在结构性重绘时初始化默认窗口。保持主 K 线与缠论层解耦，确保 `5m` legend 只控制缠论层。

**Tech Stack:** Vue 3, ECharts 6, Node test runner, Vite

---

### Task 1: 补回归测试，先锁定交互状态回归

**Files:**
- Modify: `morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs`

**Step 1: Write the failing tests**

补充以下断言：

- `drawSlim()` 使用传入的 `legendSelected`
- `drawSlim()` 使用传入的 `dataZoomState`
- 普通刷新时 `replaceMerge` 不包含 `dataZoom`
- `kline-slim.js` 绑定 `datazoom` 事件并维护 `chartDataZoomState`
- `scheduleRender()` 的去重键包含 legend 状态

**Step 2: Run test to verify it fails**

Run:

```powershell
node --test tests/kline-slim-multi-period-chanlun.test.mjs
```

Expected:

- 新增断言失败，证明当前实现没有保存 legend/dataZoom 状态

**Step 3: Commit**

```powershell
git add morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs
git commit -m "test: 覆盖 kline slim 图表交互状态回归"
```

### Task 2: 收口 `kline-slim.js` 的 legend 和 dataZoom 状态

**Files:**
- Modify: `morningglory/fqwebui/src/views/js/kline-slim.js`
- Test: `morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs`

**Step 1: Add explicit UI state**

新增：

- `chartDataZoomState`
- `handleSlimDataZoom`
- `buildRenderStateVersion()` 或等价 render key 逻辑

**Step 2: Bind chart events**

在 `initChart()` 里绑定：

- `legendselectchanged`
- `datazoom`

并在 `beforeUnmount()` 中解绑。

**Step 3: Update render scheduling**

修改 `scheduleRender()`：

- render key 必须包含当前 legend 选择状态
- 普通刷新时复用 `chartDataZoomState`
- 结构性切换时允许 `resetChartStateOnNextRender`

**Step 4: Reset state on structural changes**

在 `resetSlimDataState()` 中重置：

- `chanlunLegendSelected`
- `chartDataZoomState`

但普通轮询刷新不重置。

**Step 5: Run targeted tests**

Run:

```powershell
node --test tests/kline-slim-multi-period-chanlun.test.mjs
```

Expected:

- 新增 controller 相关断言通过

**Step 6: Commit**

```powershell
git add morningglory/fqwebui/src/views/js/kline-slim.js morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs
git commit -m "fix: 保留 kline slim 图表交互状态"
```

### Task 3: 更新 `draw-slim.js`，让 renderer 只消费显式状态

**Files:**
- Modify: `morningglory/fqwebui/src/views/js/draw-slim.js`
- Test: `morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs`

**Step 1: Extend renderer options**

为 `drawSlim()` 增加入参：

- `legendSelected`
- `dataZoomState`

**Step 2: Remove dataZoom replacement on normal refresh**

修改 `setOption()`：

- 保留 `keepState=false` 时 `chart.clear()`
- `replaceMerge` 去掉 `dataZoom`

**Step 3: Preserve main K line while toggling current-period chanlun**

保持主 K 线 series 独立存在，当前周期 legend 只影响缠论层，不影响 candlestick series。

**Step 4: Apply explicit state**

- `legend.selected` 直接使用 `legendSelected`
- `dataZoom` 优先使用 `dataZoomState`
- 无状态时才退回默认 `70-100`

**Step 5: Run targeted tests**

Run:

```powershell
node --test tests/kline-slim-multi-period-chanlun.test.mjs
```

Expected:

- renderer 相关断言全部通过

**Step 6: Commit**

```powershell
git add morningglory/fqwebui/src/views/js/draw-slim.js morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs
git commit -m "fix: 保留 kline slim 缩放与 legend 状态"
```

### Task 4: 跑相邻验证，确认没有回归现有 KlineSlim 功能

**Files:**
- Verify only

**Step 1: Run adjacent frontend tests**

Run:

```powershell
node --test tests/kline-slim-default-symbol.test.mjs tests/kline-slim-sidebar.test.mjs tests/kline-slim-chanlun-structure.test.mjs tests/kline-slim-multi-period-chanlun.test.mjs
```

Expected:

- KlineSlim 相关 4 个测试文件全部通过

**Step 2: Run build**

Run:

```powershell
npm run build
```

Expected:

- Vite build 成功

**Step 3: Commit if build output changed**

```powershell
git add morningglory/fqwebui/web
git commit -m "build: 更新 kline slim 前端产物"
```

### Task 5: 浏览器烟测与迁移进度更新

**Files:**
- Modify: `docs/migration/progress.md`

**Step 1: Run browser smoke**

验证：

1. `/kline-slim?symbol=sh510050&period=5m`
2. 手动或自动执行 `5m -> 15m -> 5m`
3. 操作缩放和平移
4. 等待一次轮询刷新
5. 确认窗口未跳回默认
6. 点击 `5m` legend，确认只隐藏 `5m` 缠论层，不影响主 K 线

**Step 2: Update migration progress**

在 `docs/migration/progress.md` 的 RFC 0022 条目中追加：

- 本次修复的 legend/current-period render state 问题
- 本次修复的 dataZoom 状态保持问题
- 关键验证命令与浏览器烟测结论

**Step 3: Run final verification**

Run:

```powershell
git diff --check
node --test tests/kline-slim-default-symbol.test.mjs tests/kline-slim-sidebar.test.mjs tests/kline-slim-chanlun-structure.test.mjs tests/kline-slim-multi-period-chanlun.test.mjs
npm run build
```

Expected:

- 无 diff 格式错误
- 测试通过
- 构建通过

**Step 4: Commit**

```powershell
git add docs/migration/progress.md
git commit -m "docs: 更新 kline slim 图表交互修复进度"
```
