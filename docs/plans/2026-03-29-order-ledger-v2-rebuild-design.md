# 订单账本 V2 全量重建设计

## 背景

当前线上 Mongo 仍然是旧订单账本主导，正式 V2 结构没有真正落地：

- `om_trade_facts = 561`
- `om_buy_lots = 309`
- `om_lot_slices = 553`
- `om_external_candidates = 556`
- `om_position_entries / om_entry_slices / om_exit_allocations / om_reconciliation_resolutions` 为空或不存在

同时仍存在历史脏数据：

- `om_trade_facts` 缺 `date/time` 的记录：`12`
- `om_buy_lots` 缺 `date/time` 的记录：`12`
- `om_lot_slices` 缺 `date/time` 的记录：`132`

这说明当前系统是“新代码 + 老数据”的混合态。继续只补 `date/time` 只能修表象，不能把账本真正切换到新架构。

## 目标

- 清空订单账本相关集合，只保留券商原始真值集合。
- 以 `xt_orders + xt_trades + xt_positions` 为唯一输入，重建正式 V2 账本。
- 让 TPSL、SubjectManagement、KlineSlim、PositionManagement 统一消费 `position entry / reconciliation`。
- 保证重建后所有正式 entry / slice 都有完整 `date/time`，且与券商当前持仓收敛一致。

## 非目标

- 不保留旧 `external_inferred` 的历史语义。
- 不恢复券商无法证明的 `trace_id / intent_id / strategy_name / scope` 历史细节。
- 不尝试把 odd-lot 历史成交伪装成合法 board-lot entry。

## 正式真值边界

### 输入真值

只认下列券商原始集合：

- `xt_orders`
- `xt_trades`
- `xt_positions`

### 重建目标集合

重建后的正式账本只保留：

- `om_broker_orders`
- `om_execution_fills`
- `om_position_entries`
- `om_entry_slices`
- `om_exit_allocations`
- `om_reconciliation_gaps`
- `om_reconciliation_resolutions`
- `om_order_requests`
- `om_order_events`
- `om_ingest_rejections`

### 清空并退出主链的集合

以下集合在重建时清空；其中 legacy 集合只作为过渡兼容，不再承担正式语义：

- `om_order_requests`
- `om_order_events`
- `om_orders`
- `om_broker_orders`
- `om_trade_facts`
- `om_execution_fills`
- `om_buy_lots`
- `om_position_entries`
- `om_lot_slices`
- `om_entry_slices`
- `om_sell_allocations`
- `om_exit_allocations`
- `om_external_candidates`
- `om_reconciliation_gaps`
- `om_reconciliation_resolutions`
- `om_stoploss_bindings`
- `om_entry_stoploss_bindings`
- `om_ingest_rejections`

### 不动的集合

- `xt_orders`
- `xt_trades`
- `xt_positions`
- `pm_*`

## 重建算法

### 第 1 步：冻结输入快照

在重建窗口开始时读取并冻结：

- 全量 `xt_orders`
- 全量 `xt_trades`
- 全量 `xt_positions`

同一轮重建只使用这批快照，不允许一边重建一边继续 ingest 新回报。

### 第 2 步：清空订单账本

先备份待清理的 `om_*` 集合到时间戳备份库，再清空正式订单账本集合。  
重建失败时只支持“整库回滚”，不做部分回滚。

### 第 3 步：重建 broker order / execution fill

- 按 `xt_orders.order_id` 建 `om_broker_orders`
- 按 `xt_trades.traded_id` 建 `om_execution_fills`
- 若某笔 `xt_trade` 找不到 `xt_order`，生成 `trade_only` broker order
- `date/time` 一律从 `traded_time` 或 `order_time` 按北京时间推导

### 第 4 步：重建 position entry / entry slice / exit allocation

- 所有 `buy` 成交先按 `broker_order_id` 聚合
- 每个聚合买单生成一个 `position_entry`
- 每个 `position_entry` 再按 Guardian 规则生成 `entry_slices`
- 所有 `sell` 成交按时间顺序回放，分摊到 open `entry_slices`
- 回放后的 `remaining_quantity` 构成“历史成交可解释仓位”

### 第 5 步：对齐 xt_positions，补 reconciliation

对每个 symbol 计算：

