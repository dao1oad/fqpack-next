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
  - `/api/order-management/orders`
  - `/api/order-management/orders/<internal_order_id>`
  - `/api/order-management/stats`
  - `/api/order-management/buy-lots/<buy_lot_id>`
  - `/api/order-management/stoploss/bind`
- CLI
  - `python -m freshquant.cli om-order submit ...`
  - `python -m freshquant.cli om-order cancel ...`
- 策略入口
  - `freshquant.order_management.submit.guardian.submit_guardian_order`
- 核心服务
  - `freshquant.order_management.submit.service.OrderSubmitService`
  - `freshquant.order_management.read_service.OrderManagementReadService`

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

`submit / ingest / reconcile` 当前要求在 unexpected exception 时，直接在当前 runtime node 发 `status=error`、`reason_code=unexpected_exception` 的 trace step，而不是只记日志或靠下游兜底。这样全局 Trace 会停在真实失败节点，并保留 `payload.error_type/error_message`。

### 撤单

`cancel_order -> internal_order_id 校验 -> cancel queue payload -> broker`

撤单链当前也会把 `cancel_tracking_create -> cancel_queue_payload_build` 写入 `order_submit` runtime event；如果撤单队列入列失败，会直接在 `cancel_queue_payload_build` 发出异常 step。

### 回报

`XT order/trade callback -> OrderManagementXtIngestService -> om_orders / om_trade_facts / om_buy_lots / om_sell_allocations -> projection update`

`om_trade_facts` 当前会保留 `trade_time` 以及同一笔成交对应的 `date/time`；旧的 `external_inferred` 历史 lot / slice 如果缺少 `date/time`，投影读取时会按已有 `trade_time` 回填，避免 Guardian 和持仓视图在消费投影时拿到 `None/None`。

如果 XT callback 在进入标准 ingest 前就抛异常，`try_ingest_xt_trade_dict` / `try_ingest_xt_order_dict` 现在也会在 `xt_report_ingest.report_receive` 发出异常 step，不再只留下普通日志后直接吞掉。

### 对账

`ExternalOrderReconcileService -> internal_match -> externalize -> projection_update`

### 账本查询

`GET /api/order-management/orders* -> OrderManagementReadService -> om_orders + om_order_requests + om_order_events + om_trade_facts -> /order-management`

## 页面组织

`/order-management` 当前已切到统一的 workbench density 语法：

- 顶部使用紧凑 toolbar 承载标题、筛选、摘要与主操作
- 订单统计改为摘要条，不再使用独立大统计卡
- 主体保持左侧订单列表、右侧订单详情的同屏并排结构
- 详情区继续展示主记录、请求信息、状态流转、成交回报，但统一使用紧凑 panel 与标签语法

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
- `morningglory/fqwebui` 改动后要重建 `fqwebui`
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
- 信用账户卖出若使用自动 `credit_trade_mode` / 自动 `price_mode`，还要检查 credit detail 与连续竞价状态是否可正常读取；当前读取失败会直接报错，不再静默退化为默认卖出模式或限价单

### 成交回来了但前端无持仓

- 检查 `om_trade_facts`
- 检查 `om_buy_lots` 和投影是否更新
- 检查 reconcile 是否把外部成交匹配成内部单
- 如果是 external reconcile 落账，还要检查 lot amount / grid interval 是否可解析；当前解析失败会直接报错，不再静默使用 `3000 / 1.03`

### 卖出后 lot 不对

- 检查 `om_sell_allocations`
- 检查 `om_lot_slices`
- 检查 ingest 是否识别到正确的买入 lot

### 订单页列表有单但详情缺 request / event / trade

- 检查 `om_order_requests` 是否存在对应 `request_id`
- 检查 `om_order_events` 是否写入对应 `internal_order_id`
- 检查 `om_trade_facts` 是否携带对应 `internal_order_id`
