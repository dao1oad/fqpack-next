# Order Management Entry Aggregation Design

**Date:** 2026-04-01

**Goal:** 在不改变券商原始订单真值边界的前提下，把 `om_position_entries / om_entry_slices / entry stoploss` 收口到“保守聚合买入入口 + 50000 切片”口径，并让 `SubjectManagement` 与 `KlineSlim` 的“按持仓入口止损”展示保持一致。

## Current Problem

- `om_broker_orders / om_execution_fills` 已经是券商原始订单与成交真值，但 `om_position_entries` 当前仍按单个 `broker_order` 生成 entry。
- 同一交易日内，接近时间、接近价格的多笔买单会被拆成多条 entry，导致：
  - `SubjectManagement` / `KlineSlim` 的 entry stoploss 出现大量碎片；
  - 卖出扣减对应到过多 entry / slice，解释层可读性差；
  - rebuild 后仍会重复生成同类碎片。
- `SubjectManagement` 当前 stoploss 区展示仍比 `KlineSlim` 简化，缺少“剩余市值”等关键摘要。

## Hard Constraints

- `om_broker_orders / om_execution_fills` 必须继续保留为原始券商订单真值，不改成聚合后的“伪订单”。
- position entry 聚合只能发生在解释层，且必须可追溯回原始 broker order。
- 切片必须基于“聚合后的 entry”重新生成，`lot_amount` 默认值和回退值统一为 `50000`。
- destructive rebuild 只能继续从 `xt_orders / xt_trades / xt_positions` 重放，不允许从旧 `om_*` 倒推。

## Recommended Approach

采用“双层真值”方案：

1. 保留 `om_broker_orders / om_execution_fills` 为原始订单真值。
2. 把 `om_position_entries` 定义为“聚合买入入口真值”。
3. ingest 与 rebuild 共用同一套 buy-entry 聚合规则。
4. `om_entry_slices` 始终由聚合后的 entry 重新按 `50000` 切片生成。
5. `SubjectManagement` 与 `KlineSlim` 共用同一套 entry 摘要展示逻辑。

## Aggregation Rules

聚合单位是“已经按 `broker_order` 聚合完成的 buy execution group”，不是单笔 fill。

新 buy group 只有同时满足以下条件时才并入已有 open entry：

- 同一 `symbol`
- 同一北京时间交易日
- `buy` 侧
- 与候选 entry 的最新聚合成员时间差 `<= 5 分钟`
- 与 cluster 首成员时间差 `<= 5 分钟`
- 成交均价偏差 `<= 0.3%`
- 候选 entry 仍 open，且自该 entry 最近一次 buy member 之后尚未发生卖出扣减

否则创建新的 position entry。

该规则刻意保守，cluster 窗口锚定首成员，不允许靠“每次都只差 4 分钟”的链式延长把日内多段独立买入错误合并成一个大 entry。

## Position Entry Shape

聚合 entry 在现有字段基础上新增聚合元数据：

- `source_ref_type = "buy_cluster"`
- `entry_type = "broker_execution_cluster"`
- `source_ref_id = <cluster_id>`
- `aggregation_members`
  - 成员 `broker_order_key`
  - 成员 `trade_fact_id`
  - 成员 `quantity`
  - 成员 `entry_price`
  - 成员 `trade_time / date / time`
- `aggregation_window`
  - `start_trade_time`
  - `end_trade_time`
  - `trading_day`
  - `member_count`

`entry_price / amount / original_quantity / remaining_quantity` 都以聚合结果为准；卖出继续只更新聚合 entry 自身，不反写原始 broker order。

## Slice / Allocation Semantics

- 每个聚合 entry 都重新调用 `arrange_entry(...)` 生成切片。
- 切片参数固定使用当前系统设置解析出的 `lot_amount`，异常回退仍为 `50000`。
- 卖出扣减仍沿用当前 `allocate_sell_to_entry_slices(...)` 逻辑。
- 卖出影响的对象变成聚合后的 entry / slice，因此 `sell_history` 也以聚合 entry 视角保存。

## Rebuild Strategy

- rebuild 先按现有方式生成 `broker_order_documents / execution_fill_documents`。
- buy 侧先形成 `broker execution group`，再按保守聚合规则归并成 cluster entry。
- sell 侧继续按时间顺序扣减聚合 entry 的 open slices。
- stoploss binding 不从旧 entry 迁移复用；destructive rebuild 后按新 entry 重新建立。
- 在正式 `--execute` 前先做 dry-run 审计，输出：
  - 重放后 entry 数量变化
  - 非 `50000` 切片数量
  - 可聚合但当前未聚合的 entry 组

## UI Consistency

- `subjectManagement.mjs` 继续作为 entry 摘要的唯一前端组装口径。
- `SubjectManagement.vue` 的“按持仓入口止损”改成和 `KlineSlim.vue` 使用相同摘要字段：
  - 买入价
  - 买入数量
  - 剩余数量
  - 买入时间
  - 剩余市值
- 两页都直接消费 `entrySummaryDisplay`，避免再次分叉。

## Testing Strategy

后端至少覆盖：

- 同 symbol / 同日 / 5 分钟内 / 0.3% 价差内的 buy groups 被聚合
- 超过 5 分钟或超过 0.3% 不聚合
- 存在卖出扣减边界后，后续 buy group 不再并入旧 entry
- 聚合 entry 的切片全部按 `50000` 生成
- rebuild 与实时 ingest 使用同一规则

前端至少覆盖：

- `SubjectManagement` entry 摘要包含“剩余市值”
- `SubjectManagement` 与 `KlineSlim` 对同一 detail 输入生成一致摘要

## Deployment / Ops Impact

- 代码变更涉及 `freshquant/order_management/**`，需要重部署 API 并重启相关 worker。
- 代码变更涉及 `morningglory/fqwebui/**`，需要重建 Web UI。
- 正式清理旧数据并执行 destructive rebuild 前，需要先建立 GitHub Issue，写清影响面、验收标准与部署影响。
