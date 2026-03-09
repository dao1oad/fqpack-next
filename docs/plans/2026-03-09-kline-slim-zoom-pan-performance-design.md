# KlineSlim 缩放/平移卡顿性能优化设计

**日期**: 2026-03-09

## 背景

`KlineSlim` 在最近两轮修复后已经恢复了：

- 多周期缠论图层与 legend 分组显示
- 中枢残影清理
- 缩放/平移状态在刷新后的保留

但实际浏览器交互里，鼠标滚轮缩放仍有明显卡顿。根因不是 ECharts 原生缩放性能不足，而是当前前端在缩放热路径里主动触发了全量图表重绘。

## 目标

- 消除鼠标滚轮缩放与拖拽平移时的明显卡顿
- 保留刷新后的缩放/平移窗口状态
- 不回退已经修好的 legend、中枢残影、多周期懒加载逻辑
- 保持 `5m` legend 只控制 `5m` 缠论层，不影响主 K 线

## 非目标

- 不重做 `KlineSlim` 页面布局
- 不调整 `/api/stock_data` 或其他后端接口
- 不在本阶段做 renderer 结构性拆分
- 不在本阶段做中枢大规模裁剪或双图层架构

## 根因结论

### 1. 缩放热路径触发了不必要的全量重绘

当前实现中：

- [kline-slim.js](D:/fqpack/freshquant-2026.2.23/.worktrees/brainstorm-kline-slim-zoom-pan-performance/morningglory/fqwebui/src/views/js/kline-slim.js) 的 `handleSlimDataZoom()` 在每次 `datazoom` 事件里都会调用 `scheduleRender(true)`
- `handleSlimDataZoomPointerUp()` 在拖拽结束后又会再触发一次 `scheduleRender(true)`
- `scheduleRender(true)` 会继续调用 [draw-slim.js](D:/fqpack/freshquant-2026.2.23/.worktrees/brainstorm-kline-slim-zoom-pan-performance/morningglory/fqwebui/src/views/js/draw-slim.js)，重新构造完整 `option` 并执行 `chart.setOption(...)`

这意味着用户每滚一下滚轮，前端都会在 ECharts 原生缩放之外，再额外跑一轮完整的 series/legend/grid 重绘。

### 2. 旧仓的语义更接近“保留视口状态”，而不是“缩放即重绘”

旧仓 [draw-slim.js](D:/fqpack/freshquant/morningglory/fqwebui/src/views/js/draw-slim.js) 的关键做法是：

- 真正重绘时继承 `previousOption.dataZoom`
- 交互过程中不把 `datazoom` 事件当作一次新的 renderer 触发器

这说明旧仓把 `dataZoom` 当成 UI 视口状态，而不是数据变更信号。

## 方案比较

### 方案 A：缩放期间只同步状态，不触发重绘（推荐）

做法：

- `datazoom` 和 `mouseup` 期间只更新 `chartDataZoomState`
- 不在这两个事件里调用 `scheduleRender()`
- 只在数据刷新、legend 变化、周期懒加载、主周期切换、标的切换等真正需要时重绘

优点：

- 直接切掉当前最重的热路径
- 最接近旧仓行为语义
- 改动集中、风险最低

缺点：

- 缩放过程中不会顺手触发其他图层的重算，但这本身就是合理取舍

### 方案 B：缩放期间保留重绘，但增加节流

做法：

- `datazoom` 仍触发 `scheduleRender()`
- 但改成 120ms 到 200ms 节流一次

优点：

- 改动较小

缺点：

- 仍然在交互热路径里做全量 `setOption()`
- 只能缓解，不能消除根因

### 方案 C：拆分主图与缠论层为双实例

做法：

- 主 K 线图只负责行情与 dataZoom
- 缠论层延迟同步或单独绘制

优点：

- 理论性能上限最高

缺点：

- 复杂度远超本轮问题
- 会显著增加维护面和回归风险

## 决策

采用方案 A。

核心原则：

1. 缩放/平移是视口交互，不是数据变更
2. 缩放热路径只缓存 `chartDataZoomState`，不触发 `drawSlim()`
3. 下一次真实重绘时再把缓存窗口应用回图表
4. 保留结构性切换时的全量重绘与清图逻辑

## 设计

### 1. 交互期与重绘期分离

图表生命周期拆成两段：

- 交互期：鼠标滚轮缩放、拖拽平移时，只更新 `chartDataZoomState`
- 重绘期：只有数据刷新、legend 切换、懒加载周期返回、主周期切换、标的切换、模式切换时才调用 `drawSlim()`

这样做以后，ECharts 原生缩放自己完成视觉变换，应用层只负责记住窗口。

### 2. `handleSlimDataZoom()` 的新语义

- 继续从事件 payload 提取窗口
- 继续写回 `chartDataZoomState`
- 去掉 `scheduleRender(true)`

### 3. `handleSlimDataZoomPointerUp()` 的新语义

- 保留 `requestAnimationFrame` 后读取稳定 `chart.getOption().dataZoom`
- 只把最终窗口同步回 `chartDataZoomState`
- 去掉 `scheduleRender(true)`

保留这个同步动作的原因是：拖拽结束后，ECharts 内部窗口值比事件流中间态更适合作为“最终视口状态”。

### 4. 仍然保留的重绘触发点

- `legendselectchanged`
- 实时轮询拿到新数据
- 懒加载周期数据成功返回
- 切换主周期
- 切换标的
- 切换实时/历史模式

这些场景都对应实际的数据或图层变化，仍然应该触发 `drawSlim()`

## 测试与验收

### 自动化测试

在 [kline-slim-multi-period-chanlun.test.mjs](D:/fqpack/freshquant-2026.2.23/.worktrees/brainstorm-kline-slim-zoom-pan-performance/morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs) 增加回归断言，锁定：

- `handleSlimDataZoom()` 不再调用 `scheduleRender(true)`
- `handleSlimDataZoomPointerUp()` 不再调用 `scheduleRender(true)`
- `drawSlim()` 仍然消费显式传入的 `dataZoomState`

### 浏览器烟测

在 `/kline-slim?symbol=sh510050&period=5m` 验证：

1. 滚轮缩放明显更顺
2. 拖拽平移明显更顺
3. 等待一次实时刷新后，当前窗口保持不变
4. `5m` legend 仍然只控制 `5m` 缠论层

## 第二阶段候选项（本轮不做）

- 降低 `drawSlim()` 每次重绘时的 placeholder series 构造成本
- 对不可见范围外的中枢做更积极裁剪
- 评估双图层或双实例架构是否值得引入
