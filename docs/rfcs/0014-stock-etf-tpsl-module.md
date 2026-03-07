# RFC 0014: 股票/ETF 独立止盈止损模块

- **状态**：Approved
- **负责人**：Codex
- **评审人**：User
- **创建日期**：2026-03-07
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

目标仓库已经具备两块与止盈止损相关的基础设施：

- `RFC 0003` 已落地 `XTData -> BAR_CLOSE -> fullcalc -> CHANNEL:BAR_UPDATE` 的实时行情主链路。
- `RFC 0007` 已落地股票/ETF 订单域主账本、`buy_lot / lot_slice / sell_allocations` 与 `buy_lot_id` 级别的单笔止损绑定。

当前缺口是：

- 还没有一个独立的、基于 tick / orderbook 的止盈止损执行模块。
- 旧仓库 `D:\fqpack\freshquant` 中的 `strategy/grid.py`、`strategy/stoploss.py`、`strategy/toolkit/fill_stoploss_helper.py` 已实现“标的级网格卖出 + 全局/单笔止损 + tick 触发执行”的闭环，但仍依赖旧的 `stock_fills/fill_id` 语义，不符合目标仓库的订单域边界。
- 新仓库当前只有 `buy_lot_id` 级别的止损绑定 API，还没有：
  - tick/orderbook 事件协议
  - 标的级三层止盈配置与运行时状态
  - 聚合止损卖单
  - 独立的 TPSL 常驻消费者

本 RFC 要求在复用现有 XTData producer 和订单域的前提下，新增一个独立模块，把旧仓库的止盈止损能力迁移到目标架构中。

## 2. 目标（Goals）

- 仅支持股票/ETF 实盘链路。
- 新增独立止盈止损模块（TPSL），不把逻辑塞回 `Guardian` 或现有 `xtdata strategy_consumer`。
- 复用现有 XTData producer，新增 `TICK_QUOTE` 事件协议，不引入独立轮询器。
- 实现“每个标的一套共享三层止盈配置”，支持盘中 API 动态更新、独立启停和热生效。
- 止盈触发条件使用 `卖一价(ask1) >= 止盈层价格`。
- 止盈卖出数量复用 Guardian 当前“拆单并汇总盈利部分”的计算方式。
- 实现 `buy_lot_id` 级别单笔止损，触发条件使用 `买一价(bid1) <= 单笔止损价`。
- 单笔止损只作用于该 `buy_lot` 被卖出后的剩余部分，即 `buy_lot.remaining_quantity`。
- 同一标的多个 `buy_lot` 同时触发止损时，只提交一笔聚合卖单，减少手续费。
- 卖单统一复用现有订单域受理、回报和分摊链路，保证 `buy_lot / lot_slice / sell_allocations` 一致性。
- 提供最小后端 API：止盈配置、止盈状态、单笔止损绑定复用入口、触发审计查询。

## 3. 非目标（Non-Goals）

- 不覆盖期货、模拟交易、回测策略。
- 不重写 `Guardian` 的信号生成逻辑。
- 不在本 RFC 内完成前端 UI 改造。
- 不引入新的消息系统或新的数据库实例。
- 不回退到旧的 `fill_id + stock_fills` 主逻辑。

## 4. 范围（Scope）

**In Scope**

- XTData producer 新增 `TICK_QUOTE` 事件输出。
- 独立 `TPSL` consumer/service。
- 标的级三层止盈 profile 和 state。
- `buy_lot` 级单笔止损候选筛选与聚合卖单。
- 订单受理作用域扩展为 `takeprofit_batch` / `stoploss_batch`。
- 审计事件与批次查询 API。

**Out of Scope**

- 期货止盈止损。
- 重新设计 `Guardian` 策略。
- 前端页面改造。
- 新增第三方消息队列或流式中间件。

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**

- XTData producer 负责新增 `TICK_QUOTE` 事件输出。
- TPSL 模块负责：
  - 维护当前监控标的集合
  - 止盈/止损判定
  - 卖出批次构建
  - 调用订单域提交卖单
  - 维护止盈层运行时状态
  - 记录触发审计
- 订单域继续负责：
  - 订单受理与回报
  - `buy_lot / lot_slice / sell_allocations` 更新

**不负责（Must Not）**

- TPSL 模块不直接连接 XTData。
- TPSL 模块不维护订单主账本事实。
- TPSL 模块不直接写 `stock_fills`。
- TPSL 模块不改变 `Guardian` 信号算法。

**依赖（Depends On）**

- `freshquant/market_data/xtdata/market_producer.py`
- `freshquant/order_management/`
- Redis（tick 队列、去重锁）
- MongoDB（TPSL profile/state/audit）
- XTData / MiniQMT 本机环境

**禁止依赖（Must Not Depend On）**

- 不允许新增独立 `get_full_tick()` 轮询器。
- 不允许把 TPSL 状态继续落到 legacy `grid_configs`、`stoploss_configs`、`fill_stoploss_configs`。
- 不允许新逻辑继续以 `fill_id` 作为单笔止损长期主键。

## 6. 对外接口（Public API）

### 6.1 XTData Tick 事件协议

新增 `TICK_QUOTE` 事件，最小字段：

- `event = "TICK_QUOTE"`
- `code`
- `time`
- `lastPrice`
- `bid1`
- `ask1`

### 6.2 HTTP API

