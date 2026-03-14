# 当前存储

## Mongo 数据库分层

### `freshquant`

基础业务库，当前主要承载：

- `xt_assets`
- `xt_positions`
- `xt_orders`
- `xt_trades`
- `stock_pre_pools`
- `stock_pools`
- `must_pool`
- 兼容历史的 `stock_fills`
- 订单投影数据库中的持仓/成交兼容视图

### `gantt` 或 `mongodb.gantt_db`

Gantt 与 Shouban30 读模型库，当前主要集合：

- `plate_reason_daily`
- `gantt_plate_daily`
- `gantt_stock_daily`
- `stock_hot_reason_daily`
- `shouban30_plates`
- `shouban30_stocks`

### `freshquant_order_management`

订单管理主事实库，当前主要集合：

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
- TPSL 相关集合
  - `om_takeprofit_profiles`
  - `om_takeprofit_states`
  - `om_exit_trigger_events`

### `freshquant_position_management`

仓位门禁状态库，当前主要集合：

- `pm_configs`
- `pm_credit_asset_snapshots`
- `pm_current_state`
- `pm_strategy_decisions`

### `fq_memory`

全局记忆热库，面向 `Symphony` / `Global Stewardship` / 自由 Codex 会话保存旁路摘要，当前主要集合：

- `task_state`
- `task_events`
- `deploy_runs`
- `health_results`
- `knowledge_items`
- `module_status`
- `context_packs`

### `quantaxis`

由 `DBQuantAxis` / `DBQA` 访问的历史行情库，供 XTData consumer 与 Kline 视图读取分钟/日线历史。

## 主事实与投影边界

- 主交易事实在订单管理库中，不在旧 `xt_orders/xt_trades` 集合中。
- `xt_orders / xt_trades / xt_positions / xt_assets` 是外部回报与当前账户视角事实，不是内部订单请求事实。
- `stock_pre_pools / stock_pools / must_pool` 是策略与页面共享的工作区/订阅范围集合。
- Gantt/Shouban30 集合是只读视图与筛选结果，不参与订单账本。
- `fq_memory` 是 agent 旁路上下文库，不参与交易链、订单账本或正式运行真值。
- Shouban30 当前把 `stock_pre_pools.extra.shouban30_order` 与 `stock_pools.extra.shouban30_order` 作为页面列表顺序和 `.blk` 输出顺序真值；历史 `stock_pools` 记录缺失该字段时，读取顺序兼容回退到旧 `datetime desc`。

## Redis 当前角色

- XTData tick 队列
  - `REDIS_TICK_QUEUE_PREFIX:<shard>`
- XTData bar 队列
  - `REDIS_QUEUE_PREFIX:<shard>`
- 订单提交队列
  - `STOCK_ORDER_QUEUE`
- 冷却锁 / 节流键
  - `buy:<code>`
  - `sell:<code>`
  - `fq:xtrade:last_new_order_time`
- Kline / 分钟结构缓存
  - `get_redis_cache_key(symbol, period)`
- TPSL 冷却锁
  - Redis 或内存 fallback

## 读写关系

- XTData producer 写 Redis tick 队列。
- XTData consumer 读 Redis bar 队列，写 QuantAxis 风格实时缓存与 Redis cache。
- Guardian 读 `xt_positions`、`must_pool`、Guardian grid 集合，写订单请求。
- Position worker 读 XT 资产/持仓，写 `pm_*` 集合。
- Order submit 写 `om_order_requests`、`om_orders`、`om_order_events`，并把 broker payload 推到 Redis。
- XT 回报 ingest 写 `om_trade_facts`、`om_buy_lots`、`om_lot_slices`、`om_sell_allocations` 等。
- TPSL 读 `xt_positions` 与 `om_*`，写 `om_takeprofit_*` / `om_exit_trigger_events`。
- Gantt/Shouban30 API 读 gantt 库，并在工作区操作时写 `stock_pre_pools`、`stock_pools`；`must_pool` 仍由独立接口或页面外链路维护。

## 当前排障原则

- 查交易链问题时，先看 `om_*`，再看 `xt_*`，最后才回头看旧兼容集合。
- 查前端列表问题时，先确认 Mongo 读模型集合是否有数据，再看 API，再看页面。
- 查 TPSL 问题时，同时核对 `xt_positions` 的可用数量与 `om_takeprofit_states` 的状态。
