# 当前接口

## HTTP API

统一入口：

```powershell
python -m freshquant.rear.api_server --port 5000
```

### `order`

- `/api/order/submit`
- `/api/order/cancel`
- `/api/stock_order`
- `/api/order-management/orders`
- `/api/order-management/orders/<internal_order_id>`
- `/api/order-management/entries/<entry_id>`
- `/api/order-management/stats`
- `/api/order-management/stoploss/bind`

当前已删除 `/api/order-management/buy-lots/<buy_lot_id>`。

### `position-management`

- `/api/position-management/dashboard`
- `/api/position-management/config`
- `/api/position-management/symbol-limits`
- `/api/position-management/symbol-limits/<symbol>`
- `/api/position-management/reconciliation`
- `/api/position-management/reconciliation/<symbol>`
- `/api/position-management/reconciliation-workspace/<symbol>`

### `position-review`

- `GET /api/position-review/summary`
- `GET /api/position-review/symbols`
- `GET /api/position-review/symbols/<symbol>`
- `GET /api/position-review/portfolio/summary`
- `GET /api/position-review/portfolio/series`（`period=day|week|month`，默认 `day`）
- `GET /api/position-review/portfolio/contributions`
- `GET /api/position-review/symbols/<symbol>/chart`
- `GET /api/position-review/events/<event_id>/conditions`

### `subject-management`

- `/api/subject-management/overview`
- `/api/subject-management/<symbol>`
- `/api/subject-management/<symbol>/must-pool`
- `/api/subject-management/<symbol>/guardian-buy-grid`

### `tpsl`

- `/api/tpsl/takeprofit/<symbol>`
- `/api/tpsl/takeprofit/<symbol>/tiers/<level>/enable`
- `/api/tpsl/takeprofit/<symbol>/tiers/<level>/disable`
- `/api/tpsl/takeprofit/<symbol>/rearm`
- `/api/tpsl/management/overview`
- `/api/tpsl/management/<symbol>`
- `/api/tpsl/history`
- `/api/tpsl/events`
- `/api/tpsl/batches/<batch_id>`

`/api/tpsl/history` 当前只按 `symbol / batch_id / entry_id` 过滤。

### `stock`

- `/api/stock_data`
- `/api/stock_data_v2`
- `/api/stock_data_chanlun_structure`
  - `/api/guardian_buy_grid_state`
  - `/api/get_stock_pools_list`
- `POST /api/pools/stock/sync-from-tdx`
  - `POST /api/pools/must/sync-from-tdx`
  - `must_pool` 同步从 `blocknew.cfg` 按显示名「待买」解析真实 BLK 文件名（如 `DM.blk`），解析失败回退 `待买.blk`
  - `/api/get_stock_pre_pools_list`
  - `/api/get_stock_must_pools_list`

### `gantt`

- `/api/gantt/plates`
- `/api/gantt/stocks`
- `/api/gantt/stocks/reasons`

### `clx-daily-selection`

- `GET /api/clx-daily-selection/health`
- `GET /api/clx-daily-selection/official`（当前 ready generation 的 pure-buy 正式结果，默认 `direction_mode=pure_buy`）
- `GET /api/clx-daily-selection/model-catalog`
- `GET /api/clx-daily-selection/batches`
- `GET /api/clx-daily-selection/batches/latest`
- `GET /api/clx-daily-selection/batches/<batch_id>/summary`
- `GET|POST /api/clx-daily-selection/batches/<batch_id>/results`
- `POST /api/clx-daily-selection/batches/<batch_id>/results/query`
- `POST /api/clx-daily-selection/batches/<batch_id>/results/sync-selected-to-tdx`（导出到 CLX_18）
- `GET /api/clx-daily-selection/batches/<batch_id>/results/<asset_type>/<symbol>`
- `GET /api/clx-daily-selection/batches/<batch_id>/statistics`
- `GET /api/clx-daily-selection/history/signals`

### `runtime`

- `/api/runtime/components`
- `/api/runtime/health/summary`
- `/api/runtime/traces`
- `/api/runtime/traces/<trace_id>`
- `/api/runtime/events`
- `/api/runtime/raw-files/files`
- `/api/runtime/raw-files/tail`

### `system-config`

- `/api/system-config/dashboard`
- `/api/system-config/bootstrap`
- `/api/system-config/settings`

## 当前接口语义

- `/api/order-management/stoploss/bind`
  - 当前只接受 `entry_id`
- `/api/subject-management/<symbol>`
  - 当前返回 `entries`
  - 不再返回 `buy_lots`
- `/api/tpsl/management/<symbol>`
  - 当前返回 `entries / entry_slices / reconciliation / history`
  - `entries` 内嵌 `stoploss`
- `/api/position-management/dashboard`
  - 当前返回 `state / rule_matrix / config / recent_decisions / symbol_position_limits`
  - 全局阈值编辑和最近决策都依赖该接口
