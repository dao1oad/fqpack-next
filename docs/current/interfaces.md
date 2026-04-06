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
- `/runtime-observability`
- `/gantt`
- `/gantt/shouban30`
- `/daily-screening`
