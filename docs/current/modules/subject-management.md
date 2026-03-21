# 标的管理

## 职责

标的管理页面把单标的的主要设置收口到同一工作台：

- `must_pool` 基础设置
- 单标的仓位上限覆盖
- buy lot 级止损绑定
- 只读 Guardian / 止盈 / 运行态与仓位门禁摘要

其中“运行态”里的仓位金额当前统一读取 `position_management.pm_symbol_position_snapshots.market_value`。

页面采用左表右编模式：左侧高密度表格展示当前配置摘要，右侧只编辑当前选中的单个标的。
右侧编辑区采用高密度工作台布局：

- 顶部摘要条压缩展示标的、持仓、Guardian、止盈、止损与仓位门禁摘要
- 左表新增“仓位上限”摘要列，直接展示当前市值、有效上限、来源和是否已阻断
- `基础配置 + 单标的仓位上限` 合并为一张紧凑编辑表
- `按 buy lot 止损` 继续使用一张紧凑编辑表

Guardian 阶梯买入价与止盈价格层级不再在本页编辑，当前统一转到 `/kline-slim` 的浮层面板维护。

## 入口

- 前端路由
  - `/subject-management`
- 前端页面
  - `SubjectManagement.vue`
- 后端接口
  - `/api/subject-management/overview`
  - `/api/subject-management/<symbol>`
  - `/api/subject-management/<symbol>/must-pool`
  - `/api/position-management/symbol-limits/<symbol>`
  - `/api/order-management/stoploss/bind`

## 依赖

- `SubjectManagementDashboardService`
- `SubjectManagementWriteService`
- `GuardianBuyGridService`
- `TpslService`
- `BuyLotStoplossService`
- `PositionManagementDashboardService`

主要事实集合：

- `must_pool`
- `guardian_buy_grid_configs`
- `guardian_buy_grid_states`
- `om_takeprofit_profiles`
- `om_takeprofit_states`
- `om_stoploss_bindings`
- `om_buy_lots`
- `xt_positions`
- `pm_symbol_position_snapshots`

## 数据流

`/subject-management -> /api/subject-management/overview -> 左侧高密度摘要表`

`/api/subject-management/overview` 当前不是只读 `must_pool`；左表 symbol 集合来自 `must_pool + guardian_buy_grid_configs + guardian_buy_grid_states + takeprofit_profiles + positions + stoploss_summary` 的并集

`点击标的 -> /api/subject-management/<symbol> -> 右侧摘要条 + 基础配置/仓位上限表 + 止损表`

`保存基础配置 + 仓位上限 -> must-pool + symbol-limit 两个写接口顺序提交 -> 刷新当前 detail + overview 摘要`

`保存止损 -> /api/order-management/stoploss/bind -> 刷新当前 detail + overview 摘要`

## 当前边界

- 页面只编辑标的级 `must_pool`、单标的仓位上限覆盖和 buy lot 止损，不编辑账户级仓位门禁。
- 仓位门禁只读展示 `effective_state / allow_open_min_bail / holding_only_min_bail`；单标的上限编辑的真值来自 position management。
- 左表“运行态”和右栏 `runtime_summary.position_amount` 使用统一单标的实时仓位定义。
- 左表代码下方的 `持仓 / 观察` 标签不是后端独立字段，而是前端根据 `runtime.position_quantity > 0` 派生：大于 0 显示 `持仓`，否则显示 `观察`
- 当前页面没有“删除标的”动作；某个 symbol 只要仍存在于 overview 的任一来源集合，就会继续显示。要让它从页面消失，必须把该 symbol 从上述所有来源集合里移除
- 止盈编辑区默认至少显示三层；如果已有更高层级，会保留现有层级并继续显示前三层。
- 止损仍按 open buy lot 维护，不提升成纯标的级配置。
- Guardian / 止盈在本页只读展示，不提供保存动作。

## 部署/运行

- 前端改动：重建 `fq_webui`
- `/api/subject-management/*` 改动：重建 `fq_apiserver`
- 仓位上限覆盖保存复用 position management 配置写入，不新增独立 worker
- 止损保存继续复用现有订单管理 worker，不新增独立 worker

## 排障点

### 左表有标的但右栏为空

- 检查 `/api/subject-management/<symbol>` 是否返回 200
- 检查该标的是否存在 symbol 归一失败或名称缺失

### 左表摘要与右栏详情不一致

- 检查保存后是否同时刷新了 detail 和 overview
- 检查 `must_pool / guardian_buy_grid / takeprofit / stoploss` 是否写入到了各自真值集合
- 检查 `pm_symbol_position_snapshots` 是否已经刷新到最新 `market_value`

### 止损保存后未生效

- 检查对应 `buy_lot_id` 是否仍为 open 状态
- 检查 `/api/order-management/stoploss/bind` 返回是否成功
- 检查 `om_stoploss_bindings` 中的 `enabled / stop_price / ratio` 是否已更新

### 左表仓位上限摘要或右栏仓位上限不一致

- 检查 `/api/subject-management/overview` 与 `/api/subject-management/<symbol>` 是否都带了 `position_limit_summary`
- 检查 `pm_configs.thresholds.single_symbol_position_limit` 与 `pm_configs.symbol_position_limits.overrides` 是否符合预期
- 检查 `pm_symbol_position_snapshots.market_value` 是否已刷新
