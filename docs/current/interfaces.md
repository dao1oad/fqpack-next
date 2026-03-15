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
- `/api/order-management/orders`
- `/api/order-management/orders/<internal_order_id>`
- `/api/order-management/stats`
- `/api/order-management/buy-lots/<buy_lot_id>`
- `/api/order-management/stoploss/bind`

### `position-management`

- `/api/position-management/dashboard`
- `/api/position-management/config`

### `system-config`

- `/api/system-config/dashboard`
- `/api/system-config/bootstrap`
- `/api/system-config/settings`

### `runtime`

- `/api/runtime/components`
- `/api/runtime/health/summary`
- `/api/runtime/traces`
- `/api/runtime/traces/<trace_id>`
- `/api/runtime/events`
- `/api/runtime/raw-files/files`
- `/api/runtime/raw-files/tail`

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

其中：

- `/api/runtime/health/summary` 固定返回核心组件全集；没有最新 health 数据时返回 `status=unknown`、`heartbeat_age_s=null`、`is_placeholder=true`
- 仓位管理页面使用独立 `/api/position-management/*` 读模型接口，因为它需要同时返回配置 inventory、effective state、holding scope 和规则矩阵
- 系统设置页面使用独立 `/api/system-config/*` 接口，明确区分 Bootstrap 文件配置与 Mongo 系统设置
- Runtime API 只读原始日志与聚合视图，不承担修复动作

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

交互式初始化向导：

```powershell
python -m freshquant.initialize
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
  - `runtime/symphony/scripts/install_freshquant_symphony_restart_task.ps1`
  - `runtime/symphony/scripts/invoke_freshquant_symphony_restart_task.ps1`

## Web UI 路由

- `/stock-control`
- `/kline-slim`
- `/gantt`
- `/gantt/shouban30`
- `/gantt/stocks/:plateKey`
- `/order-management`
- `/position-management`
- `/system-settings`
- `/tpsl`
- `/runtime-observability`

## 当前接口边界

- 交易主入口是 `OrderSubmitService`；HTTP 和 CLI 只是它的包装
- 系统设置页只维护新系统正式配置，不再承载旧 SMTP / 邮件收件人或旧 `code + value` 通用参数模式
- Kline 与 stock pool 仍保留一批历史接口；这些接口可继续使用，但新增页面应优先复用当前已有路由，不要再扩新的平行接口面
- `/api/gantt/shouban30/plates` 与 `/api/gantt/shouban30/stocks` 当前正式时间参数是 `days` 与 `end_date`
