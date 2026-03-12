# 当前接口

## HTTP API

统一入口：

```powershell
python -m freshquant.rear.api_server --port 5000
```

当前蓝图与主要接口：

### `stock`

- `/api/stock_data`
- `/api/stock_data_v2`
- `/api/stock_data_chanlun_structure`
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

### `order`

- `/api/order/submit`
- `/api/order/cancel`
- `/api/stock_order`
- `/api/order-management/buy-lots/<buy_lot_id>`
- `/api/order-management/stoploss/bind`

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

### `runtime`

- `/api/runtime/components`
- `/api/runtime/health/summary`
- `/api/runtime/traces`
- `/api/runtime/traces/<trace_id>`
- `/api/runtime/events`
- `/api/runtime/raw-files/files`
- `/api/runtime/raw-files/tail`

## CLI

统一入口：

```powershell
python -m freshquant.cli
```

当前稳定命令组：

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

## 后台 worker 与服务入口

- XTData producer
  - `python -m freshquant.market_data.xtdata.market_producer`
- XTData consumer
  - `python -m freshquant.market_data.xtdata.strategy_consumer --prewarm`
- Guardian monitor
  - `python -m freshquant.signal.astock.job.monitor_stock_zh_a_min --mode event`
- Position worker
  - `python -m freshquant.position_management.worker --interval 3`
- TPSL worker
  - `python -m freshquant.tpsl.tick_listener`
- Symphony 正式服务
  - `runtime/symphony/scripts/start_freshquant_symphony.ps1`
  - `runtime/symphony/scripts/activate_github_first_formal_service.ps1`

## Web UI 路由

- `/stock-control`
- `/kline-slim`
- `/gantt`
- `/gantt/shouban30`
- `/gantt/stocks/:plateKey`
- `/tpsl`
- `/runtime-observability`

## 当前接口边界

- 交易主入口是 `OrderSubmitService`；HTTP 和 CLI 只是它的包装。
- Kline 与 stock pool 仍保留一批历史接口；这些接口可继续使用，但新增页面应优先复用当前已有路由，不要再扩新的平行接口面。
- Runtime API 只读原始日志与聚合视图，不承担修复动作。
- TPSL 管理页通过 `/api/tpsl/management/*` 和 `/api/tpsl/history` 读取 symbol 汇总、buy lot 止损和统一触发历史；止盈/止损写操作仍分别复用 `/api/tpsl/takeprofit/*` 与 `/api/order-management/stoploss/bind`。
