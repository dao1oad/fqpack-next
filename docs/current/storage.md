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
- `stock_signals`
- `realtime_screen_multi_period`
- `stock_fills`
  - 历史原始兼容集合，仅保留人工审计、旧脚本和兜底排障
- `stock_fills_compat`
  - 由 `om_buy_lots` 投影生成的兼容镜像，供 Guardian / TPSL / 旧读接口使用

### `gantt` 或 `mongodb.gantt_db`

Gantt 与 Shouban30 读模型库，当前主要集合：

- `plate_reason_daily`
- `gantt_plate_daily`
- `gantt_stock_daily`
- `stock_hot_reason_daily`
- `shouban30_plates`
- `shouban30_stocks`

### `fqscreening` 或 `mongodb.screening_db`

每日选股正式结果库，当前主要集合：

- `daily_screening_runs`
- `daily_screening_memberships`
- `daily_screening_stock_snapshots`

### `freshquant_order_management`

订单管理主事实库，当前已建立的 V2 主账本集合边界：

- `om_order_requests`
- `om_broker_orders`
- `om_order_events`
- `om_execution_fills`
- `om_reconciliation_gaps`
- `om_reconciliation_resolutions`
- `om_position_entries`
- `om_entry_slices`
- `om_exit_allocations`
- `om_entry_stoploss_bindings`
- `om_ingest_rejections`
- `om_credit_subjects`
- TPSL 相关集合
  - `om_takeprofit_profiles`
  - `om_takeprofit_states`
  - `om_exit_trigger_events`

迁移期 legacy 集合：

- `om_orders`
- `om_trade_facts`
- `om_buy_lots`
- `om_lot_slices`
- `om_sell_allocations`
- `om_external_candidates`
- `om_stoploss_bindings`

### `freshquant_position_management`

仓位门禁状态库，当前主要集合：

- `pm_configs`
- `pm_credit_asset_snapshots`
- `pm_current_state`
- `pm_strategy_decisions`

### `fq_memory`

全局记忆热库，面向自由 Codex 会话与正式 deploy 收口保存旁路摘要，当前主要集合：

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
- `stock_fills_compat` 目前仍保留历史兼容角色，但不属于 V2 主账本真值；当前仍服务旧接口与兼容读链。
- 原始 `stock_fills` 仍保留，但只作为历史 raw 集合、人工审计与最终兜底，不再承担当前持仓镜像真值。
- `stock_pre_pools / stock_pools / must_pool` 是策略与页面共享的工作区/订阅范围集合，不再承担每日选股正式结果真值。
- `must_pool` 当前仍按 `code` 唯一保留一条主记录，并通过 `manual_category / sources / categories / memberships` 兼容保留来源、分类与上下文；顶层 `category` 只是兼容摘要字段。
- 每日选股正式 run、membership 和股票快照都落在 `fqscreening`；页面只在显式动作时复制结果到 `stock_pre_pools`。
- 当每日选股复制结果到 `stock_pre_pools` 时，当前仍使用顶层 `remark` 保持来源隔离，正式值包括：
  - `daily-screening:clxs`
  - `daily-screening:chanlun`
- `stock_signals` 是 Guardian event monitor 写入的实时信号日志。
- `realtime_screen_multi_period` 是启用 CLX 能力的 XTData consumer 写入的多周期模型信号读模型。
- Gantt/Shouban30 集合是只读视图与筛选结果，不参与订单账本。
- `daily_screening_runs / memberships / stock_snapshots` 是每日选股正式读模型，不参与订单账本。
- `fq_memory` 是 agent 旁路上下文库，不参与交易链、订单账本或正式运行真值。
- Shouban30 当前把 `stock_pre_pools.workspace_order`、`stock_pools.extra.shouban30_order` 与 `must_pool.workspace_order_hint` 分别作为三个共享池的页面或 `.blk` 输出顺序真值；`stock_pool` 历史记录缺失顺序字段时回退到旧 `datetime desc`，`must_pool` 缺失时回退到 `updated_at / created_at / datetime desc`。

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
- XTData consumer 在 `guardian_and_clx_15_30` 模式下额外写 `realtime_screen_multi_period`。
- 兼容旧值 `clx_15_30`，运行时会归一到联合模式。
- Guardian event monitor 写 `stock_signals`。
- Guardian 读 `xt_positions`、`must_pool`、Guardian grid 集合，写订单请求。
- XT account sync worker 读 XT 资产/持仓/成交/委托，写 `xt_*`、`pm_*` 与 `om_credit_subjects`。
- Order submit 当前运行主写仍是 `om_order_requests`、`om_orders`、`om_order_events`；V2 仓储边界已预留 `om_broker_orders` 供后续切换。
- XT 回报 ingest 当前运行主写仍是 `om_trade_facts`、`om_buy_lots`、`om_lot_slices`、`om_sell_allocations`；V2 仓储边界已预留 `om_execution_fills`、`om_position_entries`、`om_entry_slices`、`om_exit_allocations`、`om_reconciliation_*` 与 `om_ingest_rejections`。
- `stock_fills_compat` 当前仍由 legacy lot 链同步重建；V2 切换后再收口为 adapter 输出。
- TPSL 读 `xt_positions` 与 `om_*`，写 `om_takeprofit_*` / `om_exit_trigger_events`。
- Gantt/Shouban30 API 读 gantt 库，并在工作区操作时写 `stock_pre_pools`、`stock_pools`、`must_pool`；`stock_pool -> must_pool` 的单条/批量动作会显式写 `must_pool`，但不会改写 `stock_pool` 顺序；三个共享池各自的显式 `sync-to-tdx` 或 `clear` 都会完整覆盖 `30RYZT.blk`。
- 每日选股 API 直接调用 `CLXS / chanlun / shouban30_agg90 / market_flags`，把正式 run 和查询快照写入 `fqscreening`；手动工作区动作才会写 `stock_pre_pools`。

## 当前排障原则

- 当前排障若看运行主写链，仍先看 `om_orders / om_trade_facts / om_buy_lots / om_lot_slices / om_sell_allocations`；核对 V2 边界或迁移期读模型时，再看 `om_broker_orders / om_execution_fills / om_position_entries / om_entry_slices / om_exit_allocations / om_reconciliation_*`。
- 查当前券商仓位真值时，先看 `xt_positions`，再看 `pm_*` / 页面聚合结果，不要把 compat 镜像当 broker 真值。
- 查前端列表问题时，先确认 Mongo 读模型集合是否有数据，再看 API，再看页面。
- 查 TPSL 问题时，同时核对 `xt_positions` 的可用数量与 `om_takeprofit_states` 的状态。
