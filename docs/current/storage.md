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
- `dagster_pipeline_markers`
  - 盘后链 ready marker；CLX 输入为 `stock_postclose_ready / etf_postclose_ready`，finalizer 成功后写 `clx_daily_selection_ready`
  - CLX ready marker 额外保存 `generation_id / generation_order / publication_id`；generation order 是规范 UTC 可排序键，同 publication id 重试幂等，较旧 generation 不能覆盖较新 marker

### `freshquant_order_management`

订单管理库，当前主集合：

- `om_order_requests`
- `om_orders`
- `om_broker_orders`
  - `broker_order_key` 使用账户与交易日隔离的 canonical identity：优先
    `account_id + trading_day + order_sysid`，否则使用
    `account_id + trading_day + symbol + side + broker_order_id`
  - owner 固定为 `internal_order_id / request_id / broker_correlation_token`；
    `execution_fence` 阻止首笔成交后继续 promotion，`aggregate_revision` 用于成交
    聚合 compare-and-set
- `om_order_events`
- `om_execution_fills`
  - `execution_identity` 对
    `account_id + trading_day + symbol + side + broker_trade_id` 做稳定摘要并唯一
    幂等写入
- `om_trade_facts`
  - 与 `om_execution_fills` 共用同一 `execution_identity` 幂等边界
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

### `freshquant_clx_daily_selection`

- `partition_attempts`
  - stock/ETF 各自保存 `selection_key / attempt_no / marker_snapshot_hash / status / claim_owner / claim_token / lease_expires_at / error`
  - 状态为 `scheduled / running / committing / completed / failed / claim_expired / upstream_drift`；running 与 committing 的提交权由 owner/token fencing，lease 到期保留审计并创建新 attempt
- `partitions`
  - completed partition 的不可变头；`selection_key` 唯一，相同 key 只接受相同 `content_hash`
- `memberships`
  - `partition_id + asset_type + symbol + model_key + trigger_date` 的模型触发事实
- `snapshots`
  - partition 内标的级模型/条件摘要；`partition_id + asset_type + symbol` 唯一
- `model_stats`
  - partition 内按模型聚合的本资产统计
- `finalization_attempts`
  - `(batch_id, attempt_no)` 唯一；保存 `finalization_attempt_id / trade_date / partition_ids / material_hash / claim_owner / claim_token / lease_expires_at`
  - 状态为 `scheduled / running / failed / completed / claim_expired`；每次 dispatch/retry 对应独立 attempt 与 Dagster run key
- `batch_statuses`
  - 同交易日 stock/ETF join 状态；保存 partial，final 内容按 `content_hash` 保持不可变
  - publication 独立保存 `status / attempt_count / claim_owner / claim_token / last_claim_owner / last_attempt_at / lease_expires_at / published_at / last_error`
  - publication 身份保存 `generation_id / generation_order / publication_id`；迟到旧 generation 的 CAS 拒绝以 `last_error.code=stale_publication` 留痕，batch 保持 failed

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
- 历史持仓复盘真值
  - 当前运行态仍优先读取 `xt_trades` 与当前 OM 账本
  - `om_execution_history_archive / position_review_evidence_archive`
    提供不随 positions-only initialize 或 destructive rebuild 消失的历史只读证据
  - 历史档案不参与当前仓位重建，也不反向改写 `xt_positions`
  - `account_partition` 是账户号的不可逆摘要；API 不返回原始账户号
- CLX partition 计算真值
  - `freshquant_clx_daily_selection.partitions`
  - `memberships / snapshots / model_stats` 只通过 `partition_id` 归属不可变输出
- CLX finalizer dispatch 真值
  - `freshquant_clx_daily_selection.finalization_attempts` 固定一次 dispatch 的 trade date、batch id 和两个不可变 partition id
- CLX 默认完整批次真值
  - `batch_statuses.is_final=true` 且 `publication.status in [published, not_required]`
  - partial 与 publication `pending/publishing/failed` 只表达中间态，不替代正式发布或默认完整结果

## 当前兼容边界

- `om_trade_facts`
  - 仍保留给迁移期读链和排障
- `om_buy_lots / om_lot_slices / om_sell_allocations`
  - 仍保留给 legacy 兼容
- `stock_fills_compat`
  - 当前只做镜像/adapter，不再定义运行期仓位真值
- `stock_fills`
  - 仅 raw 审计与最终兜底