- `GET /api/tpsl/takeprofit/<symbol>`
- `POST /api/tpsl/takeprofit/<symbol>`
- `POST /api/tpsl/takeprofit/<symbol>/tiers/<level>/enable`
- `POST /api/tpsl/takeprofit/<symbol>/tiers/<level>/disable`
- `POST /api/tpsl/takeprofit/<symbol>/rearm`
- `GET /api/tpsl/events`
- `GET /api/tpsl/batches/<batch_id>`

单笔止损绑定继续复用：

- `POST /api/order-management/stoploss/bind`

### 6.3 内部提交作用域

订单域新增两类 scope：

- `scope_type = "takeprofit_batch"`
- `scope_type = "stoploss_batch"`

### 6.4 错误语义

- 行情字段缺失：跳过本次事件，记审计，不下单。
- 可卖量不足一手：返回 blocked，记 `blocked_reason`。
- 下单失败：不推进止盈层状态，批次记失败。
- 成交回写延迟：通过短冷却锁避免重复触发。

## 7. 数据与配置（Data / Config）

### 7.1 新增集合

在订单域数据库 `freshquant_order_management` 中新增：

- `om_takeprofit_profiles`
- `om_takeprofit_states`
- `om_exit_trigger_events`

### 7.2 `om_takeprofit_profiles`

- `symbol`
- `tiers`
  - `[{level, price, manual_enabled}]`
- `updated_at`
- `updated_by`

### 7.3 `om_takeprofit_states`

- `symbol`
- `armed_levels`
  - `{1: bool, 2: bool, 3: bool}`
- `last_triggered_level`
- `last_triggered_at`
- `last_trigger_batch_id`
- `last_rearm_trade_fact_id`
- `version`

### 7.4 `om_exit_trigger_events`

- `event_id`
- `event_type`
- `symbol`
- `tick_time`
- `bid1`
- `ask1`
- `last_price`
- `batch_id`
- `profile_version`
- `state_version`
- `payload`

### 7.5 复用集合

- `om_stoploss_bindings`
- `om_buy_lots`
- `om_lot_slices`
- `om_sell_allocations`

## 8. 破坏性变更（Breaking Changes）

- XTData producer 新增 `TICK_QUOTE` 事件协议。
- 后端新增 `/api/tpsl/*` 接口。
- 订单域 scope 扩展为 `takeprofit_batch` / `stoploss_batch`。
- TPSL 状态不再沿用旧分支的 `grid_configs` / `stoploss_configs` / `fill_stoploss_configs`。

### 迁移步骤

1. 部署含 `TICK_QUOTE` 输出的 XTData producer。
2. 启动独立 TPSL consumer。
3. 通过 API 配置标的级止盈 profile 与 `buy_lot` 止损绑定。
4. 停止依赖旧分支 Grid/StopLoss 的 tick 执行链。

### 回滚方案

1. 停止 TPSL consumer。
2. 忽略 `TICK_QUOTE` 队列，不影响现有 `BAR_CLOSE` 链路。
3. 回退 producer 的 `TICK_QUOTE` 输出与 `/api/tpsl/*` 接口。

## 9. 迁移映射（From `D:\fqpack\freshquant`）

- `freshquant\strategy\grid.py` → `freshquant/tpsl/takeprofit_*`
- `freshquant\strategy\stoploss.py` → `freshquant/tpsl/stoploss_*`
- `freshquant\strategy\toolkit\fill_stoploss_helper.py` → 继续由 `buy_lot` 绑定语义替代，不直接迁回
- `freshquant\signal\astock\job\monitor_stock_zh_a_min.py` 中的 tick 执行段 → `freshquant/tpsl/consumer.py`

## 10. 测试与验收（Acceptance Criteria）

- [ ] 当前有持仓且有有效 TPSL 配置的股票/ETF，能自动进入 tick 监控。
- [ ] API 更新止盈/止损配置后，无需重启即可生效。
- [ ] 止盈使用 `ask1 >= tier_price` 判定。
- [ ] 跳层时只执行最接近命中层，不补低层。
- [ ] 命中后禁用该层及以下层。
- [ ] 新买入价低于最低止盈层时，重新启用允许启用的层。
- [ ] 止盈卖量与 Guardian 当前盈利拆单语义一致。
- [ ] 止损使用 `bid1 <= buy_lot.stop_price` 判定。
- [ ] 单笔止损仅作用于 `buy_lot.remaining_quantity`。
- [ ] 多个 `buy_lot` 同时触发止损时，只下一笔聚合卖单。
- [ ] 聚合止损卖单的委托价取本批最低止损价。
- [ ] 内部可追溯每个 `buy_lot / lot_slice` 的贡献量。
- [ ] 同一 tick 同时命中止盈和止损时，止盈优先。
- [ ] 可以查询触发/阻塞/提交/失败的审计记录。

## 11. 风险与回滚（Risks / Rollback）

- 风险点：`bid1/ask1` 抖动导致重复推单。
  - 缓解：短冷却锁 + 批次去重键。
- 风险点：`can_use_volume` 不可读导致卖量计算不稳定。
  - 缓解：默认 blocked，不在本 RFC 内做激进回退。
- 风险点：止盈层状态与新买入 rearm 条件不一致。
  - 缓解：在 XT 回报 ingest 和手工导入路径同时挂接 rearm hook。

## 12. 里程碑与拆分（Milestones）

- M1：RFC 0014 Approved
- M2：`TICK_QUOTE` 事件协议与 producer 并池逻辑落地
- M3：TPSL profile/state/service 落地
- M4：止盈/止损批次计算与聚合卖单落地
- M5：TPSL consumer 与 API 落地
- M6：回归验证、治理收尾与部署说明完成
