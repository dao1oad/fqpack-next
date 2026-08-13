# 止盈（TPSL）

## 职责

TPSL 在独立 tick 链路上评估止盈条件，并生成退出单。止损触发功能已随 Issue #603 整体下线（路线步骤 2 PR-2a），三条 BUY 抄底线承担补仓职责：

- 止盈按 symbol profile 管理
- 止盈命中档位但当前可盈利切片数量为 `0` 时，仍会消耗命中档位并写 `takeprofit_hit`，但不会生成退出单
- 历史与详情优先读取 `entry ledger`
- 止盈卖出提交前会统一按 `xt_positions.can_use_volume` 截断，并按一手向下取整；Guardian 卖出现在复用同一套约束 helper
- tick listener 在北京时间 `09:30:00` 前不响应 tick 事件，不评估止盈/买入线，也不生成退出单或 Runtime Trace
- 有效 tick 门槛（路线步骤 3，根②）：tick 时间合法且 `bid1/ask1/last_price`
  三者均 >0 才进入评估链；否则跳过并落 `tpsl_worker.tick_gate`
  `reason_code=invalid_tick_time` / `invalid_tick_quote`，不评估止盈/买入线
- TPSL 提交时显式写 `om_order_requests.ledger_intent`：买入线（base_line）
  与止盈卖出 → `base`；`guardian_sell_sources` 仅作为
  止盈分配书签保留，不参与归属判定（#571）。

买入线提交侧容量复核（路线步骤 3，根②，fail-closed 三分）：
- 决策缺少 `effective_stage_cap` → 阻断，`blocked_reason=base_buy_cap_missing`
- 容量复核本身读失败/异常 → 阻断，`blocked_reason=capacity_recheck_failed`
  （不再吞异常放行提交）
- 容量组件返回不可用（账本占用/在途/仓位快照读不到）→ 阻断，
  `blocked_reason=position_capacity_unavailable`
- 复核顺序在冷却获取之前（副作用后置）：因瞬时读失败被阻断的 tick
  不消耗 15 分钟 `base_buy:<code>` 冷却，下一 tick 可立即重试

## 入口

- worker
  - `python -m freshquant.tpsl.tick_listener`
- HTTP
  - `/api/tpsl/takeprofit/<symbol>`
  - `/api/tpsl/takeprofit/<symbol>/tiers/<level>/enable`
  - `/api/tpsl/takeprofit/<symbol>/tiers/<level>/disable`
  - `/api/tpsl/takeprofit/<symbol>/rearm`
  - `/api/tpsl/management/overview`
  - `/api/tpsl/management/<symbol>`
  - `/api/tpsl/history`
  - `/api/tpsl/events`
  - `/api/tpsl/batches/<batch_id>`

## 当前依赖

- Redis tick 队列
- `xt_positions`
- `pm_symbol_position_snapshots`
- `om_takeprofit_profiles`
- `om_takeprofit_states`
- `om_position_entries`
- `om_entry_slices`
- `om_exit_trigger_events`
- `om_order_requests / om_orders / om_order_events / om_trade_facts`

## 当前读模型

### overview

`/api/tpsl/management/overview` 当前汇总：

- 当前持仓数量
- 单标的实时仓位金额
- 止盈 profile 摘要
- open entry 数量
- 最近触发事件

### detail

`/api/tpsl/management/<symbol>` 当前返回：

- takeprofit profile / state
- `entries`
- `entry_slices`
- `reconciliation`
- 统一历史摘要

当前 `takeprofit state` 缺失时，系统统一按未激活处理：

- `TakeprofitService.get_state()` 会创建 `armed_levels[level]=false` 的默认 state
- `/api/tpsl/management/*` 与 `/api/subject-management/*` 都按未激活口径返回
- 只有执行 `/api/tpsl/takeprofit/<symbol>/rearm` 或显式开启层级后，运行态才会恢复为可触发

当前 detail 已不再返回 `buy_lots`，也不再把 `stock_fills` 兼容视图当成主详情对象。
`reconciliation.state` 当前统一复用 shared canonical 语义，前后端展示统一为：

- `ALIGNED`：券商与账本对齐
- `OBSERVING`：存在待观察差额
- `AUTO_RECONCILED`：系统已自动补齐账本
- `BROKEN`：对账链路异常
- `DRIFT`：券商与账本仍然漂移

### history

`/api/tpsl/history` 当前只按：

- `symbol`
- `batch_id`
- `entry_id`

做过滤；不再接受 `buy_lot_id`。

## entry ledger / compat

- `entry_ledger`
  - 主读模型，来自 `om_position_entries + om_entry_slices`
- `stock_fills_compat`
  - 仅兼容旧接口/旧脚本
  - 不再定义 TPSL 主页面真值

## 页面布局

TPSL 当前不再保留独立 `/tpsl` 页面入口；相关信息已经分散并入以下正式页面：

- `/position-management`
  - 作为统一仓位与排障入口，承载聚合买入列表、切片明细、相关订单、对账结果与 Resolution
- `/kline-slim`
  - 承载 symbol 级设置、止盈 profile 与运行态摘要

## 部署

- 改动 `freshquant/tpsl/**`
  - 重建 API Server
  - 重启 `tpsl.tick_listener`

## 排障

### 命中止盈但没有退出单

- 查 `om_takeprofit_profiles / om_takeprofit_states`
- 查 `xt_positions.can_use_volume / volume`
- 查 `om_exit_trigger_events`
- 查对应 request / order / trade 链路

### 历史链路缺 request / order / trade

- 查 `om_exit_trigger_events.batch_id`
- 查 `om_order_requests.scope_type / scope_ref_id`
- 查 `om_orders.request_id`
- 查 `om_trade_facts.internal_order_id`
