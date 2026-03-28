# 订单管理

## 职责

订单管理是交易链的账本与执行事实层，当前负责：

- 统一受理 API、CLI、Guardian、TPSL 的下单/撤单请求
- 维护 `request -> internal order -> broker order -> execution fill` 主链
- 基于成交聚合生成 `position entry / entry slice / exit allocation`
- 基于券商仓位差额维护 `reconciliation gap / resolution`
- 为 TPSL、SubjectManagement、KlineSlim、PositionManagement 提供 entry 级读模型
- 为旧接口保留 `stock_fills` 兼容投影，但兼容投影不再参与运行期真值判断

## 入口

- HTTP
  - `/api/order/submit`
  - `/api/order/cancel`
  - `/api/stock_order`
  - `/api/order-management/orders`
  - `/api/order-management/orders/<internal_order_id>`
  - `/api/order-management/entries/<entry_id>`
  - `/api/order-management/stats`
  - `/api/order-management/stoploss/bind`
- CLI
  - `python -m freshquant.cli om-order submit ...`
  - `python -m freshquant.cli om-order cancel ...`
  - `python -m freshquant.cli stock.fill rebuild --code <symbol>`
  - `python -m freshquant.cli stock.fill rebuild --all`
  - `python -m freshquant.cli stock.fill compare --code <symbol>`
- 核心服务
  - `freshquant.order_management.submit.service.OrderSubmitService`
  - `freshquant.order_management.read_service.OrderManagementReadService`
  - `freshquant.order_management.tracking.service.OrderTrackingService`
  - `freshquant.order_management.ingest.xt_reports.OrderManagementXtIngestService`
  - `freshquant.order_management.reconcile.service.ExternalOrderReconcileService`

当前已经删除 `/api/order-management/buy-lots/<buy_lot_id>`；止损绑定接口只接受 `entry_id`。

## 当前账本边界

### 券商真值

- 当前仓位真值只认 `xt_positions`
- 当前委托/成交回报真值只认 XT callback 与 `xt_account_sync.worker` 增量刷新

### OM 主账本

- `om_order_requests`
  - 内部下单意图
- `om_orders`
  - 兼容期内部订单壳
- `om_broker_orders`
  - 券商订单聚合，维护 `requested_quantity / filled_quantity / avg_filled_price / fill_count`
- `om_execution_fills`
  - 真实券商成交 fill，`broker_trade_id` 去重
- `om_trade_facts`
  - 兼容期成交事实镜像，仍保留给旧读链和部分排障
- `om_position_entries`
  - 系统持仓入口真值，供 TPSL/Subject/Kline/持仓解释层消费
- `om_entry_slices`
  - entry 的 Guardian 切片
- `om_exit_allocations`
  - 卖出对 entry / slice 的分摊结果
- `om_reconciliation_gaps`
  - 券商仓位与账本持仓解释之间的差额
- `om_reconciliation_resolutions`
  - 差额的自动收敛结果
- `om_entry_stoploss_bindings`
  - entry 级止损绑定
- `om_ingest_rejections`
  - 进入 XT ingest 但不允许进入主账本的拒绝记录

### legacy / 兼容集合

- `om_buy_lots`
- `om_lot_slices`
- `om_sell_allocations`
- `om_external_candidates`
- `om_stoploss_bindings`
- `freshquant.stock_fills`
- `freshquant.stock_fills_compat`

这些集合仍存在于迁移期，但不再定义运行期真值。`stock_fills_compat` 当前只作为 legacy mirror / adapter 输出，镜像口径已经切到 open `position_entries`。

## 当前数据流

### 下单

`submit_order -> credit mode resolve -> position gate -> om_order_requests / om_orders / om_broker_orders / om_order_events -> STOCK_ORDER_QUEUE -> broker`

### 撤单

`cancel_order -> om_order_requests(cancel) -> om_orders / om_broker_orders state update -> STOCK_ORDER_QUEUE -> broker`

### XT order callback

`XT order callback -> normalize_xt_order_report -> OrderTrackingService.ingest_order_report_with_meta -> om_orders / om_broker_orders / om_order_events`

