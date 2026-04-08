# 止盈止损

## 职责

TPSL 在独立 tick 链路上评估止盈和止损条件，并生成退出单。当前模块已经切到 `position entry` 主语义，并同时支持 symbol 级全仓止损：

- 止盈仍按 symbol profile 管理
- 止盈命中档位但当前可盈利切片数量为 `0` 时，仍会消耗命中档位并写 `takeprofit_hit`，但不会生成退出单
- 止损对象改为 open `position_entries`
- `must_pool.stop_loss_price` 当前承担 symbol 级 `全仓止损价`
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

## 当前依赖

- Redis tick 队列
- `xt_positions`
- `pm_symbol_position_snapshots`
- `must_pool`
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

当前 `takeprofit state` 缺失时，系统统一按未激活处理：

- `TakeprofitService.get_state()` 会创建 `armed_levels[level]=false` 的默认 state
- `/api/tpsl/management/*` 与 `/api/subject-management/*` 都按未激活口径返回
- 只有执行 `/api/tpsl/takeprofit/<symbol>/rearm` 或显式开启层级后，运行态才会恢复为可触发

当前 detail 已不再返回 `buy_lots`，也不再把 `stock_fills` 兼容视图当成主详情对象。
每条 `entry` 当前会内嵌自己的 `stoploss` 绑定摘要。
`reconciliation.state` 当前统一复用 shared canonical 语义，前后端展示统一为：

- `ALIGNED`：券商与账本对齐
- `OBSERVING`：存在待观察差额
- `AUTO_RECONCILED`：系统已自动补齐账本
- `BROKEN`：对账链路异常
- `DRIFT`：券商与账本仍然漂移

### history

`/api/tpsl/history` 当前只按：

- `symbol`
- `batch_id`
- `entry_id`

做过滤；不再接受 `buy_lot_id`。

## 止损语义

当前运行时止损分成两层：

- `全仓止损`
  - 来源：`must_pool.stop_loss_price`
  - 条件：`bid1 <= full_stop_price`
  - 结果：生成 `scope_type=symbol_stoploss_batch`、`strategy_name=FullPositionStoploss`
  - 卖出该 symbol 下全部可卖 open entry slices，并继续受 `can_use_volume` 与一手约束限制
- `单笔止损`
  - 来源：`om_entry_stoploss_bindings`
  - 条件：entry 级 `stop_price` 命中
  - 结果：生成 `scope_type=stoploss_batch`、`strategy_name=PerEntryStoplossBatch`

页面上“单笔止损”当前实际是“单 entry 止损”：

- 一条 open entry 对应一条可配置止损对象
- 同一 broker order 下多笔 fill 聚合成一个 entry 时，TPSL 默认只看到一条止损对象
- 只有真正形成多个 open entries 时，TPSL 才会出现多行止损

若同一 tick 同时命中 symbol 级全仓止损和 entry 级止损，当前固定是全仓止损优先，只生成一次全仓止损 batch。

止损命中事件当前会显式区分：

- `symbol_full_stoploss_hit`
- `entry_stoploss_hit`

## entry ledger / compat

- `entry_ledger`
  - 主读模型，来自 `om_position_entries + om_entry_slices`
- `stock_fills_compat`
  - 仅兼容旧接口/旧脚本
  - 不再定义 TPSL 主页面真值

## 页面布局

TPSL 当前不再保留独立 `/tpsl` 页面入口；相关信息已经分散并入以下正式页面：

- `/position-management`
  - 作为统一仓位与排障入口，承载 `聚合买入列表 / 按持仓入口止损`、切片明细、相关订单、对账结果与 Resolution
- `/kline-slim`
  - 承载 symbol 级设置、止盈 profile 与运行态摘要

## 部署

- 改动 `freshquant/tpsl/**`
  - 重建 API Server
  - 重启 `tpsl.tick_listener`

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
