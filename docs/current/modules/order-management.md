# 订单管理

## 职责

订单管理是当前交易链的事实层。它负责：

- 统一受理 API、CLI、Guardian、TPSL 等来源的提交请求。
- 生成内部 `request_id` / `internal_order_id`。
- 维护订单主账本与事件流。
- 向 broker / puppet gateway 发送队列消息。
- ingest XT 回报并生成买入 lot、卖出分配和兼容投影。
- 维护 `freshquant.stock_fills_compat`，把 Guardian 旧 `stock_fills` 语义镜像到当前 OM 投影上。
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
  - `python -m freshquant.cli stock.fill rebuild --code 000001`
  - `python -m freshquant.cli stock.fill rebuild --all`
  - `python -m freshquant.cli stock.fill compare --code 000001`
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
- XT account sync worker
- XT 回报 ingest
- Runtime Observability

## 数据流

### 下单

`submit_order -> intent normalize -> credit mode resolve -> tracking_create -> queue payload build -> STOCK_ORDER_QUEUE -> broker`

`submit / ingest / reconcile` 当前要求在 unexpected exception 时，直接在当前 runtime node 发 `status=error`、`reason_code=unexpected_exception` 的 trace step，而不是只记日志或靠下游兜底。这样全局 Trace 会停在真实失败节点，并保留 `payload.error_type/error_message`。

策略单若在下单前被仓位管理门禁拒绝，`OrderSubmitService` 当前会在 `credit_mode_resolve` 发出 `status=failed`、`reason_code=position_management_rejected` 的 runtime step，并继续向上抛 `PositionManagementRejectedError`。

### 撤单

`cancel_order -> internal_order_id 校验 -> cancel queue payload -> broker`

撤单链当前也会把 `cancel_tracking_create -> cancel_queue_payload_build` 写入 `order_submit` runtime event；如果撤单队列入列失败，会直接在 `cancel_queue_payload_build` 发出异常 step。

### 回报

`XT order/trade callback -> OrderManagementXtIngestService -> om_orders / om_trade_facts / om_buy_lots / om_sell_allocations -> stock_fills_compat sync -> projection update`

`XT account sync worker(query_stock_orders/query_stock_trades/query_stock_positions/query_credit_detail) -> 高频账户状态刷新 + 增量过滤 -> saveOrders/saveTrades/reconcile_account -> xt_* / om_* / external candidates`

其中 `credit_detail` 保持在主循环高频刷新，用于仓位管理门禁；`credit_subjects` 只在启动和每日计划时间做低频同步，不参与每轮增量补偿。

`om_trade_facts` 当前会保留 `trade_time` 以及同一笔成交对应的 `date/time`；旧的 `external_inferred` 历史 lot / slice 如果缺少 `date/time`，投影读取时会按已有 `trade_time` 回填，避免 Guardian 和持仓视图在消费投影时拿到 `None/None`。

当成交真正改变 open lots / open slices 时，XT ingest 会同步重建对应 symbol 的 `freshquant.stock_fills_compat`。这层镜像沿用 Guardian 旧 `stock_fills` 的“剩余买入 fill”语义，但真值仍来自 `om_buy_lots` / `om_lot_slices`。

如果 XT callback 在进入标准 ingest 前就抛异常，`try_ingest_xt_trade_dict` / `try_ingest_xt_order_dict` 现在也会在 `xt_report_ingest.report_receive` 发出异常 step，不再只留下普通日志后直接吞掉。

XT `order callback` 若只带 `broker_order_id` 且无法命中内部订单，当前会在归一化阶段直接忽略；外部单仍通过 `reconcile_trade_report` 或 `reconcile_account -> externalize` 正式落账。

### 对账

`ExternalOrderReconcileService -> internal_match -> externalize -> projection_update`

### 手工兼容镜像运维

- `python -m freshquant.cli stock.fill rebuild --code <symbol>`
  - 按当前 `om_buy_lots` 重建单标的 `stock_fills_compat`
- `python -m freshquant.cli stock.fill rebuild --all`
  - 全量重建所有有 open lots 或既有 compat 记录的标的
- `python -m freshquant.cli stock.fill compare --code <symbol>`
  - 对比 `om_buy_lots` 投影和 `stock_fills_compat` 聚合数量/调整后金额是否一致

### 账本查询

`GET /api/order-management/orders* -> OrderManagementReadService -> om_orders + om_order_requests + om_order_events + om_trade_facts -> /order-management`

## 页面组织

`/order-management` 当前已切到统一的 workbench density 语法：

- 顶部使用紧凑 toolbar 承载标题、筛选、摘要与主操作
- 订单统计改为摘要条，不再使用独立大统计卡
- 主体保持左侧订单列表、右侧订单详情的同屏并排结构；列表头统一使用中文语义，`标的代码` 按“代码 + 名称”双行展示，`更新时间` 紧跟在标的后，`价格 / 数量` 与成交 `价格` 统一保留三位小数
- `Internal Order / Request` 已从主列表移除，只在右侧详情里保留 `internal_order_id / request_id`
- 详情区继续展示主记录、请求信息、状态流转、成交回报，但统一使用紧凑 panel 与标签语法
- `订单摘要` 与下方列表 grid 当前明确分成独立 stacking context，避免表头或列表层覆盖摘要区

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

兼容镜像集合：

- `freshquant.stock_fills_compat`
  - 由 OM 投影派生，供 Guardian / TPSL / 旧读接口复用旧 `stock_fills` 语义
- 原始 `freshquant.stock_fills`
  - 仅保留历史 raw 记录、人工审计和最终兜底，不再作为当前兼容镜像真值

## 配置

- `order_management.mongo_database`
- `order_management.projection_database`
- broker `observe_only`
- account type / credit mode

`observe_only` 语义当前只是不真正向 broker 发单/撤单；它不会停掉 broker 的 XT 连接、callback ingest，也不会停掉 `xt_account_sync.worker` 的增量补偿查询。

## 部署/运行

- 路由改动至少重建 `fq_apiserver`
- `morningglory/fqwebui` 改动后要重建 `fqwebui`
- submit / ingest / reconcile 逻辑改动时，要同步重启 `fqnext_xtquant_broker` 与 `fqnext_xt_account_sync_worker`
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
- 检查 `freshquant.stock_fills_compat` 是否已随持仓结构变化同步
- 检查 `xt_positions` 最近一次刷新时间与 `fqnext_xt_account_sync_worker` 是否正常运行
- 检查 reconcile 是否把外部成交匹配成内部单
- 如果是 external reconcile 落账，还要检查 lot amount / grid interval 是否可解析；当前解析失败会直接报错，不再静默使用 `3000 / 1.03`

### 卖出后 lot 不对

- 检查 `om_sell_allocations`
- 检查 `om_lot_slices`
- 检查 ingest 是否识别到正确的买入 lot
- 如果 Guardian / TPSL 侧仍看到旧 lot 视图，再检查 `stock.fill compare --code <symbol>` 是否一致

### 订单页列表有单但详情缺 request / event / trade

- 检查 `om_order_requests` 是否存在对应 `request_id`
- 检查 `om_order_events` 是否写入对应 `internal_order_id`
- 检查 `om_trade_facts` 是否携带对应 `internal_order_id`
