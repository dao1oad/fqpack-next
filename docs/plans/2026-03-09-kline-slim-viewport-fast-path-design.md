# KlineSlim 视口快路径优化设计

## 背景

当前 `KlineSlim` 的鼠标滚轮缩放与平移虽然功能可用，但交互仍然明显卡顿。根因不在 ECharts 的 `dataZoom` 本身，而在于前端把 `datazoom` 事件直接绑定到了完整的 `drawSlim()` 重绘链路：

1. `handleSlimDataZoom()` 每次滚轮都会触发 `scheduleRender(true)`。
2. `handleSlimDataZoomPointerUp()` 在拖拽结束后还会再触发一次 `scheduleRender(true)`。
3. `scheduleRender()` 会重新生成主 K 线、四周期缠论图层、legend placeholder、中枢 `markArea`，最后整图 `setOption()`。

也就是说，缩放和平移这种“只改变视口”的交互，被当前实现当成了“整张图的数据重建”来处理。

## 目标

1. 保留鼠标滚轮缩放和底部拖拽平移的即时生效语义。
2. 将缩放/平移交互从完整 `drawSlim()` 重绘链路中拆出来。
3. 让 `datazoom` 热路径只更新视口，不重建 `series / legend / markArea`。
4. 让后续真实数据刷新、legend 切换、切标的、切周期时，继续继承当前窗口。

## 非目标

1. 不改 `KlineSlim` 页面布局。
2. 不改多周期缠论图层的数据来源、legend 语义或懒加载策略。
3. 不做更大范围的图表 renderer 重构。
4. 不引入新接口或后端改动。

## 现状问题

当前热路径的问题有两层：

1. `datazoom` 事件频率高，滚轮连续输入时会反复进入 `scheduleRender(true)`。
2. `drawSlim()` 在缩放时仍然重建全部图层，尤其是多周期中枢 `markArea`，导致每次交互都做了大量无效工作。

这和旧仓的有效经验不同。旧仓的关键点不是“缩放时完全不更新”，而是“缩放期间不要重画整张图”。现仓上一次为了恢复鼠标交互，把 `scheduleRender(true)` 加回来了，功能恢复了，但也把完整重绘带回了热路径。

## 方案

### 1. 拆分两条更新路径

保留现有的 `chartDataZoomState`，但拆成：

1. 视口快路径
   - 入口：`datazoom`、`mouseup`
   - 只更新 `chartDataZoomState`
   - 只对图表做局部 `dataZoom` 更新
   - 不调用 `drawSlim()`

2. 数据重绘路径
   - 入口：新数据到达、legend 切换、切标的、切主周期、切模式
   - 继续走 `scheduleRender()` -> `drawSlim()`
   - 继续重建缠论图层与中枢

### 2. 新增局部视口更新函数

在 `kline-slim.js` 中新增一个轻量函数，例如 `applySlimViewportWindow(nextState)`，语义如下：

1. 只用 `nextState` 生成 `dataZoom` option。
2. 只调用局部 `chart.setOption({ dataZoom: ... })`。
3. 不下发 `series / legend / grid / xAxis / yAxis`。
4. 不进入 `drawSlim()`。

### 3. 增加内部防抖/防递归标记

局部 `setOption({ dataZoom })` 可能再次触发 `datazoom` 事件，因此需要在 `kline-slim.js` 中增加一个轻量布尔标记，例如 `isApplyingViewportWindow`：

1. 进入局部视口更新前置为 `true`
2. 内部事件回流时直接忽略
3. 更新完成后恢复为 `false`

### 4. 保留 `drawSlim()` 的窗口继承逻辑

`draw-slim.js` 继续保留对 `dataZoomState` 的处理。这样：

1. 缩放时由快路径即时更新窗口
2. 真正发生数据重绘时，`drawSlim()` 继续继承当前窗口
3. 不会回到“状态变了但图没动”的旧问题

## 涉及文件

1. `morningglory/fqwebui/src/views/js/kline-slim.js`
   - 调整 `handleSlimDataZoom()`
   - 调整 `handleSlimDataZoomPointerUp()`
   - 新增局部视口更新函数和递归保护

2. `morningglory/fqwebui/src/views/js/draw-slim.js`
   - 复用已有 `resolveDataZoomState()` 能力
   - 如有必要，补一个只供局部视口更新复用的导出 helper

3. `morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs`
   - 新增/修改文件级测试，锁定“`datazoom` 不再直接驱动完整重绘”

4. `docs/migration/progress.md`
   - 记录本次对 RFC 0022 的追加优化说明

## 风险与防线

### 风险 1：窗口状态和真实图表再次脱节

防线：`datazoom` 事件里除了更新 `chartDataZoomState`，还会立即走局部 `dataZoom` 更新。

### 风险 2：局部 `setOption` 引发 `datazoom` 递归

防线：新增 `isApplyingViewportWindow` 之类的内部保护标记。

### 风险 3：真实数据刷新后窗口被重置

防线：继续保留 `drawSlim()` 对 `dataZoomState` 的继承逻辑。

## 验收标准

1. 鼠标滚轮缩放明显更顺，不再频繁整图卡顿。
2. 鼠标拖拽平移明显更顺。
3. 缩放/平移时窗口立即变化，不再出现“状态变了但图不动”。
4. 等待一次轮询刷新后，当前窗口保持不变。
5. `5m` legend 仍然只控制 `5m` 缠论层，不影响主 K 线。
6. `1m / 15m / 30m` 懒加载策略不回退。
7. 已修好的 legend 显示、中枢残影与主周期图例语义不回退。
