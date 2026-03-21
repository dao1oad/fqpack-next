# TPSL 页面优化 Design

## 目标

收敛 `/tpsl` 页面职责：

- 不再在该页编辑 symbol 级止盈层级。
- 左侧标的列表直接展示默认三层止盈价格，和 `KlineSlim` 的设置口径保持一致。
- 右侧详情新增 `stock_fills` 视图，方便与 `open buy lots` / 统一触发历史做对照。

## 约束

- 当前正式详情接口是 `/api/tpsl/management/<symbol>`。
- `stock_fills` 仍是一套独立的旧订单视图，但页面需要把它作为对照信息展示出来。
- 现有 TPSL worker 与 takeprofit 保存接口继续保留，避免破坏其他入口，例如 `KlineSlim`。

## 方案

采用后端聚合方案：

1. 在 `freshquant.tpsl.management_service.TpslManagementService.get_symbol_detail()` 中追加 `stock_fills` 字段。
2. `stock_fills` 读取复用 `freshquant.data.astock.holding.get_stock_fills()`，并在服务层统一转成 JSON-safe 列表。
3. `/tpsl` 前端删除 symbol 级止盈编辑表，不再从该页发起保存/启停止盈层级动作。
4. 左侧标的卡片直接展示 `L1 / L2 / L3` 三个价格；若缺失则展示 `-`。
5. 右侧详情新增 `stock_fills` 表格，用于和 `open buy lot`、统一触发历史对比。
6. `Rearm` 保留，但移动到详情头部，避免删除止盈编辑区后失去该操作。

## 取舍

- 不采用前端额外请求 `/api/stock_fills` 的方案，因为那会让页面同时维护两套路由和响应格式。
- 不删除后端 takeprofit 保存/启停接口，因为 `KlineSlim` 仍然依赖它们。
- 不新增新的 TPSL API，避免产生平行接口面。

## 验证

- 后端测试覆盖 `get_symbol_detail()` 聚合 `stock_fills`。
- 前端测试覆盖：
  - 左侧卡片显示三层止盈价格。
  - 详情 view model 保留 `stock_fills`。
- 页面源码不再包含“标的止盈层次”编辑区。
