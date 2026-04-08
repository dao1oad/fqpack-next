# 标的管理

## 职责

标的管理把单标的的配置、运行态和退出语义收口到一个工作台。当前页面负责：

- `must_pool` 基础配置
- symbol 级 `全仓止损价`
- 单标的仓位上限设置
- `position entry` 级止损绑定
- Guardian / 止盈 / 仓位门禁 / 对账摘要只读展示

页面不再使用 `buy_lot` 作为主编辑对象。

## 入口

- 前端
  - 独立 Web UI 路由已移除
  - `PositionManagement` 中栏 `PositionSubjectOverviewPanel` 当前直接复用 `SubjectManagement` 的读模型与交互控制器
  - 仓内仍保留 `SubjectManagement.vue` 与对应读模型，供迁移期复用
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
- 止盈 profile / state
- 当前持仓与运行态
- entry 级止损摘要
- 单标的仓位上限摘要

overview 的 `runtime` 当前返回：

- `position_quantity`
- `position_amount`
- `avg_price`
- `last_hit_level`
- `last_trigger_kind`
- `last_trigger_level`
- `last_trigger_time`
- `last_takeprofit_trigger_level`
- `last_takeprofit_trigger_time`
- `last_entry_stoploss_trigger_time`

overview 里的“单标的仓位上限摘要”当前按批量 PM dashboard 结果一次性装载，不再按 symbol 重复调用单标的 limit 读路径。

当前批量装载口径直接读取 `GET /api/position-management/dashboard` 返回里的 `symbol_position_limits.rows`。

左表 symbol 集合当前只来自：

- `must_pool`
- 当前持仓聚合

Guardian 配置、止盈 profile、entry 级止损摘要和最近 TPSL 触发事件只作为这些标的的补充信息，不再把“仅残留配置、但不在持仓且不在 must_pool”的孤儿标的带进页面。

### detail

`/api/subject-management/<symbol>` 当前返回：

- `must_pool`
- `guardian_buy_grid_config`
- `guardian_buy_grid_state`
- `runtime_summary`
- `takeprofit`
- `position_management_summary`
- `position_limit_summary`
- `base_config_summary`
- `entries`

当前 detail 已不再返回 `buy_lots` 字段。

每条 `entry` 当前会内嵌：

- `stoploss` 绑定摘要
- `aggregation_members`
- `aggregation_window`
- `entry_slices`
- `latest_price / latest_price_source`
- `remaining_market_value / remaining_market_value_source`

`base_config_summary` 当前为中栏“标的总览”里的“基础配置 + 单标的仓位上限”提供正式读模型，字段统一区分：

- `configured_value`
- `effective_value`
- `effective_source`

当前生效口径固定为：

- `category`
  - 显式配置只认原始 `must_pool.manual_category / must_pool.category`
  - 若只有 provenance / memberships 推导出的分类，页面仍显示当前值，但状态保持 `未配置`，来源标成 provenance
  - 原始字段缺失时不再误标成 `must_pool.category`
- `stop_loss_price`
  - 只认 `must_pool.stop_loss_price`
  - 缺失时显示 `未配置`
- `initial_lot_amount`
  - `must_pool.initial_lot_amount`
  - 否则回退 `must_pool.lot_amount`
  - 再否则回退 Guardian 默认首次开仓金额 `100000`
- `lot_amount`
  - `instrument_strategy.lot_amount`
  - 否则回退 `must_pool.lot_amount`
  - 再否则回退 `guardian.stock.lot_amount`

其中 `instrument_strategy.lot_amount` 当前要与 Guardian 运行时 `get_trade_amount(symbol)` 口径保持一致；不会因为存在仅带 `.SH/.SZ` 后缀的单独记录，就在页面里误判成当前生效值。

标的总览里的“当前生效”摘要当前必须明确展示来源；缺失配置不再渲染为空白。

当前中栏 / 旧页面共享的基础配置标签口径为：

- `首笔买入金额`
- `默认买入金额`
- `单标的仓位上限`

其中“默认买入金额”必须和 `lot_amount` / `instrument_strategy.lot_amount` / `guardian.stock.lot_amount` 这一条运行口径保持一致，不能和单标的仓位上限混淆。
这两类买入金额当前不再放在 `PositionSubjectOverviewPanel` 主表里行内编辑，而是统一收口到 `/system-settings -> 交易控制 / 策略 -> Guardian`：

- `首笔买入金额`
  - 当前展示的是运行默认值 `DEFAULT_INITIAL_LOT_AMOUNT = 100000`
  - 在系统设置页里按只读项展示，不伪装成可配置 Mongo 参数
- `默认买入金额`
  - 当前对应 `guardian.stock.lot_amount`
  - 在系统设置页里继续作为正式可编辑系统项展示

当前 `overview` 与 `detail` 在最近 TPSL 触发字段上已经统一：

- overview 展示 `runtime.last_trigger_kind + runtime.last_trigger_level + runtime.last_trigger_time`
- detail 展示 `runtime_summary.last_trigger_kind + runtime_summary.last_trigger_level + runtime_summary.last_trigger_time`
- overview / detail 额外分别返回：
  - `last_takeprofit_trigger_level + last_takeprofit_trigger_time`
  - `last_entry_stoploss_trigger_time`

