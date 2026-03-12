# 订单管理

## 职责

订单管理是当前交易链的事实层。它负责：

- 统一受理 API、CLI、Guardian、TPSL 等来源的提交请求。
- 生成内部 `request_id` / `internal_order_id`。
- 维护订单主账本与事件流。
- 向 broker / puppet gateway 发送队列消息。
- ingest XT 回报并生成买入 lot、卖出分配和兼容投影。
- 对账外部成交，处理“不是由内部请求发起”的外部单。

## 入口

- HTTP
  - `/api/order/submit`
  - `/api/order/cancel`
  - `/api/stock_order`
  - `/api/order-management/buy-lots/<buy_lot_id>`
  - `/api/order-management/stoploss/bind`
- CLI
  - `python -m freshquant.cli om-order submit ...`
  - `python -m freshquant.cli om-order cancel ...`
- 策略入口
  - `freshquant.order_management.submit.guardian.submit_guardian_order`
- 核心服务
  - `freshquant.order_management.submit.service.OrderSubmitService`

## 依赖

- Mongo
- Redis
- Position Management
- XT broker / puppet gateway
- XT 回报 ingest
- Runtime Observability

## 数据流

### 下单

`submit_order -> intent normalize -> credit mode resolve -> tracking_create -> queue payload build -> STOCK_ORDER_QUEUE -> broker`

### 撤单

`cancel_order -> internal_order_id 校验 -> cancel queue payload -> broker`

### 回报

`XT order/trade callback -> OrderManagementXtIngestService -> om_orders / om_trade_facts / om_buy_lots / om_sell_allocations -> projection update`

### 对账

`ExternalOrderReconcileService -> internal_match -> externalize -> projection_update`

## 存储

主事实集合：

- `om_order_requests`
- `om_orders`
- `om_order_events`
- `om_trade_facts`
- `om_buy_lots`
- `om_lot_slices`
- `om_sell_allocations`
- `om_external_candidates`
- `om_stoploss_bindings`
- `om_credit_subjects`

旧 `xt_orders / xt_trades` 属于外部回报视角，不替代 `om_*` 主事实。

## 配置

- `order_management.mongo_database`
- `order_management.projection_database`
- broker `observe_only`
- account type / credit mode

`observe_only` 语义是“只建内部账本和事件，不真正向 broker 发单”；排障时必须确认当前是否误开该模式。

## 部署/运行

- 路由改动至少重建 `fq_apiserver`
- submit / ingest / reconcile 逻辑改动时，要同步重启相关宿主机进程
- 交易链改动后至少验证一次：
  - submit
  - XT 回报 ingest
  - 投影更新

## 排障点

### submit 成功返回但不落库

- 检查 `om_order_requests`
- 检查 `om_orders`
- 检查 Mongo 连接与订单库名

### 已落库但 broker 没动作

- 检查 Redis `STOCK_ORDER_QUEUE`
- 检查 gateway 进程是否消费
- 检查是否误开 `observe_only`

### 成交回来了但前端无持仓

- 检查 `om_trade_facts`
- 检查 `om_buy_lots` 和投影是否更新
- 检查 reconcile 是否把外部成交匹配成内部单

### 卖出后 lot 不对

- 检查 `om_sell_allocations`
- 检查 `om_lot_slices`
- 检查 ingest 是否识别到正确的买入 lot
