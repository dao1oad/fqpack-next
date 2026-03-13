# 止盈止损

## 职责

TPSL 模块负责在独立 tick 链路上评估止盈和止损条件，并在条件满足时批量生成退出单。它是独立模块，不和 Guardian 共享买卖状态机。

## 入口

- worker
  - `python -m freshquant.tpsl.tick_listener`
- HTTP
  - `/api/tpsl/takeprofit/<symbol>`
  - `/api/tpsl/management/overview`
  - `/api/tpsl/management/<symbol>`
  - `/api/tpsl/history`
  - `/api/tpsl/events`
  - `/api/tpsl/batches/<batch_id>`
- Web UI
  - `/tpsl`
  - `morningglory/fqwebui/src/views/TpslManagement.vue`
- 核心服务
  - `freshquant.tpsl.consumer.TpslTickConsumer`
  - `freshquant.tpsl.service.TpslService`
  - `freshquant.tpsl.management_service.TpslManagementService`

## 依赖

- Redis tick 队列 `REDIS_TICK_QUEUE_PREFIX:<shard>`
- `xt_positions`
- Order Management 提交能力
- buy lot / stoploss 绑定信息
- stock holdings 读模型
- 订单 request / order / event / trade 追踪集合

## 数据流

`Redis tick -> TickQuoteListener -> TpslTickConsumer.handle_tick -> load_active_tpsl_codes -> evaluate_takeprofit / evaluate_stoploss -> create batch -> OrderSubmitService`

执行顺序上，takeprofit 先于 stoploss 评估。

`/api/tpsl/management/overview -> TpslManagementService -> 当前持仓 + takeprofit profile + stoploss 绑定 + 最近触发事件`

`/api/tpsl/management/<symbol> -> TpslManagementService -> takeprofit profile/state + open buy lots + stoploss bindings + 统一历史`

`/api/tpsl/history -> TpslManagementService -> om_exit_trigger_events + om_order_requests + om_orders + om_order_events + om_trade_facts`

## 存储

TPSL 数据当前仍放在订单管理库，核心集合：

- `om_takeprofit_profiles`
- `om_takeprofit_states`
- `om_exit_trigger_events`
- `om_buy_lots`
- `om_stoploss_bindings`
- `om_order_requests`
- `om_orders`
- `om_order_events`
- `om_trade_facts`

TPSL 还会读取：

- `xt_positions`
- `om_buy_lots`
- `om_stoploss_bindings`

## 配置

- takeprofit profile tiers
- rearm / enable / disable 状态
- cooldown lock（Redis 或内存 fallback）
- Redis host/port/db

当前可通过 API：

- 设置 profile
- 启用/停用 tier
- rearm
- 查询 symbol 汇总与详情
- 查询统一事件/订单/成交历史

当前页面支持：

- symbol 级止盈层次编辑
- buy lot 级 stop_price 设置与启停
- 同页查看 takeprofit / stoploss 触发历史及后续 request/order/trade

## 部署/运行

- 改动后至少重启：

```powershell
python -m freshquant.tpsl.tick_listener
```

- 如果改了 API，同时重建 `fq_apiserver`
- 如果改了管理页，同时重建 `fq_webui`

## 排障点

### tick 到了但完全不评估

- 检查 worker 是否在跑
- 检查 active universe 是否包含目标股票
- 检查 Redis tick 队列是否真的有目标 code

### 命中止盈但没有生成退出单

- 检查 profile 是否 enabled
- 检查 cooldown 是否仍在
- 检查 `xt_positions` 可卖数量

### 管理页历史里只有 trigger，看不到后续订单或成交

- 检查 `om_order_requests.scope_type / scope_ref_id` 是否写成 `takeprofit_batch` 或 `stoploss_batch`
- 检查 `om_orders.request_id`、`om_order_events.internal_order_id`、`om_trade_facts.internal_order_id` 是否能串起来
- 检查 `om_exit_trigger_events.batch_id` 是否和 request 的 `scope_ref_id` 一致

### 触发事件落了但批次无单

- 检查 `om_exit_trigger_events`
- 检查 OrderSubmitService 是否被拒绝
- 检查 Position Management 是否影响了退出单（理论上卖单应允许）