- `/api/position-management/reconciliation`
  - 当前返回只读多视图一致性审计摘要
  - 包含 `summary.rule_counts / summary.reconciliation_state_counts / rows[].surface_values / rows[].rule_results / rows[].evidence_sections`
- `/api/position-management/reconciliation-workspace/<symbol>`
  - 当前返回 `/position-management` 右上统一排障工作区需要的 symbol 级对账 workspace
  - 包含 `detail / gaps / resolutions / rejections`
- `/api/position-review/summary`
  - 当前返回历史交易复盘的全局 `totals / verdict_counts / data_quality`
- `/api/position-review/symbols`
  - 当前返回所有存在可信历史成交的标的，包含当前持仓与已清仓标的
  - 每行包含首末成交时间、请求与逐笔成交数量、买卖数量与金额、复盘计数、汇总结论和可判定订单合规率
- `/api/position-review/symbols/<symbol>`
  - 当前返回单标的 `summary / executions / charts / reviews / data_quality`
  - `executions` 是按账户分区稳定标识的 canonical 逐笔成交台账；同账户迟到或更正的 XT 真值不会与旧 OM/XT 记录重复计数
  - 只读当前库：合并 `freshquant.xt_trades` 与当前 OM 账本
    （`om_order_requests / om_orders / om_execution_fills / om_trade_facts /
    om_position_entries / om_entry_slices / om_exit_allocations`）；
    `om_execution_history_archive / position_review_evidence_archive` 仅作为
    重建前历史留存的写入侧，复盘读模型不再读取归档
  - `charts` 包含 `cumulative_quantity / traded_amount / trade_price / verdict_distribution / request_quantity_compare`
  - `reviews` 以订单请求为单位返回 `request / expected / actual / verdict / reasons / evidence`
  - `verdict` 固定为 `PASS / FAIL / INSUFFICIENT_EVIDENCE / NOT_APPLICABLE`
  - 证据置信度固定为 `HIGH / MEDIUM / LOW`
  - 账户只返回不可逆 `account_partition` 或 `unknown`，不返回原始账户号；
    多账户与未知分区由 `data_quality` 显式说明
  - ClickHouse Trace 只作为可选补充证据，不是接口返回成交数量或持仓解释的前置条件
- `/api/position-review/portfolio/summary`
  - 返回组合总览 KPI：`total_asset / market_value / remaining_cost / floating_pnl / realized_pnl / position_ratio / cash`
  - 同时返回 `monthly_turnover`、四态 `verdict_counts`、`signal_type_counts`、`reviewable / pass_rate` 与 `data_quality.equity_basis / cost_basis`
  - `market_value` 覆盖全部持仓快照（券商真值）；`remaining_cost / floating_pnl` 对每个持仓标的优先使用 entry/slice/allocation 账本成本，证据不足时回退券商均价并在 `data_quality.cost_basis=degraded` 明示
- `/api/position-review/portfolio/series`
  - 返回权益曲线，名称与 `equity_basis` 跟随证据等级：
    - `broker_total_asset`：券商历史总资产快照（`xt_assets`）
    - `credit_snapshot_reconstructed`：信用资产快照重建（`pm_credit_asset_snapshots`，按分钟聚合，缺失区间不插值）
    - `estimated`：仅当前快照/持仓的估算
  - 每个点返回 `total_equity / estimated_equity / cash / market_value / total_debt / net_external_flow / position_ratio / drawdown`
- `/api/position-review/portfolio/contributions`
  - 返回标的贡献表（按 `total_pnl = realized + floating` 降序），支持 `top_n`（默认 10，上限 50）
- `/api/position-review/symbols/<symbol>/chart`
  - 单一 K 线主图的只读投影：返回 `holding_cycles / cost_basis_series / position_series / pnl_series / order_events / signal_type_registry / cost_basis / data_quality`
  - 市场 K 线仍由 Stock / ETF K 线 API 提供，`chart` 不复制行情 bars
  - `order_events[]` 是订单级事件合同：`event_id / account_partition / side / event_type / request_id / internal_order_id / broker_order_id / signal / order / execution / position_impact / review / marker / conditions / data_quality`
  - `marker` 锚定首次成交 bar 与订单加权成交均价；`execution` 保留多笔 fill 明细、首末成交时间与 fill 数
  - `signal_type_registry` 由服务端稳定映射 `signal_type -> family / label / marker_symbol`；前端只消费该映射
  - 支持 `period / account_partition / include_unfilled` 查询参数；`include_unfilled=false`（默认）只返回已有实际成交的订单
  - `cost_basis.fees_included` 恒为 `false`；`cost_basis.source` 为 `entry_slice_allocation`（账本完整）或 `estimated_moving_average`（降级）
