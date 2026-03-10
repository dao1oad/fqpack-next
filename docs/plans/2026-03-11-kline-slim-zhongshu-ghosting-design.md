# KlineSlim 中枢/段中枢残影修复设计

**目标**：把 `FRE-6` 收敛为一个明确的前端图表生命周期问题来修复：重复切换 `symbol` 后，`中枢 / 段中枢 / 高级段中枢` 这些 `markArea` 类图层不应继续残留在新标的上，同时不能回退 `FRE-5` 已经修好的缩放、平移和视口保持语义。

## 1. 范围与假设

- In：`KlineSlim` 的结构性切换、`markArea` 残影、浏览器自动化回归、同页缩放/平移回归保护。
- Out：后端 fullcalc、接口改造、自绘 renderer、大范围性能重构。
- 假设：
  - 本票的主验收路径以 issue 原文为准，优先覆盖“重复切换不同 `symbol` 后残影累积”。
  - “关闭 `中枢 / 段中枢` 开关后残影消失”作为控制组验证，不单独扩成另一张票。
  - 只要普通同标的实时刷新仍不清图，就不会主动回退 `FRE-5` 的缩放/平移交互。

## 2. 现状证据与根因假设

当前仓库已经有两条直接证据：

1. [`handleRouteChange()`](D:/fqpack/runtime/symphony-service/workspaces/FRE-6/morningglory/fqwebui/src/views/js/kline-slim.js) 在路由切换时会 `resetSlimDataState()`，但当 `routeSymbol` 仍存在时只会 `showLoading()`，并不会先 `chart.clear()`。
2. [`drawSlim()`](D:/fqpack/runtime/symphony-service/workspaces/FRE-6/morningglory/fqwebui/src/views/js/draw-slim.js) 结构性重绘时仍使用：
   - `replaceMerge: ['series', 'legend', 'xAxis', 'yAxis']`
   - `中枢 / 段中枢 / 高级段中枢` 则通过 `markArea` 承载。

因此本次设计采用的主根因假设是：

- 当图表 identity 从 `symbol A` 切到 `symbol B` 时，如果实例没有先清空，旧的 `markArea` 图形元素可能不会被当前的 `replaceMerge` 路径完全回收，于是出现“切得越多、残影越多”的效果。

这个假设与 issue 现象是对得上的：

- 只影响 `中枢 / 段中枢`；
- 关闭对应 legend 后不再可见；
- 同标的轮询刷新不是主触发器，切标的是主触发器。

## 3. 方案选项

### 方案 A：结构性切换时 controller 显式清图（推荐）

- 在 `kline-slim.js` 中把 `symbol / period / endDate` 的切换视为结构性切换。
- 进入新 identity 前先 `chart.clear()`，再 `showLoading()` 等待首帧数据。
- 同标的轮询刷新、legend 切换、缩放和平移继续走当前路径，不改 steady-state renderer。

优点：

- 改动最小，和 issue 描述最贴合。
- 不需要重写 `draw-slim.js`。
- 不容易回退 `FRE-5` 已修好的数据缩放语义。

缺点：

- 切标的/切主周期时视口会重置。
- 如果真正残留点在 renderer 更深层，这个方案可能还不够。

### 方案 B：在 renderer 的 `keepState: false` 分支统一 `chart.clear()`

- 保持 controller 不变，把结构性重绘的“先清空实例”语义下沉到 `drawSlim()`。

优点：

- 语义更集中，`keepState: false` 的含义更完整。

缺点：

- 会改动现有 renderer 约定。
- 需要同步改现有测试里关于 `keepState: false` 的假设。

### 方案 C：放弃 `markArea`，改成自绘矩形或自定义系列

优点：

- 可能从根上绕开 ECharts 对 `markArea` 的 diff 行为。

缺点：

- 超出本票范围。
- 回归面过大，不适合当前 Todo 阶段。

## 4. 推荐设计

采用方案 A。

### 4.1 结构性切换定义

以下任一变化都算结构性切换：

- `symbol` 变化
- 主 `period` 变化
- `endDate` 从空变有值、或从有值变空、或值本身变化

这几种变化都会让当前主图 identity 发生变化，不应继续复用旧 `markArea` 图形元素。

### 4.2 图表生命周期

- 结构性切换：
  - 先 `chart.clear()`
  - 再 `showLoading()`
  - 等待新数据首帧后按现有 `drawSlim()` 路径渲染
- 普通同 identity 刷新：
  - 不清图
  - 继续沿用当前 `setOption + replaceMerge + dataZoom` 语义
- legend 切换：
  - 不清图
  - 继续视为同 identity 内的图层开关

### 4.3 为什么不在本票改 renderer

本票的目标是“去掉切标的累积残影”，不是“重写图层引擎”。当前 renderer 已经承载了：

- 多周期图层
- `FRE-5` 之后收敛出的缩放/平移语义
- `dataZoom` 的独立 replaceMerge 路径

在 Todo 阶段优先用 controller 生命周期修复，可以把风险控制在最小范围内。如果后续浏览器回归仍然失败，再说明需要针对 renderer 单独开下一层修复。

## 5. 测试与验收设计

### 5.1 文件级回归

沿用现有 [`kline-slim-multi-period-chanlun.test.mjs`](D:/fqpack/runtime/symphony-service/workspaces/FRE-6/morningglory/fqwebui/tests/kline-slim-multi-period-chanlun.test.mjs) 风格，新增两类断言：

- `handleRouteChange()` 在结构性切换时存在显式 `chart.clear()` 路径；
- 普通 `fetchMainData()` 或同 identity 刷新路径不包含对应清图逻辑。

### 5.2 浏览器自动化主路径

新增专用浏览器回归：

1. 用 stub API 为多个 `symbol` 生成稳定但明显不同的 deterministic 图形数据；
2. 保持 `中枢 / 段中枢` 打开；
3. 初始打开 `symbol A`，记录截图哈希；
4. 连续切到 `symbol B -> symbol C -> symbol A`；
5. 回到 `symbol A` 后再次截图，要求与步骤 3 的哈希一致。

这个验收方式直接对应 issue 现象：“随着标的切换越来越多，残影越来越多”。

### 5.3 控制组验证

在同一测试里再做一步：

- 关闭 `中枢 / 段中枢` legend，再次切换 `symbol`；
- 页面不应保留旧的中枢矩形残留。

### 5.4 回归保护

必须继续复跑已有的 [`kline-slim-zoom-pan.browser.spec.mjs`](D:/fqpack/runtime/symphony-service/workspaces/FRE-6/morningglory/fqwebui/tests/kline-slim-zoom-pan.browser.spec.mjs)，因为本票的修复边界明确不能回退 `FRE-5`。

## 6. Human Review 决策点

- 是否接受“切 `symbol / period / endDate` 时重置视口”作为本票允许的代价。
- 是否接受把浏览器自动化主验收路径聚焦到“重复切换标的”而不是扩展到所有 period/legend 组合。
- 是否接受本票先不改 renderer，只做 controller 生命周期修复。
