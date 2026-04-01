# 标的管理

## 职责

标的管理把单标的的配置、运行态和退出语义收口到一个工作台。当前页面负责：

- `must_pool` 基础配置
- 单标的仓位上限设置
- `position entry` 级止损绑定
- Guardian / 止盈 / 仓位门禁 / 对账摘要只读展示

页面不再使用 `buy_lot` 作为主编辑对象。

## 入口

- 前端路由
  - `/subject-management`
- 后端接口
  - `/api/subject-management/overview`
  - `/api/subject-management/<symbol>`
  - `/api/subject-management/<symbol>/must-pool`
  - `/api/subject-management/<symbol>/guardian-buy-grid`
  - `/api/position-management/symbol-limits/<symbol>`
  - `/api/order-management/stoploss/bind`

## 当前依赖

- `must_pool`
- `guardian_buy_grid_configs`
- `guardian_buy_grid_states`
- `om_takeprofit_profiles`
- `om_takeprofit_states`
- `om_position_entries`
- `om_entry_stoploss_bindings`
- `om_reconciliation_gaps / om_reconciliation_resolutions`
- `xt_positions`
- `pm_symbol_position_snapshots`

## 当前读模型

### overview

`/api/subject-management/overview` 当前汇总：

- `must_pool`
- Guardian 配置
- 止盈 profile
- 当前持仓与运行态
- entry 级止损摘要
- 单标的仓位上限摘要

overview 里的“单标的仓位上限摘要”当前按批量 PM dashboard 结果一次性装载，不再按 symbol 重复调用单标的 limit 读路径。

左表 symbol 集合当前只来自：

- `must_pool`
- 当前持仓聚合

Guardian 配置、止盈 profile、entry 级止损摘要和最近触发事件只作为这些标的的补充信息，不再把“仅残留配置、但不在持仓且不在 must_pool”的孤儿标的带进页面。

### detail

`/api/subject-management/<symbol>` 当前返回：

- `must_pool`
- `guardian_buy_grid_config`
- `guardian_buy_grid_state`
- `runtime_summary`
- `takeprofit`
- `position_management_summary`
- `position_limit_summary`
- `entries`

当前 detail 已不再返回 `buy_lots` 字段。

每条 `entry` 当前会内嵌自己的 `stoploss` 绑定摘要。

## 止损语义

页面上的“单笔止损”当前实际是 `position entry` 级止损：

- 绑定接口只接受 `entry_id`
- 表格默认展示 open entries
- 行内摘要当前与 `KlineSlim` 共用同一套 entry 展示口径，显示：
  - 买入价
  - 买入数量
  - 剩余数量与比例
  - 买入时间
  - 剩余市值

## 排序

左表当前按运行态仓位金额从大到小排序，排序口径与 `KlineSlim` 持仓股和 `PositionManagement` 单标的上限表保持一致。

## 当前边界

- 可编辑
  - `must_pool` 基础配置
  - 单标的仓位上限 override
  - entry stoploss
- 只读
  - Guardian 阶梯价
  - 止盈 profile / state
  - 仓位门禁状态
  - 对账状态

Guardian / 止盈的真实编辑入口仍在 `/kline-slim`。

## 部署

- 改动 `/api/subject-management/*`
  - 重建 API Server
- 改动 `/subject-management`
  - 重建 Web UI

## 排障

### 左表和右栏不一致

- 先查 `/api/subject-management/overview`
- 再查 `/api/subject-management/<symbol>`
- 再查 `om_position_entries / om_entry_stoploss_bindings`

### 止损保存后未生效

- 查 `/api/order-management/stoploss/bind` 返回
- 查 `om_entry_stoploss_bindings`
- 确认目标 `entry_id` 仍处于 open 状态

### 某只股票显示异常 entry

- 查 `om_position_entries`
- 查 `om_reconciliation_gaps / om_reconciliation_resolutions`
- 查 `om_ingest_rejections`
