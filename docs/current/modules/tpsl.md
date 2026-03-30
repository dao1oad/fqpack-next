# 止盈止损

## 职责

TPSL 在独立 tick 链路上评估止盈和止损条件，并生成退出单。当前模块已经切到 `position entry` 语义：

- 止盈仍按 symbol profile 管理
- 止损对象改为 open `position_entries`
- 历史与详情优先读取 `entry ledger`
- 止盈卖出提交前会统一按 `xt_positions.can_use_volume` 截断，并按一手向下取整；Guardian 卖出现在复用同一套约束 helper

## 入口

- worker
  - `python -m freshquant.tpsl.tick_listener`
- HTTP
  - `/api/tpsl/takeprofit/<symbol>`
  - `/api/tpsl/takeprofit/<symbol>/tiers/<level>/enable`
  - `/api/tpsl/takeprofit/<symbol>/tiers/<level>/disable`
  - `/api/tpsl/takeprofit/<symbol>/rearm`
  - `/api/tpsl/management/overview`
  - `/api/tpsl/management/<symbol>`
  - `/api/tpsl/history`
  - `/api/tpsl/events`
  - `/api/tpsl/batches/<batch_id>`
- Web UI
  - `/tpsl`

## 当前依赖

- Redis tick 队列
- `xt_positions`
- `pm_symbol_position_snapshots`
- `om_takeprofit_profiles`
- `om_takeprofit_states`
- `om_position_entries`
- `om_entry_slices`
- `om_entry_stoploss_bindings`
- `om_exit_trigger_events`
- `om_order_requests / om_orders / om_order_events / om_trade_facts`

## 当前读模型

### overview

`/api/tpsl/management/overview` 当前汇总：

- 当前持仓数量
- 单标的实时仓位金额
- 止盈 profile 摘要
- entry stoploss 摘要
- 最近触发事件

### detail

`/api/tpsl/management/<symbol>` 当前返回：

- takeprofit profile / state
- `entries`
- `entry_slices`
- `reconciliation`
- 统一历史摘要

当前 detail 已不再返回 `buy_lots`，也不再把 `stock_fills` 兼容视图当成主详情对象。
每条 `entry` 当前会内嵌自己的 `stoploss` 绑定摘要。

### history

`/api/tpsl/history` 当前只按：

- `symbol`
- `batch_id`
- `entry_id`

做过滤；不再接受 `buy_lot_id`。

## 止损语义

页面上“单笔止损”当前实际是“单 entry 止损”：

- 一条 open entry 对应一条可配置止损对象
- 同一 broker order 下多笔 fill 聚合成一个 entry 时，TPSL 默认只看到一条止损对象
- 只有真正形成多个 open entries 时，TPSL 才会出现多行止损

## entry ledger / compat

- `entry_ledger`
  - 主读模型，来自 `om_position_entries + om_entry_slices`
- `stock_fills_compat`
  - 仅兼容旧接口/旧脚本
  - 不再定义 TPSL 主页面真值

## 页面布局

`/tpsl` 当前是：

- 左侧 symbol 导航
- 右侧详情工作台
- 统一历史表

左侧 symbol 导航和详情表都按持仓金额从大到小排序。

## 部署

- 改动 `freshquant/tpsl/**`
  - 重建 API Server
  - 重启 `tpsl.tick_listener`
- 改动 `/tpsl`
  - 重建 Web UI

## 排障

### 命中止损但没有退出单

- 查 `om_entry_stoploss_bindings`
- 查 `xt_positions.can_use_volume / volume`
- 查 `om_exit_trigger_events`
- 查对应 request / order / trade 链路

### 页面中止损对象数量不对

- 查 `om_position_entries`
- 查该 symbol 是否被聚合成单一 `broker_execution_group` entry
- 查 `om_reconciliation_resolutions` 是否新增了 `auto_open_entry`

### 历史链路缺 request / order / trade

- 查 `om_exit_trigger_events.batch_id`
- 查 `om_order_requests.scope_type / scope_ref_id`
- 查 `om_orders.request_id`
- 查 `om_trade_facts.internal_order_id`
