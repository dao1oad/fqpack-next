# 当前架构

## 总体分层

- 行情层
  - `freshquant.market_data.xtdata.*`
- 策略层
  - `freshquant.strategy.*`
  - `freshquant.signal.*`
- 交易执行层
  - `freshquant.order_management.*`
  - `freshquant.position_management.*`
  - `freshquant.tpsl.*`
- 展示层
  - `freshquant.rear.*`
  - `morningglory/fqwebui`
- 观测层
  - `freshquant.runtime_observability.*`
- 记忆层
  - `freshquant.runtime.memory.*`

## 记忆层

- 热记忆
  - 当前会话通过 `FQ_MEMORY_CONTEXT_PATH` 加载的 context pack
- 冷记忆
  - `runtime/memory/**` 中由 bootstrap / archive / retrieval 维护的长期记忆材料
  - 自由会话通过 `runtime/memory/scripts/bootstrap_freshquant_memory.py` 生成并加载 context pack
- 正式边界
  - 记忆层只提供上下文，不覆盖 GitHub、`docs/current/**` 与最新远程 `origin/main` / `main` 的正式真值
  - 涉及运行交付时，以最新远程 `main` 的正式 deploy 与 health check 为准
  - 所有代码更新的 PR + CI + merge gate 仍是交付收敛面的正式真值

## 订单相关核心调用链

### 实时交易链

`XTData -> Guardian -> PositionManagement gate -> OrderManagement submit -> broker -> XT callback -> OrderManagement ingest -> Position/TPSL/Subject/Kline read models`

### 止盈止损链

`tick -> TpslTickConsumer -> TpslService -> OrderSubmitService -> broker -> XT callback -> OrderManagement ingest`

### 当前仓位链

`xt_account_sync.worker -> xt_positions -> pm_symbol_position_snapshots -> PositionManagement / SubjectManagement / TpslManagement / KlineSlim`

### 当前自动还款链

`xt_account_sync.worker -> pm_credit_asset_snapshots -> xt_auto_repay.worker -> query_credit_detail confirm -> XtQuantTrader.order_stock(CREDIT_DIRECT_CASH_REPAY, placeholder stock_code, LATEST_PRICE)`

## 当前订单账本边界

### 券商真值层

- `xt_positions`
- `xt_orders`
- `xt_trades`

### 订单账本层

- `om_order_requests`
- `om_orders`
- `om_broker_orders`
- `om_order_events`
- `om_execution_fills`
- `om_trade_facts`

### 持仓解释层

- `om_position_entries`
- `om_entry_slices`
- `om_exit_allocations`

### 自动平账层

- `om_reconciliation_gaps`
- `om_reconciliation_resolutions`
- `om_ingest_rejections`

### 兼容层

- `om_buy_lots`
- `om_lot_slices`
- `om_sell_allocations`
- `freshquant.stock_fills`
- `freshquant.stock_fills_compat`

## 当前关键边界

- `xt_positions`
  - 定义当前券商仓位真值
- `om_broker_orders + om_execution_fills`
  - 定义执行事实
  - XT 回报进入订单账本时，`broker_order_id` 只作为候选检索键；重复券商订单号需要结合 `symbol`、`side/order_type` 与回报时间确定内部订单
- `om_position_entries`
  - 定义系统可消费的持仓入口
- `om_reconciliation_*`
  - 只负责自动平账，不再伪造成 fake order / fake trade
- `stock_fills_compat`
  - 只做兼容投影，不再参与运行期真值判断

## 当前页面消费关系

- `OrderManagement`
  - 订单请求、内部订单、券商订单、成交事实
- `PositionManagement`
  - `券商仓位 / 账本仓位 / 对账状态`
- `SubjectManagement`
  - `entries + entry stoploss + must_pool + limit summary`
- `TpslManagement`
  - `entries + entry_slices + takeprofit + stoploss`
- `KlineSlim`
  - `entries + entry stoploss + guardian/takeprofit`

## 当前规则

- buy fill 默认按 broker order 聚合成一个 entry
- 对账补开的 `auto_reconciled_open` 若与相邻 open entry 满足同标的、同交易日、5 分钟内且价差不超过 0.3%，也会并入同一个 buy cluster
- stoploss 绑定对象是 `entry_id`
- odd-lot 不进入 `position_entries`
- odd-lot 进入 `om_ingest_rejections`
- XT 自动还款当前只处理普通融资负债；盘中低频巡检只把快照当候选信号，真正提交前始终再查一次实时 `credit_detail`

## 当前部署边界

- `freshquant/order_management/**`
  - 重建 API Server
  - 重启 `xt_account_sync.worker`
  - 重启 `xt_auto_repay.worker`
  - 重启 `tpsl.tick_listener`
- `freshquant/position_management/**`
  - 重建 API Server
  - 重启 `xt_account_sync.worker`
- `freshquant/xt_auto_repay/**`
  - 重启 `xt_auto_repay.worker`
- `freshquant/tpsl/**`
  - 重建 API Server
  - 重启 `tpsl.tick_listener`
- `morningglory/fqwebui/**`
  - 重建 Web UI
