# 仓位管理

## 职责

仓位管理负责把券商账户真值、策略阈值和订单账本解释结果转换成可消费的门禁结论。它不负责下单，也不负责账本修复。

当前正式真值边界：

- 券商真值
  - `xt_positions`
  - `pm_symbol_position_snapshots`
- 账本解释
  - `om_position_entries`
  - `om_entry_slices`
  - `stock_fills_compat`
  - `/api/stock_fills` 当前 open position 投影
- 对账解释
  - `om_reconciliation_gaps`
  - `om_reconciliation_resolutions`
  - `om_ingest_rejections`

## 入口

- worker
  - `python -m freshquant.xt_account_sync.worker --interval 15`
- HTTP
  - `GET /api/position-management/dashboard`
  - `GET /api/position-management/config`
  - `POST /api/position-management/config`
  - `GET /api/position-management/symbol-limits`
  - `GET /api/position-management/symbol-limits/<symbol>`
  - `POST /api/position-management/symbol-limits/<symbol>`
  - `GET /api/position-management/reconciliation`
  - `GET /api/position-management/reconciliation/<symbol>`
- Web UI
  - `/position-management`

## 页面组织

`/position-management` 当前是统一两栏工作台：

- 左栏：当前仓位状态 + 标的总览
- 右栏：选中标的工作区 + 最近决策与上下文

规则矩阵已并入“当前仓位状态”。当前仓位状态已放到“标的总览”上方，因此桌面端不再保留旧的三栏壳和单独的对账入口卡片。

inventory 参数表已从本页移除，去重后的只读补充项已并入 `/system-settings`；本页只保留当前仓位状态、标的总览、选中标的工作区和最近决策。

左栏“标的总览”当前不再展示独立的“单标的仓位上限覆盖”列表，而是把下面三类能力收口到同一张高密度主表：

- `must_pool` 基础配置
- 单标的仓位上限 override
- 标的摘要与运行态

当前高密度主表固定横向展示关键字段，不再把基础配置按纵向卡片拆开：

- `持仓`
  - 合并展示 `持仓股数 + 持仓市值`
- `订单状态`
  - 合并展示 `活跃单笔止损 + Open Entry`
- `全仓止损价`
- `单标的仓位上限`

左栏列表当前额外保留两组只读概览列，便于不用切进 `KlineSlim` 也能快速核对当前价格导引：

- `Guardian 层级触发`
  - 单独展示最近 Guardian 命中层级与命中时间
  - 数据来自 `guardian.last_hit_level + guardian.last_hit_signal_time`
  - 对旧状态数据，如果 `last_hit_level` 已存在但 `last_hit_signal_time` 缺失，当前展示层会先回退到该 Guardian state 的 `updated_at`
- `止盈层级触发`
  - 只展示最近一次止盈事件的 `L1 / L2 / L3 + 时间`
  - 如果止盈事件没有层级，则回退显示 `止盈 + 时间`
  - 数据来自 TPSL 最近 `takeprofit` 退出事件
  - 若止盈 state 的 `last_rearm_reason = new_buy_below_lowest_tier`，且 `last_rearmed_at` 晚于最近一次止盈事件，则该列清空，表示当前买入周期已重置
- `单笔止损触发`
  - 只展示最近一次 entry 级止损事件的 `止损 + 时间`
  - 当前只认 `entry_stoploss_hit / stoploss_hit`，不混入 symbol 级全仓止损
- `Guardian 层级触发 / 止盈层级触发 / 单笔止损触发`
  - 三列统一使用单行样式：`事件标签 + 触发时间`
  - 事件与时间不再拆成两行
- `Guardian 买入层级`
  - 展示 `B1 / B2 / B3` 三层 Guardian 价格与每层启用状态
- `止盈价格层级`
  - 展示 `L1 / L2 / L3` 三层止盈价与每层真实运行态
  - 状态真值当前按 `manual_enabled && armed_levels[level]` 计算；只有系统当前真的还会触发该层止盈时才显示 `开`

`Guardian 买入层级` 与 `止盈价格层级` 这两列当前都使用相同的三段式布局：

- 左侧层级编号
- 中间价格
- 右侧开关状态

开关统一右对齐，关闭态当前固定用红色显示，便于按行横向比对。

`Guardian 买入层级 / 止盈价格层级 / Guardian 层级触发 / 止盈层级触发 / 单笔止损触发` 这几列当前会优先吃掉主表剩余横向空间。

左栏主表当前列顺序固定为：

