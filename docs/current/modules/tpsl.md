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
- `position_management.pm_symbol_position_snapshots`
- 订单 request / order / event / trade 追踪集合

## 数据流

`Redis tick -> TickQuoteListener -> TpslTickConsumer.handle_tick -> load_active_tpsl_codes -> evaluate_takeprofit / evaluate_stoploss -> create batch -> OrderSubmitService`

执行顺序上，takeprofit 先于 stoploss 评估。

TPSL 与 Runtime Observability 的当前口径：

- `evaluate_takeprofit` 只有在某个有效止盈层级真正命中当前价格时，才会创建 `trace_id` 并把后续 `trigger_eval / blocked / error` 事件并入全局 Trace
- 止盈价未设置、空字符串、非法值或层级未命中时，不再写成功态 `tick_match / profile_load / trigger_eval` event；页面与 `/api/runtime/events` 也会默认隐藏历史空跑评估噪声
- `evaluate_stoploss` 同样只在存在真实命中的 binding 时才创建 `trace_id`；未命中 binding 时不再写成功态 `trigger_eval`
- 需要排查底层 tick 评估原始记录时，使用 Runtime Observability 的 Raw Browser，不再依赖组件 Event 视图回看空跑评估

`/api/tpsl/management/overview -> TpslManagementService -> 当前持仓数量 + 单标的实时仓位 + takeprofit profile + stoploss 绑定 + 最近触发事件`

`/api/tpsl/management/<symbol> -> TpslManagementService -> takeprofit profile/state + stock_fills 兼容对照视图 + open buy lots + 单标的实时仓位 + stoploss bindings + 统一历史`

其中 `stock_fills` 对照视图的读路径当前优先使用 OM 投影，再退到 `freshquant.stock_fills_compat`，只有 compat 缺失时才兜底原始 `stock_fills`。

`/api/tpsl/history -> TpslManagementService -> om_exit_trigger_events + om_order_requests + om_orders + om_order_events + om_trade_facts`

`/api/tpsl/takeprofit/<symbol>` 读写与 tier enable/disable/rearm 响应在返回前也会把 Mongo `ObjectId`、日期时间对象归一成 JSON-safe 值，避免保存后因为原始文档字段导致 500。

`/api/tpsl/management/<symbol>` 与 `/api/tpsl/history` 在返回前会把 Mongo `ObjectId`、日期时间对象归一成 JSON-safe 值，避免管理页详情/历史响应因为底层文档原始字段而序列化失败。

`om_takeprofit_states.armed_levels` 在 Mongo 中按 string key 持久化（例如 `"1": true`），服务层对外仍按 level map 归一读取，避免首次补 state 或 rearm 时因为整型 key 被 Mongo 拒绝。

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
- cooldown lock（未配置 Redis 时使用进程内 fallback；Redis 已配置但写锁失败时直接报错）
- Redis host/port/db

当前可通过 API：

- 设置 profile
- 启用/停用 tier
- rearm
- 查询 symbol 汇总与详情
- 查询统一事件/订单/成交历史

当前页面支持：

- 左侧标的卡片只读展示 symbol 级三层止盈价格
- buy lot 级 stop_price 设置与启停
- 同页查看 `stock_fills` 兼容对照视图
- 同页查看 takeprofit / stoploss 触发历史及后续 request/order/trade

当前 `/tpsl` 页面已切到统一的 workbench density 语法：

- 顶部使用紧凑 toolbar 承载标题、摘要和刷新动作
- 左侧保留 symbol 导航，列表在单屏内独立滚动，卡片摘要展示统一单标的实时仓位（万元）和三层止盈价格
- 右侧保留详情工作台
- 右侧标题摘要同时展示持仓股数和统一实时仓位
- 右侧不再提供 symbol 级止盈层次编辑；止盈设置真值入口以 `KlineSlim` 为主
- 右侧新增 `stock_fills` 对照表
- `stock_fills` 对照表当前统一展示方向列：`external_inferred` 显示 `推断持仓`；OM 投影返回的 open buy fills 即使未显式带 `op`，也按当前真值语义显示 `买入`
- 统一历史改成高密度表格，继续同屏展示 request/order/trade 明细

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
- 检查 `xt_positions.volume` 是否存在非数字脏值；当前不会再静默按 0 处理

### 命中止盈但没有生成退出单

- 检查 profile 是否 enabled
- 检查 cooldown 是否仍在
- 检查 `xt_positions` 可卖数量
- 检查 `xt_positions.can_use_volume / volume` 是否存在非数字脏值；当前会直接报错，不再静默按 0 阻断

### 管理页历史里只有 trigger，看不到后续订单或成交

- 检查 `om_order_requests.scope_type / scope_ref_id` 是否写成 `takeprofit_batch` 或 `stoploss_batch`
- 检查 `om_orders.request_id`、`om_order_events.internal_order_id`、`om_trade_facts.internal_order_id` 是否能串起来
- 检查 `om_exit_trigger_events.batch_id` 是否和 request 的 `scope_ref_id` 一致

### 管理页仓位金额不对

- 检查 `pm_symbol_position_snapshots.market_value`
- 检查 `xt_positions.market_value` 是否与券商查询一致
- 检查 `xt_account_sync.worker` 最近一次 `positions` 同步是否成功

### 管理页 `stock_fills` 对照视图不一致

- 先检查 `om_buy_lots` / `om_lot_slices` 是否正确
- 再检查 `freshquant.stock_fills_compat` 是否已同步
- compat 缺失时才回头看原始 `freshquant.stock_fills`

### 触发事件落了但批次无单

- 检查 `om_exit_trigger_events`
- 检查 OrderSubmitService 是否被拒绝
- 检查 Position Management 是否影响了退出单（理论上卖单应允许）