### XT trade callback

`XT trade callback -> normalize_xt_trade_report -> OrderTrackingService.ingest_trade_report_with_meta -> om_execution_fills / om_trade_facts / om_broker_orders aggregate refresh -> om_position_entries / om_entry_slices / om_exit_allocations -> stock_fills_compat mirror sync`

当前写链规则：

- buy fill 默认按 `broker_order_key` 聚合成一个 `position_entry`
- 同一 broker order 的多笔 fill 会更新同一个 entry，而不是继续生成多条 entry
- sell fill 先扣减 `entry_slices`，再写 `exit_allocations`
- legacy `buy_lot / lot_slice / sell_allocation` 仍同步写入，供迁移期兼容链使用

### 自动平账

`xt_positions delta -> om_reconciliation_gaps -> stable observation -> om_reconciliation_resolutions -> auto_open_entry / auto_close_allocation`

自动平账不再伪造成 fake order / fake trade。收敛结果直接体现在：

- `auto_open_entry`
- `auto_close_allocation`
- `board_lot_rejected`
- `matched_execution_fill`

### 手工导入

`manual import/reset -> om_trade_facts -> om_position_entries / om_entry_slices -> stock_fills_compat mirror sync`

手工入口当前也强制执行 `100` 股整数倍校验。

## Board Lot 规则

系统当前把普通 A 股 `100` 股整数倍视为硬约束：

- odd-lot XT 回报会写 `om_execution_fills / om_trade_facts` 审计事实
- odd-lot 不会生成 `position_entry / entry_slice / exit_allocation`
- odd-lot 会写入 `om_ingest_rejections.reason_code=non_board_lot_quantity`
- 手工导入与手工 reset 直接拒绝 odd-lot 数量

## 读模型口径

- `/api/order-management/orders`
  - 订单列表与详情继续围绕 `internal_order_id` 展示
  - 详情中成交、券商订单聚合和运行态说明都来自 V2 账本
- `/api/order-management/stoploss/bind`
  - 当前只绑定 `entry_id`
- `/api/stock_fills`
  - 名称仍保留给旧页面/脚本
  - 底层优先读 `om_position_entries + om_entry_slices`
  - `freshquant.stock_fills_compat` 仅作为兼容镜像兜底

## 页面语义

- `/order-management`
  - 继续展示 request / order / event / trade 主线
  - 订单详情中的成交解释已经基于 `broker_order + execution_fill`
- `/subject-management`
  - 止损对象已经是 `entry`
- `/tpsl`
  - “单笔止损”实际是 `entry stoploss`
- `/kline-slim`
  - 标的设置中的止损对象也是 `entry`
- `/position-management`
  - 不再对比 `stock_fills` 仓位真值，只展示 `券商仓位 / 账本仓位 / 对账状态`

## 部署

- 改动 `freshquant/order_management/**` 后：
  - 重建 API Server
  - 重启 `xt_account_sync.worker`
  - 重启 `tpsl.tick_listener`
- 改动 `morningglory/fqwebui/**` 中订单相关页面后：
  - 重建 Web UI

## 排障

### submit 成功但 broker 没响应

- 查 `om_order_requests`
- 查 `om_orders`
- 查 `om_broker_orders`
- 查 Redis `STOCK_ORDER_QUEUE`

### 成交已到但页面没有持仓入口

- 查 `om_execution_fills`
- 查 `om_trade_facts`
- 查 `om_broker_orders.filled_quantity`
- 查 `om_position_entries / om_entry_slices`
- 若成交数量不是 `100` 股整数倍，再查 `om_ingest_rejections`

### 券商仓位与账本仓位不一致

- 先看 `xt_positions`
- 再看 `om_position_entries`
- 最后看 `om_reconciliation_gaps / om_reconciliation_resolutions`

### 旧接口显示碎片化持仓

- 查 `om_position_entries`
- 查 `freshquant.stock_fills_compat`
- 若 compat 镜像仍旧异常，再查 legacy `om_buy_lots`
