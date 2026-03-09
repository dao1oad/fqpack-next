# KlineSlim 恢复鼠标缩放平移功能设计

**日期**: 2026-03-09

## 背景

`KlineSlim` 最近一轮“缩放热路径不重绘”的性能优化后，浏览器里的鼠标滚轮缩放和平移再次失效。实际排查表明，问题不是 `datazoom` 事件没有触发，而是事件只更新了 `chartDataZoomState`，没有再把这个窗口状态应用回图表。

## 目标

- 恢复鼠标滚轮缩放功能
- 恢复鼠标拖拽平移功能
- 保留刷新后视口窗口的继承能力
- 不回退 legend、多周期懒加载、中枢残影等已有修复

## 非目标

- 不继续做本轮性能优化
- 不修改后端接口
- 不重构 `draw-slim.js` 的 renderer 架构

## 根因结论

当前版本里：

- [kline-slim.js](D:/fqpack/freshquant-2026.2.23/.worktrees/fix-kline-slim-zoom-pan-restore/morningglory/fqwebui/src/views/js/kline-slim.js) 的 `handleSlimDataZoom()` 只更新 `chartDataZoomState`
- `handleSlimDataZoomPointerUp()` 只同步最终窗口
- 两处都不再调用 `scheduleRender(true)`

浏览器复现结果显示：

- `chartDataZoomState` 在滚轮后确实变化了
- 但 `chart.getOption().dataZoom[0]` 没有变化
- 直到手工执行一次 `scheduleRender(true)` 后，图表视口才真正变化

因此当前回归的根因是：窗口状态被缓存了，但没有被立即应用回图表。

## 方案比较

### 方案 A：恢复交互期即时重绘（推荐）

- 在 `handleSlimDataZoom()` 恢复 `this.scheduleRender(true)`
- 在 `handleSlimDataZoomPointerUp()` 恢复 `this.scheduleRender(true)`

优点：

- 与上次成功修复版本一致
- 改动最小
- 能直接恢复功能

缺点：

- 会回到交互期即时重绘的行为

### 方案 B：只在 `mouseup` 后重绘

优点：

- 重绘次数更少

缺点：

- 滚轮缩放可能仍然表现为不即时

### 方案 C：单独做轻量 dataZoom 局部更新

优点：

- 理论上功能和性能都更优

缺点：

- 实现复杂度明显更高
- 不适合这轮“先恢复功能”的目标

## 决策

采用方案 A。

## 设计

### 1. 交互期恢复即时重绘

- `handleSlimDataZoom()` 在更新 `chartDataZoomState` 后立即 `scheduleRender(true)`
- `handleSlimDataZoomPointerUp()` 在同步最终窗口后再次 `scheduleRender(true)`

### 2. 保留已有状态模型

继续保留：

- `chartDataZoomState`
- `renderVersion`
- `legendSelected`
- `resetChartStateOnNextRender`

也就是说，这次不是推翻上一轮的状态模型，而是恢复“状态更新后要立即应用”的最后一步。

## 测试与验收

### 自动化测试

在 [kline-slim-multi-period-chanlun.test.mjs](D:/fqpack/freshquant-2026.2.23/.worktrees/fix-kline-slim-zoom-pan-restore/morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs) 中锁定：

- `handleSlimDataZoom()` 包含 `scheduleRender(true)`
- `handleSlimDataZoomPointerUp()` 包含 `scheduleRender(true)`

### 浏览器烟测

验证：

1. 鼠标滚轮缩放后图表窗口立即变化
2. 鼠标拖拽平移后图表窗口立即变化
3. 刷新后窗口仍保持
