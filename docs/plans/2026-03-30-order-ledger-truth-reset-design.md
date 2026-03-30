# Order Ledger Truth Reset Design

## 目标

彻底收敛订单账本运行期真值，消除 `xt_positions`、`om_position_entries`、legacy `om_buy_lots` 与 entry stoploss 视图之间的分叉。

## 已确认根因

- 运行期 reconcile 在计算内部剩余仓位时，同时累加了 V2 `om_position_entries.remaining_quantity` 和 legacy `om_buy_lots.remaining_quantity`
- 当同一 symbol 同时存在 open V2 entry 和 open legacy buy_lot 时，系统会把内部持仓算成双倍
- 下一轮 reconcile 会错误地产生 `sell gap` 并执行 `auto_close_allocation`
- 最终表现为：
  - `xt_positions` 仍有仓位
  - `/position-management` 通过 broker truth 对齐后看似正常
  - `/subject-management`、`/tpsl`、`/kline-slim` 因 open entry 被清空而没有“按持仓入口止损”

## 方案

1. 修复 reconcile 内部仓位计算逻辑
   - V2 `position_entries` 存在时，不再把 legacy `buy_lots` 纳入运行期对账主口径
   - legacy `buy_lots` 继续保留给兼容视图/审计，不再参与运行期主真值判定
2. 用失败测试锁定“open entry + open legacy buy_lot 共存时不得产出 sell gap”
3. 对当前运行库执行 destructive reset
   - 备份订单账本数据库
   - 清理 OM 运行期集合与 compat 投影
   - 仅基于 `xt_orders / xt_trades / xt_positions` 重建
   - 重建后再跑一次 reconcile 校准当前 broker 仓位
4. 验证视图一致性
   - `xt_positions.volume > 0` 的 symbol 必须在 `om_position_entries` 中恢复为 open entry，或仅以 open reconciliation gap 表达差额
   - `/subject-management`、`/tpsl`、`/kline-slim` 必须能看到 open entries
   - `/position-management` 的 ledger/reconciliation 不再掩盖 entry 为空的异常

## 风险与回滚

- 这是 destructive rebuild，必须先备份目标数据库
- 若重建或校验失败，停写入面后整库恢复，不做局部回滚