- `ledger_remaining_quantity`
- `broker_quantity = xt_positions.volume`
- `delta = broker_quantity - ledger_remaining_quantity`

处理规则：

- `delta == 0`
  - 不生成补偿
- `delta > 0`
  - 若 `delta % 100 == 0`，生成 `auto_reconciled_open entry`
  - 价格取 `xt_positions.avg_price`
  - 时间取本次重建时间
- `delta < 0`
  - 若 `abs(delta) % 100 == 0`，生成 `auto_reconciled_close allocation`
  - 按 open `entry_slices` 规则扣减
- `delta % 100 != 0`
  - 不进入主账本
  - 生成 `REJECTED reconciliation gap`
  - 同时写 `om_ingest_rejections`

### 第 6 步：重建最小 request/event skeleton

`om_order_requests / om_order_events` 只恢复 broker 可证明的最小骨架：

- `source = broker_rebuild`
- `request_id / internal_order_id` 采用稳定可重建规则
- 不恢复旧系统无法由券商真值证明的字段

## 日期与时间规则

- 所有正式 `execution_fill / position_entry / entry_slice` 都必须有完整 `date/time`
- 北京时间作为统一展示和持久化推导时区
- `trade_time` 为秒级 Unix timestamp，`date/time` 为其派生字段
- 不再接受“只写 `trade_time`，读时临时回填”的长期状态

## Odd-Lot 与异常规则

- 任何非 `100` 整数倍成交都不允许生成 `position_entry`
- 任何非 `100` 整数倍 reconciliation delta 都不允许进入主账本
- odd-lot 只进入：
  - `om_execution_fills` 审计层
  - `om_ingest_rejections`
  - `om_reconciliation_gaps(state=REJECTED)`

## 读侧语义

### TPSL

- 正式语义改为“单笔持仓入口止损”
- 所有绑定统一走 `entry_id`
- `auto_reconciled_open entry` 也允许绑定止损

### SubjectManagement / KlineSlim / PositionManagement

- 统一展示 `entries`
- 不再把 `buy_lots` 当正式对象
- `PositionManagement` 只保留：
  - `券商仓位`
  - `账本仓位`
  - `对账状态`

### OrderManagement

- 主列表展示 `broker_orders`
- 详情展示：
  - `broker order`
  - `execution fills`
  - `linked entries`
  - `reconciliation`

### legacy 兼容

- `/api/stock_fills` 仍可保留名称
- 但底层只从 `position_entries + entry_slices + exit_allocations` 投影
- `om_buy_lots / om_lot_slices / om_sell_allocations` 不再作为正式读源

## 运维流程

### 重建前

- 创建高影响破坏性变更 GitHub Issue，写清影响面、验收标准、部署影响
- 停止写入面：
  - `fqnext_xtquant_broker`
  - `fqnext_xt_account_sync_worker`
  - `fqnext_tpsl_worker`
  - API 订单写入口

### 重建后

- 重启：
  - API
  - `fqnext_xtquant_broker`
  - `fqnext_xt_account_sync_worker`
  - `fqnext_tpsl_worker`
- 重新验证：
  - `/order-management`
  - `/subject-management`
  - `/kline-slim`
  - `/position-management`
  - `/tpsl`
  - `/api/stock_fills`

## 验收标准

- 所有 `position_entry` 都有完整 `date/time`
- 所有 `entry_slice` 都有完整 `date/time`
- 任意 symbol 满足：
  - `sum(open entry remaining_quantity)` 与 `xt_positions.volume` 收敛一致，或差额有明确 `reconciliation`
- 非 `100` 整数倍不会进入正式 entry ledger
- TPSL 只按 `entry_id` 工作
- `603919` 这类 symbol 在 TPSL / Subject 中按 entry 收敛
- `300760` 这类历史 odd-lot 不再以脏 lot 形式出现在主链
- 页面不再出现空买入时间

## 风险与回滚

主要风险：

- 旧内部语义字段丢失
- 某些持仓只能用 `auto_reconciled_open` 表达，无法还原真实历史成交时间
- 重建窗口内若未完全停写，可能引入快照漂移

回滚策略：

- 重建前备份全部待清理 `om_*` 集合到备份库
- 失败时：
  - 停写入面
  - 清空新账本
  - 从备份库整库恢复
  - 再恢复运行面