## 订单身份索引与并发边界

- `om_orders.internal_order_id` 唯一
- 非空 `om_orders.broker_correlation_token` 唯一，格式固定为
  `FQOM + 20 hex` 共 24 字符
- 非空 `om_broker_orders.broker_order_key` 唯一
- 非空 `om_execution_fills.execution_identity` 与
  `om_trade_facts.execution_identity` 分别唯一
- existing broker owner claim 的重领/合并不覆盖既有订单状态或成交聚合；状态更新
  保持 owner 不变，成交聚合以 fence/CAS 收敛，避免 stale 回报覆盖较新成交事实

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
  - `xt_positions` 写入采用滞回语义：缺失标的经 `sync_missing_count / sync_last_seen_at`
    连续确认后才驱逐，空快照守卫保留存量；reconcile 使用滞回后的有效持仓视图，
    避免 XT 瞬时部分返回导致持仓被清空或触发虚假 sell gap
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
- `ClxDailySelectionService.plan_partition / execute_partition`
  - 只读本资产 ready marker，写本侧 `partition_attempts`
  - 使用 scheduled/running/committing owner-token claim lease 和 compare-and-set；过期 attempt 标为 `claim_expired` 后只重派本侧
  - 计算前后发现 marker hash 漂移时只更新本侧 attempt，不写 partition 输出
  - 成功提交由同一 owner/token fencing，幂等写 `memberships / snapshots / model_stats / partitions`
- 三个 CLX Dagster sensor
  - newest-first 扫描最近 5 个已完成交易日；项目时区当天只在 `15:05` 后纳入，交易日来自交易日历
  - 每 tick 最多返回一个 RunRequest；marker 缺失或 `reuse/wait` 继续旧日，`active` 停止，`run` 返回
- `ClxDailySelectionService.plan_finalization / execute_finalization`
  - 当前 marker 缺失时返回 waiting，不复用旧 generation；双侧未齐时只更新 partial `batch_statuses`
  - 双侧完成后写 `finalization_attempts`，job 按 attempt id 读取并严格校验持久化 trade date、batch id、partition ids 与 Dagster tags
  - marker/partition generation 漂移时 attempt 失败，不发布旧 failed/pending final
  - 双侧合同一致时写不可变 final 内容，并由 owner-token publication claim 独立发布 `clx_daily_selection_ready`
  - ready marker 写入再按规范 UTC `generation_order` 与不可变 `publication_id` 做 CAS；同 id 重试幂等，迟到旧 generation 显式失败且不能把旧 batch 标为 published

## 当前排障原则

- 查当前仓位先看 `xt_positions`
- 查账本解释先看 `om_position_entries`
- 查执行事实先看 `om_broker_orders / om_execution_fills`
- 查 odd-lot 或拒绝写入先看 `om_ingest_rejections`
- 查 legacy 镜像问题最后再看 `stock_fills_compat / om_buy_lots`
- 查全历史持仓复盘缺失先看
  `om_execution_history_archive / position_review_evidence_archive`
- 查 CLX 单侧重试先看 `partition_attempts`，不要删除或重算另一侧 completed partition
- 查 CLX finalizer 重试先看 `finalization_attempts` 的 attempt/status/lease 与 Dagster tags，不复用失败 dispatch 的 run key
- 查 CLX 页面默认批次同时看 `batch_statuses.is_final` 与 `publication.status`；只有 `published/not_required` 是默认完整结果
- 查 CLX 输入漂移同时比对 `dagster_pipeline_markers` 与 attempt 中冻结的 `marker_snapshot_hash`

## Trade Calendar Cache

- `freshquant.trade_calendar_cache` stores the persisted A-share trade calendar snapshot used by FreshQuant and Dagster.
- The current document key is `market=cn_a`, `source=sina`, with `_id=cn_a:sina`.
- `trade_dates` are stored as ISO date strings, with `min_trade_date`, `max_trade_date`, `date_count`, `checksum`, `last_success_at`, `last_error_*`, and `fallback_hits` for audit.
- Docker API and Dagster share a disk snapshot volume at `FQ_TRADE_CALENDAR_STATE_DIR`; the default file is `cn_a_sina.json` and is rewritten only after a successful live refresh.
- Redis is not the durable truth for the trade calendar; Mongo is the primary last-known-good source and the disk snapshot is the cold fallback when the live Sina/AkShare request or Mongo read path fails.
