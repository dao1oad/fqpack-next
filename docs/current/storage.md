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
- `om_execution_history_archive`
  - 持仓复盘的规范化成交档案；`execution_key` 使用
    `broker_trade_id + symbol + side + trade_time + quantity + price`
    六元身份，`archive_key` 再叠加不可逆账户分区，防止跨账户覆盖
  - 请求、订单、fill、trade fact 关联以候选数组保存，不用单值覆盖冲突证据
  - OM 与 XT 的 `broker_trade_id + symbol + time + quantity + price`
    相同但 `side` 相反时，XT/archive 保持 canonical；OM 只以
    `canonical_conflict=side_mismatch_with_xt` 归档为质量证据
- `position_review_evidence_archive`
  - 持仓复盘的不可变证据档案；保存 `xt_trade / order_request / order /
    execution_fill / trade_fact / position_entry / entry_slice /
    exit_allocation` 的业务 payload
  - 使用 `evidence_type + account_partition + 稳定业务身份` 幂等写入
  - 顶层、候选快照和 payload 均不持久化原始 `account_id`；只保留不可逆
    `account_partition`

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

### `freshquant_clx_backtest`

CLX 回测专用派生库，源行情库在这条链上保持只读：

- 控制面
  - `runs`
  - `jobs`
  - `workers`
  - `progress_events`
  - `freeze_records`
- 血缘与审计
  - `manifests`
  - `audit_findings`
  - `model_registry`
- 排行与组合
  - `combo_definitions`
  - `combo_metrics`
  - `model_heatmap`
  - `portfolio_summaries`
  - `portfolio_equity`
  - `portfolio_trades`
  - `combo_signals`

该库是已验证 artifact 的查询投影。immutable projector 对相同身份执行幂等 upsert；同一 `_id` 的不同内容会被判为冲突，而不是覆盖既有研究事实。

## CLX Artifact 存储

- 宿主机默认根目录：`D:/fqpack/runtime/clx-backtest`
- 容器路径：`/opt/clx-backtest`
- API：只读挂载
- `fq_clx_backtest_worker`：可写挂载

主要目录为 `snapshots / events / rankings / holdout / holdout-ledger / holdout-ledgers / portfolios / runs / exports`。其中全量链使用 `holdout-ledger`，API worker 的 run 级链使用 `holdout-ledgers/<run_id>`。每层用 `manifest.json + manifest.sha256 + 文件哈希 + 上游 lineage` 定义身份；HOLDOUT persistent ledger 与访问审计按长期单次揭示证据保留，与普通缓存采用不同清理口径。

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
- 历史持仓复盘真值
  - 当前运行态仍优先读取 `xt_trades` 与当前 OM 账本
  - `om_execution_history_archive / position_review_evidence_archive`
    提供不随 positions-only initialize 或 destructive rebuild 消失的历史只读证据
  - 历史档案不参与当前仓位重建，也不反向改写 `xt_positions`
  - `account_partition` 是账户号的不可逆摘要；API 不返回原始账户号

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
- initialize / order-ledger rebuild
  - 替换 `xt_trades` 或 purge OM 账本前，先幂等写入两个持仓复盘档案
  - 归档失败时中止清理；两个档案集合不在 order-ledger purge 边界内
- `PositionReviewRepository`
  - 合并当前 `xt_trades / om_*` 与两个历史档案
  - 同一账户内按成交六元身份去重，不同已知账户分区保留为不同成交
  - 无账户 OM 证据只在唯一账户匹配时归并；多账户候选保持歧义证据，
    不额外制造第三笔 canonical execution

## 当前排障原则

- 查当前仓位先看 `xt_positions`
- 查账本解释先看 `om_position_entries`
- 查执行事实先看 `om_broker_orders / om_execution_fills`
- 查 odd-lot 或拒绝写入先看 `om_ingest_rejections`
- 查 legacy 镜像问题最后再看 `stock_fills_compat / om_buy_lots`
- 查全历史持仓复盘缺失先看
  `om_execution_history_archive / position_review_evidence_archive`

## Trade Calendar Cache

- `freshquant.trade_calendar_cache` stores the persisted A-share trade calendar snapshot used by FreshQuant and Dagster.
- The current document key is `market=cn_a`, `source=sina`, with `_id=cn_a:sina`.
- `trade_dates` are stored as ISO date strings, with `min_trade_date`, `max_trade_date`, `date_count`, `checksum`, `last_success_at`, `last_error_*`, and `fallback_hits` for audit.
- Docker API and Dagster share a disk snapshot volume at `FQ_TRADE_CALENDAR_STATE_DIR`; the default file is `cn_a_sina.json` and is rewritten only after a successful live refresh.
- Redis is not the durable truth for the trade calendar; Mongo is the primary last-known-good source and the disk snapshot is the cold fallback when the live Sina/AkShare request or Mongo read path fails.