`PositionSubjectOverviewPanel` 主表当前会把 TPSL 与 Guardian 两类触发分开显示：

- `Guardian 层级触发`
- `止盈层级触发`
- `单笔止损触发`

不再把 Guardian 命中信息混排进 `Guardian 买入层级（配置）` 列。
Guardian 最近命中时间当前正式来源是 `guardian_buy_grid_states.last_hit_signal_time`；对历史 legacy 状态，如果该字段缺失但 `last_hit_level` 仍存在，overview / detail 会先回退使用同一条 state 的 `updated_at` 作为展示时间。

当前 `guardian_buy_grid_state` 的正式真义是：
- `buy_enabled`
  - 配置态，来自 `guardian_buy_grid_configs`
- `buy_active`
  - 运行态，来自 `guardian_buy_grid_states`
- 若 detail 读取不到 `guardian_buy_grid_state`
  - 后端会按 `buy_active=[false,false,false]` 归一化返回
  - `kline-slim` 的 Guardian 运行态因此显示为未激活
  - `PositionSubjectOverviewPanel` 中的 `Guardian 买入层级（配置）` 仍然只展示配置态，不与运行态混淆

当前 `takeprofit.state` 的正式真义是：
- `manual_enabled`
  - 配置态，来自 `om_takeprofit_profiles.tiers[*].manual_enabled`
- `armed_levels`
  - 运行态，来自 `om_takeprofit_states`
- 若 overview / detail 读取不到 `takeprofit state`
  - 后端会按各层 `armed_levels[level]=false` 归一化返回
  - `PositionSubjectOverviewPanel` 与 `kline-slim` 都把该层视为未激活，不再把缺 key 当成 `开`
止盈层级触发的数据来自 TPSL 最近止盈退出事件，当前语义固定是：

- `takeprofit`
  - 优先显示最近命中的 `L1 / L2 / L3`
  - 如果事件里没有 level，再回退显示 `止盈`

单笔止损触发的数据来自 TPSL 最近 entry 级止损退出事件，当前只认：

- `entry_stoploss_hit`
- `stoploss_hit`

不混入 `symbol_full_stoploss_hit`，避免和全仓止损语义混淆。
三列触发当前统一按单行显示：`事件标签 + 触发时间`。
若止盈 state 的 `last_rearm_reason = new_buy_below_lowest_tier`，且 `last_rearmed_at` 晚于最近一次止盈事件，则 overview / detail 都会清空止盈触发字段，表示当前买入周期已经重置，不再继续显示上一个周期的最近止盈触发。

## 止损语义

标的总览里的 `全仓止损价` 当前正式对应 `must_pool.stop_loss_price`：

- 读模型来源是 `base_config_summary.stop_loss_price`
- TPSL 命中时会生成 symbol 级 `FullPositionStoploss`
- 卖出该 symbol 下全部可卖 open entry slices
- 若同一 tick 同时命中全仓止损和单笔止损，当前固定是全仓止损优先

页面上的“单笔止损”当前实际是 `position entry` 级止损：

- 绑定接口只接受 `entry_id`
- 表格默认展示 open entries
- 行内摘要当前与 `KlineSlim` 共用同一套 entry 展示口径，显示：
  - 买入价
  - 买入数量
  - 剩余数量与比例
  - 买入时间
  - 剩余市值

`SubjectManagement` 读模型当前承载 entry 级切片检查语义；独立路由已下线，但组件和读模型仍保留：

- `PositionSubjectOverviewPanel` 当前在每个 symbol 行内直接展示聚合后的 open entry 列表，并按行编辑 / 保存止损
- `PositionManagement` 右上工作区当前使用“聚合买入列表 / 按持仓入口止损 -> 切片明细”的主从联动
- `entry_slices` 当前只展示当前选中 entry 的切片，不再通过悬浮框一次性展开全部切片
- “剩余市值”优先按有效 `latest_price * remaining_quantity`
- 若 `latest_price <= 0` 或缺失，则优先用 `xt_positions.market_value / quantity` 推导有效最新价
- 若仍无有效最新价，再回退 `avg_price * remaining_quantity`

## 排序

标的总览当前按运行态仓位金额从大到小排序，排序口径与 `KlineSlim` 持仓股和 `PositionManagement` 中栏表保持一致。

## 当前边界

- 可编辑
  - `must_pool` 基础配置
  - 单标的仓位上限 override
  - entry stoploss
- 只读
  - Guardian 阶梯价
    - 标的总览概览列当前展示 `B1 / B2 / B3`
- 止盈 profile / state
    - 标的总览概览列当前展示 `L1 / L2 / L3`
    - “开/关”当前按 `manual_enabled && armed_levels[level]` 合成真实运行态，只有系统当前仍会触发该层止盈时才显示 `开`
    - 缺失 `takeprofit state` 时，当前统一按未激活处理
  - 仓位门禁状态
    - 当前仍在 detail / 摘要只读展示
    - 不再占用 `PositionSubjectOverviewPanel` 主表列
  - 对账状态

Guardian / 止盈的真实编辑入口仍在 `/kline-slim`。

## 部署

- 改动 `/api/subject-management/*`
  - 重建 API Server
- 改动 `SubjectManagement.vue`
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
