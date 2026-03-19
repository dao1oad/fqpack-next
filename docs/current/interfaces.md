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

### `subject-management`

- `/api/subject-management/overview`
- `/api/subject-management/<symbol>`
- `/api/subject-management/<symbol>/must-pool`
- `/api/subject-management/<symbol>/guardian-buy-grid`

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
- 标的管理页面使用独立 `/api/subject-management/*` 聚合接口，把 `must_pool / guardian_buy_grid / takeprofit / buy lot stoploss / 运行态摘要` 收口到同一页；账户级仓位门禁只读联动展示，不在该页写入
- 系统设置页面使用独立 `/api/system-config/*` 接口，明确区分 Bootstrap 文件配置与 Mongo 系统设置
- 每日选股页面的查询主链路使用 `/api/daily-screening/*`；共享工作区操作直接复用 `/api/gantt/shouban30/pre-pool/*` 与 `/api/gantt/shouban30/stock-pool/*`
- Runtime API 只读原始日志与聚合视图，不承担修复动作
- `/api/runtime/traces` 与 `/api/runtime/traces/<trace_id>` 默认只用事件内已有字段组装 `symbol_name`；只有显式传 `include_symbol_name=1` 才会按需补查 instrument 信息

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
- XT account sync worker
  - `python -m freshquant.xt_account_sync.worker --interval 3`
- TPSL worker
  - `python -m freshquant.tpsl.tick_listener`
- Symphony 正式服务
  - `runtime/symphony/scripts/start_freshquant_symphony.ps1`
  - `runtime/symphony/scripts/activate_github_first_formal_service.ps1`
  - `runtime/symphony/scripts/install_freshquant_symphony_restart_task.ps1`
  - `runtime/symphony/scripts/invoke_freshquant_symphony_restart_task.ps1`
- Codex 自由会话硬入口
  - `codex_run/start_codex_cli.bat`
  - `codex_run/start_codex_app_server.bat`
  - 两者都先调用 `codex_run/start_freshquant_codex.ps1`，由 wrapper 执行 `runtime/memory/scripts/bootstrap_freshquant_memory.py`，再启动对应 `codex` 命令
  - `start_codex_app_server.bat` 保持前台运行，默认启动 `codex app-server` 的 `stdio://` 传输；关闭该窗口即停止服务
- Memory bootstrap fallback
  - `runtime/memory/scripts/bootstrap_freshquant_memory.py`
  - 供没有走 `codex_run/*.bat` 的自由会话手动执行 memory refresh / compile，并返回 `context_pack_path`

## Web UI 路由

- `/stock-control`
  - 持仓股信号
  - `stock_pools模型信号`
  - `must_pools买入信号`
- 顶部导航按钮当前使用浏览器新标签页打开路由，并通过 `tabTitle` 驱动浏览器标签标题
- `/kline-slim`
- `/gantt`
- `/gantt/shouban30`
- `/daily-screening`
- `/gantt/stocks/:plateKey`
- `/order-management`
- `/position-management`
- `/subject-management`
- `/system-settings`
- `/tpsl`
- `/runtime-observability`

## 当前接口边界

- 交易主入口是 `OrderSubmitService`；HTTP 和 CLI 只是它的包装
- `/stock-control` 当前读取两类信号接口：
  - `/api/get_stock_signal_list`
  - `/api/get_stock_model_signal_list`
- `/stock-control` 当前只展示信号列表，不再承载持仓股列表
- `/stock-control` 当前按 `/gantt/shouban30` 的 panel-table 语法展示三个并行列表：
  - 左列 `持仓股信号`
  - 中列 `stock_pools模型信号`
  - 右列 `must_pools买入信号`
- `/stock-control` 三个列表当前统一列结构为：
  - `信号时间`
  - `入库时间`
  - `标的代码`
  - `标的名称`
  - `价格`
- `/stock-control` 的价格列当前统一展示为单行 `触发价 / 止损价 / 止损%`，价格数值保留三位小数，分页默认 `100` 条/页
- 系统设置页只维护新系统正式配置，不再承载旧 SMTP / 邮件收件人或旧 `code + value` 通用参数模式
- Kline 与 stock pool 仍保留一批历史接口；这些接口可继续使用，但新增页面应优先复用当前已有路由，不要再扩新的平行接口面
- `/api/gantt/shouban30/plates` 与 `/api/gantt/shouban30/stocks` 当前正式时间参数是 `days` 与 `end_date`
- `/api/daily-screening/query` 的语义是“先锚定 base union，再对所选条件统一取交集”
- `/api/daily-screening/stocks/<code>/detail` 会返回统一详情：snapshot、memberships、CLXS 命中、chanlun 命中、90 天聚合、市场属性与热门理由
- `/daily-screening` 页面当前会展示条件说明提示，并允许把当前交集结果直接追加到共享 `pre_pools`
