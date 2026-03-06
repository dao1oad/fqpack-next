# Guardian 持仓代码刷新设计

**日期**：2026-03-07

## 背景

当前 `StrategyGuardian` 是否把某只股票视为“持仓股”，依赖 `get_stock_holding_codes()` 的返回结果。该函数现在只读取订单域持仓投影 `get_stock_positions()`，并通过版本号做缓存；正常 XT 成交入账、外部订单对账确认路径没有完整触发缓存失效。

这带来两个问题：

- 新出现的外部持仓代码，如果只先进入 `xt_positions`，但尚未进入订单域投影，Guardian 可能不会把它识别为持仓股。
- 即使订单域投影已经变化，若漏掉 `mark_stock_holdings_projection_updated()`，`get_stock_holding_codes()` 也可能长期返回旧结果。

相关代码入口：

- `freshquant/data/astock/holding.py`
- `freshquant/strategy/guardian.py`
- `freshquant/order_management/ingest/xt_reports.py`
- `freshquant/order_management/reconcile/service.py`

## 目标

- 让 Guardian 对“当前有哪些持仓代码”的判断优先贴近券商真实持仓。
- 补齐订单域持仓变化后的缓存失效链路，避免长期脏读。
- 给持仓代码缓存增加短 TTL 兜底，降低未来漏接失效的风险。

## 非目标

- 不修改 Guardian 卖出数量计算逻辑。
- 不在本次改动中引入“仓位差一发现就立即生成 provisional lot/slice”的新语义。
- 不改变外部订单 120 秒自动确认窗口。

## 方案比较

### 方案 A：`xt_positions ∪ 订单域持仓投影`，并补齐失效链路（采用）

- `get_stock_holding_codes()` 返回 `xt_positions` 与订单域 `list_stock_positions()` 的并集。
- 正常 XT 成交入账、外部订单正式匹配、120 秒自动确认三条路径补 `mark_stock_holdings_projection_updated()`。
- `_get_stock_holding_codes_cached()` 增加短 TTL，作为显式失效之外的兜底。

优点：

- 最小化改动即可解决“新外部持仓代码识别不到”的核心问题。
- 不跨越 RFC 0007 当前已批准的对账语义边界。
- Guardian 与 XTData `guardian_1m` 监控池的数据口径更一致。

缺点：

- 若只有仓位差、尚未完成 120 秒确认，Guardian 仍然只能先识别“这是持仓股”，不能立刻得到精确的 arranged fills 价格层。

### 方案 B：只补缓存失效与 TTL

优点：

- 改动最小。

缺点：

- 外部新持仓代码在未进入订单域投影前，仍然无法仅靠 `xt_positions` 被 Guardian 识别。
- 不能解决“券商真实持仓已变，但投影未更新时 holding codes 漏识别”的问题。

### 方案 C：发现仓位差时立即生成 provisional lot/slice

优点：

- Guardian 能更快看到外部持仓并参与卖出层级计算。

缺点：

- 改动对账语义，属于更大的行为变更，需要额外 RFC/评审，不适合在当前缺陷修复里直接落地。

## 详细设计

### 1. 持仓代码来源

- 新增一个内部聚合逻辑：
  - 订单域持仓投影：沿用 `get_stock_positions()` / `list_stock_positions()`
  - 券商实时持仓快照：直接读取 `DBfreshquant["xt_positions"]`
- 输出仍然保持现有接口语义：
  - 仅返回 6 位基础代码
  - 去重
  - 稳定排序

这样可以保证：

- 系统内已入账但券商快照尚未更新的代码，仍能由订单域投影覆盖。
- 券商端新增外部持仓、但订单域尚未补账的代码，至少可以先通过 `xt_positions` 被识别。

### 2. 缓存策略

- `get_stock_holding_codes()` 继续采用“版本号参与 cache key”的显式失效机制。
- `_get_stock_holding_codes_cached()` 新增短 TTL，建议 15 秒。
- 显式失效仍然是主路径，TTL 只是兜底，不作为正确性的主要保证。

### 3. 失效触发点

在以下持仓语义变化路径补 `mark_stock_holdings_projection_updated()`：

- `OrderManagementXtIngestService.ingest_trade_report()` 成功写入 buy lot / slice 或卖出分摊后。
- `ExternalOrderReconcileService.reconcile_trade_reports()` 成功将外部正式成交补入订单域后。
- `ExternalOrderReconcileService.confirm_expired_candidates()` 生成 `external_inferred` 成交并补入订单域后。

要求：

- 仅在成功完成订单域入账后触发失效。
- 不在纯候选态 `INFERRED_PENDING` 就触发，避免把“尚未入账的候选”误当成持仓投影变化。

### 4. Guardian 行为边界

- 本次修复后，Guardian 更早知道“这只票现在属于持仓股集合”。
- 但在没有正式成交回报、也未完成 120 秒自动确认前，`get_arranged_stock_fill_list(code)` 仍可能没有对应 slice。
- 因此这次修复解决的是“持仓股识别”与“缓存长期陈旧”，不是“无回报时立即具备精确卖出层级”。

## 涉及文件

- 修改 `freshquant/data/astock/holding.py`
- 修改 `freshquant/order_management/ingest/xt_reports.py`
- 修改 `freshquant/order_management/reconcile/service.py`
- 修改 `freshquant/tests/test_order_management_holding_adapter.py`
- 修改 `freshquant/tests/test_order_management_reconcile.py`
- 视需要新增 XT ingest 相关测试

## 验收标准

- 当 `xt_positions` 出现订单域投影尚未包含的新代码时，`get_stock_holding_codes()` 能返回该代码。
- 当订单域持仓在 XT 成交入账、外部正式回报匹配、120 秒自动确认后发生变化时，持仓代码缓存会被刷新。
- 在漏掉显式失效的情况下，持仓代码缓存仍会在短 TTL 后收敛。
- 现有 `freshquant/tests` 全量通过。

## 风险

- 将 `xt_positions` 纳入 holding codes 后，若券商快照存在短暂脏数据，Guardian 可能比订单域更早把某代码视为持仓股。
- 但相比当前“长期完全识别不到”，这个偏差更可控，而且 TTL 与显式失效会让结果快速收敛。
