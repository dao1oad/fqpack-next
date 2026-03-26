# KlineSlim 画线编辑顺序与持仓默认排序设计

## 目标

- 让 `画线编辑` 浮层中的两个大区块顺序与图上的价格横线视觉位置一致：`止盈价格` 在上，`Guardian 倍量价格` 在下。
- 让左侧 `持仓股` 列表默认按仓位金额从大到小排序，并让默认打开的标的与该排序口径保持一致。

## 边界

- 只交换两个大区块的顺序，不调整每个区块内部三条价格线的顺序。
- 不改 Guardian / 止盈的保存、开关、运行态和样式语义。
- 不改后端接口排序，持仓默认排序仅在前端统一处理。

## 方案

### 画线编辑区块顺序

- 直接在 `KlineSlim.vue` 中交换 `止盈价格` 与 `Guardian 倍量价格` 两个 `section` 的模板位置。
- 保持各自现有的 summary、批量按钮和行内控件不变。

### 持仓默认排序

- 在 `kline-slim-sidebar.mjs` 增加持仓排序 helper。
- 排序口径使用 `position_amount ?? market_value ?? amount`，按数值降序。
- 缺失或非法值排在后面；相同数值保持原始顺序，避免列表抖动。
- `buildSidebarSections()` 仅对 `holding` 分组应用该排序，不影响其它分组。

### 默认标的选择一致性

- 在 `kline-slim-default-symbol.mjs` 复用同一持仓排序口径。
- 当页面未传 `symbol` 时，默认打开排序后的第一只持仓，保证与 `持仓股` 列表顶部一致。

## 测试

- `klineSlim.test.mjs`：断言 `止盈价格` 出现在 `Guardian 倍量价格` 之前。
- `kline-slim-sidebar.test.mjs`：断言 `holding` 分组按仓位金额降序且稳定。
- 新增 `kline-slim-default-symbol.test.mjs`：断言默认标的选择遵循同一降序口径。

