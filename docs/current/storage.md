# 当前存储

## Mongo 数据库分层

### `freshquant`

基础业务库，主要包含：

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
  - raw legacy fill 集合
- `stock_fills_compat`
  - legacy mirror，当前由 open entry 视图投影生成

### `freshquant_order_management`

订单管理库，当前主集合：

- `om_order_requests`
- `om_orders`
- `om_broker_orders`
- `om_order_events`
- `om_execution_fills`
- `om_trade_facts`
- `om_position_entries`
- `om_entry_slices`
- `om_exit_allocations`
- `om_reconciliation_gaps`
- `om_reconciliation_resolutions`
- `om_entry_stoploss_bindings`
- `om_ingest_rejections`
- `om_takeprofit_profiles`
- `om_takeprofit_states`
- `om_exit_trigger_events`
- `om_credit_subjects`

当前仍保留的 legacy 集合：

- `om_buy_lots`
- `om_lot_slices`
- `om_sell_allocations`
- `om_external_candidates`
- `om_stoploss_bindings`

### `freshquant_position_management`

- `pm_configs`
- `pm_credit_asset_snapshots`
- `pm_current_state`
- `pm_strategy_decisions`
- `pm_symbol_position_snapshots`

### `gantt`

- `plate_reason_daily`
- `gantt_plate_daily`
- `gantt_stock_daily`
- `stock_hot_reason_daily`
- `shouban30_plates`
- `shouban30_stocks`

### `fqscreening`

- `daily_screening_runs`
- `daily_screening_memberships`
- `daily_screening_stock_snapshots`

### `fq_memory`

- `task_state`
- `task_events`
- `deploy_runs`
- `health_results`
- `knowledge_items`
- `module_status`
- `context_packs`

## 当前真值边界

- 当前券商仓位真值
  - `xt_positions`
- 当前执行事实真值
  - `om_broker_orders`
  - `om_execution_fills`
- 当前持仓解释真值
  - `om_position_entries`
  - `om_entry_slices`
  - `om_exit_allocations`
- 当前自动平账真值
  - `om_reconciliation_gaps`
  - `om_reconciliation_resolutions`
  - `om_ingest_rejections`

## 当前兼容边界

- `om_trade_facts`
  - 仍保留给迁移期读链和排障
- `om_buy_lots / om_lot_slices / om_sell_allocations`
  - 仍保留给 legacy 兼容
- `stock_fills_compat`
  - 当前只做镜像/adapter，不再定义运行期仓位真值
- `stock_fills`
  - 仅 raw 审计与最终兜底

## Redis 当前角色

- XTData tick 队列
- XTData bar 队列
- `STOCK_ORDER_QUEUE`
- 冷却锁 / 节流键
- Kline / 分钟结构缓存
- TPSL 冷却锁

## 当前读写关系

- `xt_account_sync.worker`
  - 写 `xt_*`
  - 写 `pm_*`
  - 增量触发订单回报 ingest
- `OrderSubmitService`
  - 写 `om_order_requests / om_orders / om_broker_orders / om_order_events`
- `OrderManagementXtIngestService`
  - 写 `om_execution_fills / om_trade_facts / om_broker_orders`
  - 写 `om_position_entries / om_entry_slices / om_exit_allocations`
  - 写 `om_ingest_rejections`
  - 同步 legacy `buy_lot` 链与 `stock_fills_compat`
- `ExternalOrderReconcileService`
  - 写 `om_reconciliation_gaps / om_reconciliation_resolutions`
  - 必要时自动写 `position_entries / exit_allocations`
- `TpslService`
  - 读 `xt_positions` 与 `om_*`
  - 写 `om_takeprofit_* / om_exit_trigger_events`

## 当前排障原则

- 查当前仓位先看 `xt_positions`
- 查账本解释先看 `om_position_entries`
- 查执行事实先看 `om_broker_orders / om_execution_fills`
- 查 odd-lot 或拒绝写入先看 `om_ingest_rejections`
- 查 legacy 镜像问题最后再看 `stock_fills_compat / om_buy_lots`
