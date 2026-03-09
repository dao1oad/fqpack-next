# KlineSlim 缩放平移与 Legend 状态修复设计

## 背景

`KlineSlim` 在恢复多周期缠论图层后，又暴露出两类交互回归：

1. 图表的放大、缩小和平移在轮询刷新后不可用，或者刚操作完就被重置。
2. 当前主周期 `5m` 的 legend 只能显示，不能真正控制 `5m` 缠论层显隐；主 K 线本身不应受影响。

本轮只修复图表交互状态保持，不改页面布局、不改后端接口、不改 Redis 推送语义。

## 根因

### 1. `5m` legend 无效

当前 [kline-slim.js](D:/fqpack/freshquant-2026.2.23/.worktrees/fix-kline-slim-zoom-legend-state/morningglory/fqwebui/src/views/js/kline-slim.js) 的 `scheduleRender()` 去重键只包含：

- 当前主周期数据版本
- 额外可见周期数据版本

但没有包含：

- 当前周期 legend 勾选状态
- `中枢 / 段中枢` 全局开关状态

结果是点击 `5m` legend 时，因为没有新数据请求、`renderVersion` 也没变化，重绘会被短路，当前周期缠论层不会更新。

### 2. 缩放和平移状态丢失

当前 [draw-slim.js](D:/fqpack/freshquant-2026.2.23/.worktrees/fix-kline-slim-zoom-legend-state/morningglory/fqwebui/src/views/js/draw-slim.js) 每次刷新都会重新下发 `dataZoom`，并且 `replaceMerge` 包含了 `dataZoom`。这会在普通轮询刷新时反复重建 slider 和 inside zoom 组件，导致：

- 用户刚缩放过的窗口被重置
- 平移后窗口位置丢失
- 交互表现看起来像“放大缩小和平移不能用了”

## 目标

- 修复 `5m` legend 对当前主周期缠论层无效的问题。
- 保持 `5m` 主 K 线始终可见，不受 `5m` legend 影响。
- 让缩放、平移状态在普通轮询刷新后继续保持。
- 保持切换标的、切换主周期时允许重置为默认窗口。

## 非目标

- 不改多周期懒加载策略。
- 不新增新的 legend 分组。
- 不改后端 `/api/stock_data` 接口。
- 不调整上次已经修好的中枢 remap 与残影清理策略。

## 方案比较

### 方案 A：最小补丁

- 给 `renderVersion` 追加 legend 状态签名
- 从 `replaceMerge` 移除 `dataZoom`

优点：

- 改动最小

缺点：

- legend 状态和缩放状态仍然分散在图表内部状态里
- 后续容易继续出现“刷新后状态丢失”的同类回归

### 方案 B：显式 UI 状态收口

- 在 `kline-slim.js` 显式保存 `chanlunLegendSelected`
- 在 `kline-slim.js` 显式保存 `chartDataZoomState`
- `draw-slim.js` 只消费这些状态，不主动从 `chart.getOption()` 推断

优点：

- 当前周期 legend、额外周期 legend、全局中枢开关都能稳定参与重绘判定
- 缩放和平移状态来源单一，普通刷新可稳定保留
- 与“结构性切换时允许重置”语义边界清晰

缺点：

- 需要补几个图表事件监听和测试

### 方案 C：继续依赖 `chart.getOption()`

- 每次刷新从 ECharts 当前 option 反推 legend 与 dataZoom 状态

优点：

- 表面上改动少

缺点：

- 强依赖 ECharts 返回结构
- 可维护性最差，也最容易再回归

**结论：采用方案 B。**

## 最终设计

### 1. 图表状态模型

在 `kline-slim.js` 中显式持有两类 UI 状态：

- `chanlunLegendSelected`
  - 保存 `1m / 5m / 15m / 30m / 中枢 / 段中枢` 的勾选状态
  - 既用于懒加载，也参与 render 去重键
- `chartDataZoomState`
  - 保存当前缩放/平移窗口，例如 `start/end/startValue/endValue`
  - 仅在用户交互或结构性切换时更新

### 2. Legend 交互语义

- `5m` legend 只控制 `5m` 的缠论层：
  - `笔`
  - `段`
  - `高级别段`
  - `中枢`
  - `段中枢`
  - `高级段中枢`
- `5m` 主 K 线始终显示，不受 `5m` legend 影响。
- `1m / 15m / 30m` 继续按原有懒加载语义工作。
- 全局 `中枢 / 段中枢` 继续只控制对应中枢类图层。

### 3. 缩放和平移状态保持

- 在图表初始化后绑定 `datazoom` 事件。
- 用户每次缩放或平移后，将最新窗口写回 `chartDataZoomState`。
- 普通轮询刷新时复用该状态，不重新初始化 `dataZoom`。
- 切换标的、切换主周期、切换实时/历史模式时重置 `chartDataZoomState`，回到默认窗口。

### 4. Renderer 更新规则

`draw-slim.js` 改为：

- 显式接收 `legendSelected`
- 显式接收 `dataZoomState`
- `legend.selected` 直接使用传入状态
- `dataZoom` 只在首次结构渲染时初始化默认窗口，否则复用传入窗口
- `replaceMerge` 不再包含 `dataZoom`
- `keepState=false` 时仍保留 `chart.clear() + notMerge: true`，避免图层残影

### 5. 测试策略

新增或扩展测试覆盖：

- `draw-slim` 使用显式传入的 legend/dataZoom 状态
- 当前周期 legend 状态参与 `scheduleRender()` 去重键
- `datazoom` 事件绑定与窗口状态回写
- 普通刷新不重置缩放/平移
- `5m` legend 不影响主 K 线

## 验收标准

1. 图表可以正常放大、缩小、平移。
2. 普通轮询刷新后，当前窗口位置保持不变。
3. `5m` legend 可以控制 `5m` 缠论层显隐。
4. `5m` 主 K 线始终保留，不受 legend 影响。
5. `1m / 15m / 30m` legend 的懒加载行为不变。
6. 全局 `中枢 / 段中枢` 开关继续有效。
7. 切换标的或主周期时，图表允许重置到新的默认窗口。
8. 不回退上次已经修好的 legend 显示和中枢残影修复。