- `/api/position-review/events/<event_id>/conditions`
  - 按 `event_id` 懒加载完整条件证据：`signal / trigger_snapshot / conditions / expression / condition_tree / strategy_version / config_snapshot_hash / evidence / data_quality`
  - 每个 condition 返回 `condition_key / label / actual_value / actual_display / operator / threshold_value / threshold_display / unit / passed / source / observed_at / evidence_id`
  - 历史阈值缺失时 `threshold_value=null` 且 `source=missing`，`data_quality.threshold_missing_count` 计数并在页面提示“历史阈值证据缺失”；当前配置不进入历史 condition snapshot
  - 找不到事件时返回 404
- `/api/stock_data`、`/api/stock_data_v2`、`/api/stock_data_chanlun_structure`
  - 当前分钟周期参数兼容 `1min / 5min / 15min / 30min` 与 `1m / 5m / 15m / 30m`，进入服务前统一归一到前端/缠论服务使用的 `1m / 5m / 15m / 30m`
  - `/api/stock_data?realtimeCache=1` 优先读取实时 K 线缓存；若 QFQ 覆盖缺口（含历史无效/占位缺口，不再限定为当日）未就绪，则记录 warning 并回退历史 K 线读取，避免行情图表左侧列表标的出现主图空白
  - 非实时历史读取或结构读取遇到 QFQ 未就绪时仍返回 `QFQ_DATA_NOT_READY` 对应 HTTP 状态
- `POST /api/pools/stock/sync-from-tdx`
  - 从当前 TDX home 的 `T0002/blocknew/ZXG.blk` 读取通达信自选股，解码为 6 位标的代码，排除完整持仓后，以结果覆盖 `freshquant.stock_pools`
  - 覆盖同步契约：文件缺失、解析失败或有效代码为 0 时直接阻断，不修改池子；先批量 upsert 目标代码，全部成功后再删除不在目标集合中的旧记录；持仓排除集合不受 `max_symbols` 截断
  - 查询参数 `days` 控制新增记录有效期，默认 `30`
  - 返回 `source_count / synced_count / removed_count / holding_excluded_count / invalid_count` 及对应代码列表；只写 `stock_pools`，不写 `must_pool`，不触发交易动作
- `POST /api/pools/must/sync-from-tdx`
  - 复用相同的 TDX `.blk` 读取/解码链路，从当前 TDX home 的 `T0002/blocknew/待买.blk` 读取「待买」分组（经 `blocknew.cfg` 按显示名解析，如 `DM.blk`），解码为 6 位标的代码，排除完整持仓后覆盖刷新 `freshquant.must_pool`
  - 覆盖同步契约与 stock 相同（文件阻断、完整持仓排除、先批量 upsert 后删除旧成员）
  - 已有记录保留 `stop_loss_price / initial_lot_amount / lot_amount` 交易参数；新代码自动解析统一系统默认参数（`lot_amount` 走 `get_trade_amount(code)`，`initial_lot_amount` 默认等于 `lot_amount`；`stop_loss_price` 使用系统默认止损配置 `params.guardian.value.stock.stop_loss_default`，未配置时以 `None` 导入——通达信「待买」分组不承载止损配置，不再因缺省止损阻断同步）
  - 查询参数 `days` 控制 membership 有效期，默认 `30`
  - 返回 `source_count / synced_count / removed_count / holding_excluded_count / invalid_count / failed_count` 及对应代码列表；只写 `must_pool`，不写 `stock_pools`，不触发交易动作
- `/api/stock_fills`
  - 仍保留旧名称
  - 底层优先读 `entry ledger`
- `/api/clx-daily-selection/batches` 与 `/api/clx-daily-selection/batches/latest`
  - 默认只读取 `is_final=true` 且 `publication.status in [published, not_required]` 的完整 batch
  - 只有显式传 `include_partial=1` 时才把单侧完成、运行中、失败、drift 或 publication `pending/publishing/failed` 纳入返回
  - publication 未完成的内部 final 内容在公共响应中降级为 `release_status=partial / is_final=false`
  - batch 固定返回 `status / release_status / is_final / trade_date / evaluation_profile_id / switch_opt / partitions`；final 内容存在时额外返回 `publication`
  - `partitions.stock` 与 `partitions.etf` 分别暴露本侧 `status / attempt_status / selection_key / attempt_no / partition_id / marker_snapshot_hash / content_hash / upstream_status / error`；当前 marker 缺失时该侧为 `waiting / marker_missing`
  - marker 或 partition generation 漂移产生的新 batch id 与旧 generation 分离；旧 failed/pending final 不会被公共接口提升为当前完整结果
  - `publication` 暴露 `generation_id / generation_order / publication_id / status / attempt_count / last_error`；迟到旧 generation 返回的 `last_error.code=stale_publication` 保持 failed/partial，相同 publication id 的重试保持幂等
