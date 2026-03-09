# KlineSlim 缩放平移与当前周期 Legend 状态修复设计

**日期**: 2026-03-09

## 背景

`KlineSlim` 在最近两轮修复后已经恢复了多周期缠论图层、legend 显示和中枢残影清理，但仍有两个实际交互问题：

1. 鼠标滚轮缩放和拖拽平移看起来无效。
2. `5m` 主周期上的 `5m` 缠论结构 legend 开关不稳定，刷新后容易失效。

这两个问题都与图表状态保持逻辑有关，而不是后端数据缺失。

## 目标

- 恢复 `KlineSlim` 主图的鼠标滚轮缩放能力。
- 恢复 `KlineSlim` 主图的拖拽平移能力。
- 轮询刷新后保留用户当前的缩放和平移窗口。
- 让 `5m` legend 只控制 `5m` 缠论层，不影响 `5m` 主 K 线。
- 保持已经修好的多周期 legend、懒加载和中枢残影清理逻辑不回退。

## 非目标

- 不修改 `KlineSlim` 页面布局。
- 不修改 `/api/stock_data` 或任何后端接口。
- 不新增新的图表交互模式。
- 不回退当前仓的多周期缠论图层实现。

## 根因结论

### 1. 缩放和平移失效的根因

浏览器实测表明，ECharts 的 `datazoom` 事件已经正常触发，事件 payload 里也携带了新的缩放窗口；问题出在当前前端在 `datazoom` 回调里同步读取 `chart.getOption().dataZoom` 作为真值。

在当前实现里，这个读取时机过早，拿到的仍然是旧窗口值。后续轮询刷新再把这个旧窗口写回图表，于是用户看到的效果就是“缩放和平移没有反应”。

### 2. `5m` legend 失效的根因

当前周期的 legend 状态虽然已经存入 `chanlunLegendSelected`，但刷新去重键和重绘触发时机仍然不稳定，导致只切换当前主周期缠论层时，重绘可能被错误短路。

## 方案比较

### 方案 A：继续依赖 `chart.getOption()`，但延迟一帧读取

优点：
- 改动最小。

缺点：
- 仍然依赖 ECharts 内部状态何时落盘，不稳。
- 后续容易再次回归。

### 方案 B：把 `datazoom` 事件 payload 作为唯一缩放状态来源（推荐）

优点：
- 直接修正已验证的根因。
- 与当前显式状态模型兼容。
- 能同时收口 `legend` 和 `dataZoom` 两类 UI 状态。

缺点：
- 需要调整 `kline-slim.js` 和 `draw-slim.js` 的状态边界。

### 方案 C：完全回退到旧分支的隐式状态继承

优点：
- 最接近旧分支。

缺点：
- 当前仓已经引入多周期 legend 与懒加载，完全回退会打散现有实现。
- 风险高于定点修复。

## 决策

采用方案 B。

核心原则：

1. `datazoom` 事件 payload 是缩放和平移状态的唯一真值来源。
2. 普通轮询刷新只更新数据，不重建 `dataZoom` 组件。
3. 结构性切换（切标的、切主周期、切模式）仍允许清图并重置窗口。
4. `5m` legend 只控制 `5m` 缠论层，不控制主 K 线。

## 设计

### 1. 状态模型

在 `kline-slim.js` 中继续显式维护两类 UI 状态：

- `chanlunLegendSelected`
  - 保存 `1m / 5m / 15m / 30m / 中枢 / 段中枢` 的选中状态。
  - 必须参与 `renderVersion` 计算，确保当前主周期 legend 切换也会触发重绘。

- `chartDataZoomState`
  - 保存当前缩放和平移窗口。
  - 只从 `datazoom` 事件参数更新。
  - 不再在 `datazoom` 回调里同步读取 `chart.getOption().dataZoom`。

### 2. 渲染规则

- 普通轮询刷新：
  - 保留 `chartDataZoomState`
  - 保留 `chanlunLegendSelected`
  - 只更新 series 和相关图层数据

- 结构性重绘：
  - 切标的、切主周期、切实时/历史模式时触发
  - 允许 `chart.clear()`
  - 允许重置 `chartDataZoomState`

### 3. 旧分支参考方式

参考旧分支的语义，而不是整段回退：

- 不在错误时机从图表内部 option 回读交互状态。
- 普通刷新不要不断替换 `dataZoom` 组件。
- 结构性切换才做全量替换。

## 测试与验收

### 自动化测试

- 为 `kline-slim.js` 增加文件级回归测试：
  - 锁定 `handleSlimDataZoom()` 使用事件 payload，而不是 `chart.getOption()`
  - 锁定当前 legend 状态参与重绘版本签名

- 为 `draw-slim.js` 增加文件级回归测试：
  - 锁定 `dataZoomState` 透传
  - 锁定普通刷新不替换 `dataZoom`

### 手工冒烟

访问：

- `http://127.0.0.1:18080/kline-slim?symbol=sh510050&period=5m`

检查：

1. 鼠标滚轮缩放立即生效。
2. 拖拽平移立即生效。
3. 等待一次刷新后，当前窗口保持不变。
4. 点击 `5m` legend，主 K 线保留，`5m` 缠论层消失；再次点击后恢复。
