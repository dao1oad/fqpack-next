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
- `GET /api/position-review/symbols/<symbol>/timeline`

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
- `/api/get_stock_pre_pools_list`
- `/api/get_stock_must_pools_list`
- `/api/add_to_stock_pools_by_code`
- `/api/add_to_must_pool_by_code`

### `gantt`

- `/api/gantt/plates`
- `/api/gantt/stocks`
- `/api/gantt/stocks/reasons`
- `/api/gantt/shouban30/plates`
- `/api/gantt/shouban30/stocks`
- `/api/gantt/shouban30/pre-pool/*`
- `/api/gantt/shouban30/stock-pool/*`

### `daily-screening`

- `/api/daily-screening/scopes`
- `/api/daily-screening/scopes/latest`
- `/api/daily-screening/filters`
- `/api/daily-screening/scopes/<scope_id>/summary`
- `/api/daily-screening/query`
- `/api/daily-screening/stocks/<code>/detail`
- `/api/daily-screening/actions/add-to-pre-pool`
- `/api/daily-screening/actions/add-batch-to-pre-pool`
- `/api/daily-screening/pre-pools`
- `/api/daily-screening/pre-pools/stock-pools`
- `/api/daily-screening/pre-pools/delete`

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
  - 当前返回单标的 `summary / executions / charts / reviews / timeline / data_quality`
  - `executions` 是按账户分区稳定标识的 canonical 逐笔成交台账；同账户迟到或更正的 XT 真值不会与旧 OM/XT 归档重复计数
  - 合并当前 `xt_trades / OM ledger` 与
    `om_execution_history_archive / position_review_evidence_archive`；
    initialize 或 order-ledger rebuild 后已归档历史仍可查询
  - `charts` 包含 `cumulative_quantity / traded_amount / trade_price / verdict_distribution / request_quantity_compare`
  - `reviews` 以订单请求为单位返回 `request / expected / actual / verdict / reasons / evidence`
  - `verdict` 固定为 `PASS / FAIL / INSUFFICIENT_EVIDENCE / NOT_APPLICABLE`
  - 证据置信度固定为 `HIGH / MEDIUM / LOW`
  - 账户只返回不可逆 `account_partition` 或 `unknown`，不返回原始账户号；
    多账户与未知分区由 `data_quality` 显式说明
  - ClickHouse Trace 只作为可选补充证据，不是接口返回成交数量或持仓解释的前置条件
- `/api/position-review/symbols/<symbol>/timeline`
  - 当前为 `/position-review` 的订单级三轨图和 `/kline-slim` 可选交易复盘模式提供窗口化只读投影；支持 `start / end / refresh` 查询参数
  - 返回 `events / position_series / range / data_quality`；每个 `events[]` 是按 `account_partition + internal_order_id`（缺少内部订单时使用安全回退键）聚合的一笔订单，而不是逐笔 fill
  - 未传窗口时，`events[].actual` 返回订单级总成交量、加权成交均价、成交笔数和首末成交时点；传入 `start` 或 `end` 时只统计窗口内成交，`events[].data_quality.actual_scope` 固定为 `window`，避免与窗口内 `position_series` 混用不同成交口径
  - `position_series` 按真实成交时点连续回放，并在窗口起点和终点提供仓位锚点；即使窗口内没有成交，持仓阶梯线也覆盖整个请求时间窗。同秒跨订单、缺少可证明先后关系时，订单事件以 `data_quality` 明示仓位归属不确定，不承诺任一订单的确定前后仓位
  - 当一个策略请求拆分为多个订单或账户分区、但没有可用分配证据时，相关 `expected_quantity` 返回 `null` 并附带 `expected_quantity_ambiguous_across_orders` warning，避免在数量轨重复计算策略应有量
  - `events[].signal` 只在存在 `request_id / internal_order_id / trace_id / intent_id` 等明确关联键时返回；不以时间邻近规则伪造信号与订单关联
- `/api/stock_fills`
  - 仍保留旧名称
  - 底层优先读 `entry ledger`

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
- `/position-management`
- `/position-review`
- `/runtime-observability`
- `/gantt`
- `/gantt/shouban30`
- `/daily-screening`