- `/api/clx-daily-selection/batches/<batch_id>/results`
  - GET/POST 都查询服务端已计算事实；`/results/query` 是同一查询合同的显式 POST 别名
  - 支持 `asset_types / model_keys / condition_keys / directions / min_model_count / q / cursor / limit`
  - partial batch 只查询已完成 partition，不补造未完成侧结果
  - 默认排序为 `distinct_model_count DESC / distinct_condition_count DESC / symbol ASC`
- `/api/clx-daily-selection/batches/<batch_id>/statistics`
  - final batch 返回股票、ETF 与完整 batch 统计
  - partial 不作为跨资产统计真值；页面只显示已完成侧的分区事实与 partial 状态
- `/api/clx-daily-selection/batches/<batch_id>/results/<asset_type>/<symbol>`
  - 返回标的 snapshot 与 memberships
  - membership 分开返回 `model_key / signal_value_raw / primary_entrypoint / model_condition / condition_evidence`
  - unknown 与 S0002 entrypoint 3 缺证据保持显式 unknown，不折叠为 false
- `/api/clx-daily-selection/history/signals`
  - 当前只接受 `period=1d`，`barCount` 范围 `1..2000`
  - 支持 `symbol / assetType / endDate / modelKeys / conditionKeys / includeRaw`；省略 `endDate` 时由 provider 解析标的最新交易日
  - 返回 `end_date / bars / signals_by_model / markers_by_model / line_series / calculation_profile / input_bar_asof / future_function_guard / query_hash`
  - `line_series` 与 bars 等长；当前 `ma250` 使用 `ma250-v1`，`chanlun_line` 与 `reference_line` 没有正式来源时保持 unknown
  - HTTP `ETag` 使用 `query_hash`
- `/api/clx-daily-selection/health`
  - 返回 `fqcopilot` batch、single 和 S0002 evidence 能力状态
  - 正式值应为 `evaluation_profile_id=production_v1`、`switch_opt=1`、`model_count=18`

## CLI

统一入口：

```powershell
python -m freshquant.cli
```

稳定命令组：

- `stock`
- `etf`
- `index`
- `future`
- `xt-asset`
- `xt-trade`
- `xt-order`
- `xt-position`
- `channel`
- `om-order`

订单管理 CLI：

```powershell
python -m freshquant.cli om-order submit --action buy --symbol 600000 --price 10.5 --quantity 100
python -m freshquant.cli om-order cancel --internal-order-id <id>
```

## Codex / Memory Bootstrap

- memory bootstrap 脚本
  - `py -3.12 runtime/memory/scripts/bootstrap_freshquant_memory.py --repo-root . --service-root D:/fqpack/runtime`
- Codex CLI 启动入口
  - `codex_run/start_codex_cli.bat`
- Codex app-server 启动入口
  - `codex_run/start_codex_app_server.bat`
- app-server 默认通过 `stdio://` 暴露本地会话接口
- 本地 `codex app-server` 窗口按 `Ctrl+C` 退出；关闭该窗口即停止服务

## 后台 worker

- XTData producer
  - `python -m freshquant.market_data.xtdata.market_producer`
- XTData consumer
  - `python -m freshquant.market_data.xtdata.strategy_consumer --prewarm`
- Guardian monitor
  - `python -m freshquant.signal.astock.job.monitor_stock_zh_a_min --mode event`
- XT account sync worker
  - `python -m freshquant.xt_account_sync.worker --interval 15`
- XT auto repay worker
  - `python -m freshquant.xt_auto_repay.worker`
- TPSL worker
  - `python -m freshquant.tpsl.tick_listener`

## Web UI 路由

- `/kline-slim`
  - 裸路径保持普通持仓/股票池行情模式；加 `clxScreening=1&clxWorkbench=1`后进入 CLX 统一工作台，左栏选股筛选与 cursor 列表、中栏 K 线、右栏历史信号操作共享当前 scope/symbol/endDate 上下文
  - `clxScope` 为共享 scope；左栏筛选使用 `clxFilter*`，右栏 marker 显示使用 `clxModels / clxConditions / clxMarkerMode`，两组模型/条件状态互不覆盖；cursor 只属于当前列表请求链，不写入 URL
- `/clx-daily-screening`
  - 兼容旧收藏和深链的 redirect；旧 `clxModels / clxConditions` 按原页面语义迁移到左栏 `clxFilterModels / clxFilterConditions`，进入 `/kline-slim?clxScreening=1&clxWorkbench=1&period=1d`，不再提供独立页面
- `/position-management`
- `/position-review`
- `/runtime-observability`
- `/gantt`
- `/daily-screening`（CLX 选股 / 评价 / 三池工作台）
- `/clx-evaluation`（Vue Router 重定向到 `/daily-screening`）