- `标的`
- `持仓`
- `订单状态`
- `Guardian 买入层级`
- `止盈价格层级`
- `Guardian 层级触发`
- `止盈层级触发`
- `单笔止损触发`
- `全仓止损价`
- `单标的仓位上限`
- `保存`

桌面宽度下当前目标是不再出现横向滚动条。

`首笔买入金额 / 默认买入金额` 当前已从标的总览主表移除，统一收口到 `/system-settings -> 交易控制 / 策略 -> Guardian`。

中栏前端组件是 `PositionSubjectOverviewPanel`；它直接复用：

- `/api/subject-management/overview`
- `/api/subject-management/<symbol>`
- `/api/subject-management/<symbol>/must-pool`
- `/api/position-management/symbol-limits/<symbol>`
- `/api/order-management/stoploss/bind`

标的总览默认按持仓优先、仓位市值从大到小排序。

默认选中首个标的并驱动右栏联动。

选中标的工作区当前固定拆成上下两张高密度表：

- 上半区：`聚合买入列表 / 按持仓入口止损`
  - 固定列为：`入口 / 买入时间 / 买入价 / 买入数量 / 剩余 / 占比 / 市值 / 单笔止损`
  - `入口` 当前只展示 `序号 + entry id` 的紧凑单行标签
  - `买入时间 / 剩余 / 占比` 当前固定单行展示，不再换行
  - 不再单独展示 `聚合买入` 列
- 下半区：`切片明细`
  - `入口` 列当前也只展示 `序号 + entry id`
  - `入口` 同样固定单行展示，便于压缩右栏宽度

右上工作区会为每个 symbol 维护当前选中的 open entry；首次进入 symbol 时默认选中第一条 entry，`切片明细` 只展示当前选中 entry 的 `entry_slices`，不再一次性铺开全部切片。

右栏下半区继续展示最近决策与上下文，但当前不再跟选中 symbol 联动；它固定展示所有标的的最近决策，并按 `evaluated_at` 从近到远排序。

单标的实时仓位上限当前统一使用“系统默认值兜底 + 显式 override”语义：

- 默认值写在 `pm_configs.thresholds.single_symbol_position_limit`
- 单标的覆盖值写在 `pm_configs.symbol_position_limits.overrides.<symbol>`
- 没有 override 时，实际生效值天然等于系统默认值
- buy gate 只看 `effective_limit`

标的总览行内保存时，如果覆盖值等于系统默认值，后端仍会自动删除 override。

最近决策与上下文已切换成和标的总览一致的 `el-table`。最近决策中的实时市值、仓位上限、市值来源、数量来源都会做系统真值回填；如果历史记录缺字段，后端会用当前 broker snapshot、symbol limit 和 tracked scope 做系统真值回填。

该表支持手动拖列；显示不下时使用横向滚动条。

最近决策表格默认分页 `100` 条，表体默认显示约 `15` 行。

左栏 `全仓止损价` 当前直接展示 `base_config_summary.stop_loss_price.effective_value`，运行时语义由 TPSL 的 symbol 级全仓止损承担；`活跃单笔止损` 只统计 entry 级 stoploss 绑定数量。

## 对账工作台

`/position-management` 当前不再直接展示旧对账视图；对账、相关订单、Entry / Slice、gap / resolution / rejection 已统一迁到独立路由 `/reconciliation`。

`/reconciliation` 当前使用以下只读接口：

- `GET /api/position-management/reconciliation`
- `GET /api/position-management/reconciliation/<symbol>`
- `GET /api/position-management/reconciliation-workspace/<symbol>`

一致性检查只读，不负责修复，不会触发 compat sync、reconcile、repair、rebuild 或任何写操作。`/position-management` 当前只保留对账中心的概念链接，不再内嵌任何对账入口模块。

## 排障

### 需要查看对账或订单链

- 直接进入 `/reconciliation`
- 需要带上下文时，使用 `?symbol=<symbol>`
- 在 `/reconciliation` 里继续看 `概览 / 相关订单 / 持仓账本 / Resolution`

### 某个 symbol 一直异常

- 查 `om_reconciliation_gaps.state`
- 查最近 `resolution_type`
- 查是否存在 `om_ingest_rejections.reason_code=non_board_lot_quantity`

### 单标的上限覆盖保存后不生效

- 查 `pm_configs.thresholds.single_symbol_position_limit`
- 查 `pm_configs.symbol_position_limits.overrides`
- 查 dashboard 返回的 `effective_limit`
