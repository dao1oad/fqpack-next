# Broker Reconcile Idempotency Design

**日期**: 2026-03-10

## 背景

`fqnext_xtquant_broker` 在 2026-03-10 上午出现两类重复异常：

- `sell quantity exceeds open guardian slices`
- `Invalid order state transition: FILLED -> FILLED`

现场排查显示，`002475` 的一次外部卖出同时被以下链路重复入账：

1. XT 分笔成交逐笔进入 `xt_reports.try_ingest_xt_trade_dict()`
2. `reconcile_trade_reports()` 对未匹配内部单的成交再次 externalize 为 `external_reported`
3. `confirm_expired_candidates()` 又将同一仓位差候选确认为 `external_inferred`

结果是同一批卖出被多次分配到 Guardian open slices，最终把切片余额吃穿。

## 目标

- 保证外部卖出在 `external_reported` 与 `external_inferred` 两条链之间只会落账一次。
- 保证重复 `FILLED` 委托回报不会把 broker 线程打成异常日志风暴。
- 保持现有公开接口、Mongo schema 和 supervisor 启动方式不变。

## 非目标

- 不重写整个 reconcile 模块。
- 不调整 Guardian 切片算法本身。
- 不引入新的服务、队列或配置项。

## 方案

### 1. external candidate 在真实成交到来后立即收口

当 `reconcile_trade_reports()` 发现 XT 成交可以匹配到 `INFERRED_PENDING` candidate 时：

- 若成交数量等于 candidate 的 `quantity_delta`，将 candidate 标记为 `MATCHED`，不再允许后续 `confirm_expired_candidates()` 再次 externalize。
- 若成交数量小于 candidate 的 `quantity_delta`，按剩余量收缩 candidate，而不是保留原始整单数量。
- 若成交数量大于 candidate 的 `quantity_delta`，直接把 candidate 标记为 `MATCHED`，并以真实成交为准落账。

这样可以切断“先逐笔 external_reported，再整单 external_inferred”的重复路径。

### 2. 外部成交先检查是否已存在等价 external order

`reconcile_trade_reports()` 在创建新的 `external_reported` order 前，先按 `symbol + side + source_type + state + broker_order_id` 查已有外部订单：

- 若已存在同 broker order 的 external order，直接复用该 `internal_order_id`
- 不再为同一 `broker_order_id` 重复创建多个 `external_reported` order

这可以收紧同一笔外部成交的 order 粒度。

### 3. 重复 FILLED 委托回报幂等化

`OrderTrackingService.ingest_order_report()` 对相同状态回报做 no-op：

- `current_state == report["state"]` 时直接返回当前 order
- 不再抛 `FILLED -> FILLED`、`CANCELED -> CANCELED` 这类重复终态异常

这样 broker 线程即使收到重复 XT 委托回报，也只会忽略，不会放大成错误日志。

## 测试

- 新增 reconcile 回归测试：部分成交命中 candidate 后，不会再在 confirm 阶段生成重复 inferred trade。
- 新增 tracking 回归测试：重复 `FILLED` order report 不抛异常。
- 运行现有 `xt_reports / tracking / reconcile` 聚焦测试，确认没有回归。

## 风险

- candidate 收缩逻辑如果实现错误，可能让真实外部剩余仓位漏确认。
- 需要优先让测试覆盖“部分成交 + 剩余候选”场景，避免只修整单场景。
