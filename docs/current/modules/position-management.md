# 仓位管理

## 职责

仓位管理负责把券商账户真值、策略阈值和订单账本解释结果转换成可消费的门禁结论。它不负责下单，也不定义订单账本本身。

当前正式真值边界：

- 券商真值
  - `xt_positions`
  - `pm_symbol_position_snapshots`
- 账本解释
  - `om_position_entries`
  - `om_reconciliation_gaps / om_reconciliation_resolutions`

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
- Web UI
  - `/position-management`

## 当前页面读模型

`/api/position-management/dashboard` 当前聚合返回：

- 配置 inventory
- 当前 `raw_state / effective_state / stale`
- 最新资产摘要
- 单标的仓位上限摘要行
- 当前规则矩阵
- 最近决策摘要

最近决策与上下文已合并为一张高密度 ledger。最近决策中的实时市值、仓位上限、市值来源、数量来源都会做系统真值回填；如果历史记录缺字段，后端会用当前 broker snapshot、symbol limit 和 tracked scope 做系统真值回填。

最近决策 ledger 默认分页 `100` 条，表体默认显示约 `15` 行。

## 当前真值语义

### 券商仓位

当前仓位真值只认 `xt_positions`：

- `quantity`
  - `xt_positions.volume`
- `available_quantity`
  - `xt_positions.can_use_volume`
- `avg_price`
  - `xt_positions.avg_price`
- `market_value`
  - `xt_positions.market_value`

### 账本仓位

账本仓位来自 `om_position_entries` 聚合，不再使用 `om_buy_lots` 或 `stock_fills` 兼容镜像定义当前仓位真值。

当前 dashboard 会聚合：

- `explained_quantity`
- `entry_count`
- `execution_backed_quantity`
- `auto_reconciled_quantity`
- `entry_cost_basis`

### 对账状态

对账状态来自：

- `om_reconciliation_gaps`
- `om_reconciliation_resolutions`
- `om_ingest_rejections`

页面右侧当前正式只展示：

- `券商仓位`
- `账本仓位`
- `对账状态`

这里的正式对照语义是：`券商真值 / 账本仓位 / reconciliation`。页面展示文案对应为 `券商仓位 / 账本仓位 / 对账状态`，不再返回三套并列仓位真值。

## tracked scope

单标的仓位上限摘要行只保留 tracked scope 内的 symbol：

- 当前持仓股
- `must_pool`
- `stock_pools`
- `pre_pools`

脏数据只要不在持仓股、must_pool、stock_pools、pre_pools 中，就不会进入“单标的仓位上限覆盖”。

## 页面组织

`/position-management` 当前已切到统一的 workbench density 语法：

- 页面顶部不再保留“仓位管理”标题卡片
- 三栏摘要区上移到“最近决策与上下文”上方
- 顶部双栏当前恢复等高面板
- 顶部双栏都改为面板内竖向滚动
- 当前仓位状态与参数 inventory 已合并为左栏
- 参数 inventory 保持“可编辑阈值 + 只读参数”边界，参数 inventory 的说明列已经压缩成紧凑文案，不再单独占一整列解释块
- 规则矩阵已并入“当前仓位状态”
- 持仓范围卡片已移除
- 当前命中规则说明改成与资产摘要同层级的紧凑指标卡
- 当前命中规则说明与“可用保证金”等小指标卡保持同尺寸
- 最近决策与上下文已合并为一张高密度 ledger

右栏“单标的仓位上限覆盖”当前集中展示：

- 单标的上限设置
- 操作
- 当前来源
- 一致性
- 门禁
- 券商仓位
- 账本仓位
- 对账状态

其中：

- 系统默认值列已移除，`操作` 列挪到 `当前来源` 前
- 单标的仓位上限覆盖输入框默认展示当前生效值
- 保存值等于系统默认值时，后端会自动删除 override
- 金额统一按“万”展示
- 单标的仓位上限覆盖当前只展示持仓股
- 整体按券商真值仓位市值从大到小排序

右栏三列布局当前规则：

- 券商仓位、账本仓位、对账状态三列会扩展占满右栏剩余宽度
- 账本仓位 / 对账状态内容统一左对齐
- 表头与数据行共用固定列宽，避免右侧三列在长来源文本下发生错位

## 单标的上限

单标的实时仓位上限当前统一使用“系统默认值兜底 + 显式 override”语义：

- 默认值写在 `pm_configs.thresholds.single_symbol_position_limit`
- 单标的覆盖值写在 `pm_configs.symbol_position_limits.overrides.<symbol>`
- 没有 override 时，实际生效值天然等于系统默认值
- buy gate 只看 `effective_limit`

## 排障

### 页面上券商仓位和账本仓位不一致

- 先看 `xt_positions`
- 再看 `pm_symbol_position_snapshots`
- 再看 `om_position_entries`
- 最后看 `om_reconciliation_gaps / om_reconciliation_resolutions`

### 某个 symbol 一直异常

- 查 `om_reconciliation_gaps.state`
- 查最近 `resolution_type`
- 查是否存在 `om_ingest_rejections.reason_code=non_board_lot_quantity`

### 单标的上限覆盖保存后不生效

- 查 `pm_configs.thresholds.single_symbol_position_limit`
- 查 `pm_configs.symbol_position_limits.overrides`
- 查 dashboard 返回的 `effective_limit`
