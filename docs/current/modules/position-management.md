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

`/position-management` 当前是统一三栏工作台：

- 左栏：当前仓位状态 + 对账检查
- 中栏：标的总览
- 右栏：选中标的工作区 + 最近决策与上下文

当前仓位状态与参数 inventory 已合并为左栏，规则矩阵已并入“当前仓位状态”。左栏仍可编辑全局阈值：

- `allow_open_min_bail`
- `holding_only_min_bail`
- `single_symbol_position_limit`

中栏“标的总览”当前不再展示独立的“单标的仓位上限覆盖”列表，而是把下面三类能力收口到同一张高密度主表：

- `must_pool` 基础配置
- 单标的仓位上限 override
- 标的摘要与运行态

当前高密度主表固定横向展示关键字段，不再把基础配置按纵向卡片拆开：

- `全仓止损价`
- `开仓数量`
- `默认买入金额`
- `活跃单笔止损`

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
- 下半区：`切片明细`

右上工作区会为每个 symbol 维护当前选中的 open entry；首次进入 symbol 时默认选中第一条 entry，`切片明细` 只展示当前选中 entry 的 `entry_slices`，不再一次性铺开全部切片。

右栏下半区继续展示最近决策与上下文，但当前不再跟选中 symbol 联动；它固定展示所有标的的最近决策，并按 `evaluated_at` 从近到远排序。

单标的实时仓位上限当前统一使用“系统默认值兜底 + 显式 override”语义：

- 默认值写在 `pm_configs.thresholds.single_symbol_position_limit`
- 单标的覆盖值写在 `pm_configs.symbol_position_limits.overrides.<symbol>`
- 没有 override 时，实际生效值天然等于系统默认值
- buy gate 只看 `effective_limit`

标的总览行内保存时，如果覆盖值等于系统默认值，后端仍会自动删除 override。

最近决策与上下文已合并为一张高密度 ledger。最近决策中的实时市值、仓位上限、市值来源、数量来源都会做系统真值回填；如果历史记录缺字段，后端会用当前 broker snapshot、symbol limit 和 tracked scope 做系统真值回填。

最近决策 ledger 默认分页 `100` 条，表体默认显示约 `15` 行。

中栏 `全仓止损价` 当前直接展示 `base_config_summary.stop_loss_price.effective_value`，运行时语义由 TPSL 的 symbol 级全仓止损承担；`活跃单笔止损` 只统计 entry 级 stoploss 绑定数量。

## 对账检查面板

`对账检查面板` 对应 `GET /api/position-management/reconciliation` 和 `GET /api/position-management/reconciliation/<symbol>`。

一致性检查只读，不负责修复，不会触发 compat sync、reconcile、repair、rebuild 或任何写操作。它只负责告诉前端哪些视图本应相等却不相等，以及 broker truth 和 ledger explanation 的差异是否被 reconciliation 正确解释。

顶部摘要当前展示：

- `总标的`
- `ERROR / WARN / OK`
- reconciliation 五态计数
- `R1 ~ R4` 每条规则的 `OK / WARN / ERROR` 汇总

dense ledger 当前展示：

- `标的`
- `检查结果`
- `对账状态`
- `latest resolution`
- `signed gap`
- `open gap`
- `mismatch` 摘要
- `broker / snapshot / entry` 关键视图摘要

行展开证据当前展示：

- `R1 ~ R4` 逐规则检查 badge
- `mismatch_codes` 的中文解释
- `broker / snapshot / entry_ledger / slice_ledger / compat_projection / stock_fills_projection` 六个 evidence surface
- `reconciliation.state`
- `signed gap`
- `open gap`
- 当前可用的 `rule evidence` 数量

### 审计规则

- `R1 broker_snapshot_consistency`
  - 比较 `xt_positions` 与 `pm_symbol_position_snapshots`
  - 预期必须一致
- `R2 ledger_internal_consistency`
  - 比较 `om_position_entries` 与 `om_entry_slices`
  - 预期必须一致
- `R3 compat_projection_consistency`
  - 比较 `om_position_entries`、`stock_fills_compat` 与 `/api/stock_fills` 当前 open position 投影
  - 预期三者应一致
- `R4 broker_vs_ledger_consistency`
  - 比较 `xt_positions` 与 `om_position_entries`
  - 这里不是简单要求数量相等，而是要求差异必须能被 reconciliation 状态正确解释

### 对账状态

当前正式 reconciliation 汇总态有 5 种：

- `ALIGNED`
- `OBSERVING`
- `AUTO_RECONCILED`
- `BROKEN`
- `DRIFT`

当前页面会把 `BROKEN` 和 `DRIFT` 直接标为错误，把 `OBSERVING` 标为警告。

### 当前前后端 contract

后端 `PositionReconciliationReadService` 当前返回的只读 contract 已固定包含：

- `summary.rule_counts`
- `rows[].surface_values`
- `rows[].rule_results`
- `rows[].evidence_sections`

前端 `PositionReconciliationPanel` 只消费这些只读字段，不再把对账逻辑散落在行内可写表单里。

## 排障

### 对账检查出现 ERROR

- 先看 `xt_positions`
- 再看 `pm_symbol_position_snapshots`
- 再看 `om_position_entries`
- 再看 `om_entry_slices`
- 再看 `stock_fills_compat`
- 最后看 `om_reconciliation_gaps / om_reconciliation_resolutions / om_ingest_rejections`

### 某个 symbol 一直异常

- 查 `om_reconciliation_gaps.state`
- 查最近 `resolution_type`
- 查是否存在 `om_ingest_rejections.reason_code=non_board_lot_quantity`

### 单标的上限覆盖保存后不生效

- 查 `pm_configs.thresholds.single_symbol_position_limit`
- 查 `pm_configs.symbol_position_limits.overrides`
- 查 dashboard 返回的 `effective_limit`
