# 止盈止损

## 职责

TPSL 模块负责在独立 tick 链路上评估止盈和止损条件，并在条件满足时批量生成退出单。它是独立模块，不和 Guardian 共享买卖状态机。

## 入口

- worker
  - `python -m freshquant.tpsl.tick_listener`
- HTTP
  - `/api/tpsl/takeprofit/<symbol>`
  - `/api/tpsl/events`
  - `/api/tpsl/batches/<batch_id>`
- 核心服务
  - `freshquant.tpsl.consumer.TpslTickConsumer`
  - `freshquant.tpsl.service.TpslService`

## 依赖

- Redis tick 队列 `REDIS_TICK_QUEUE_PREFIX:<shard>`
- `xt_positions`
- Order Management 提交能力
- buy lot / stoploss 绑定信息

## 数据流

`Redis tick -> TickQuoteListener -> TpslTickConsumer.handle_tick -> load_active_tpsl_codes -> evaluate_takeprofit / evaluate_stoploss -> create batch -> OrderSubmitService`

执行顺序上，takeprofit 先于 stoploss 评估。

## 存储

TPSL 数据当前仍放在订单管理库，核心集合：

- `om_takeprofit_profiles`
- `om_takeprofit_states`
- `om_exit_trigger_events`

TPSL 还会读取：

- `xt_positions`
- `om_buy_lots`
- `om_stoploss_bindings`

## 配置

- takeprofit profile tiers
- rearm / enable / disable 状态
- cooldown lock（Redis 或内存 fallback）
- Redis host/port/db

当前可通过 API：

- 设置 profile
- 启用/停用 tier
- rearm
- 查询事件

## 部署/运行

- 改动后至少重启：

```powershell
python -m freshquant.tpsl.tick_listener
```

- 如果改了 API，同时重建 `fq_apiserver`

## 排障点

### tick 到了但完全不评估

- 检查 worker 是否在跑
- 检查 active universe 是否包含目标股票
- 检查 Redis tick 队列是否真的有目标 code

### 命中止盈但没有生成退出单

- 检查 profile 是否 enabled
- 检查 cooldown 是否仍在
- 检查 `xt_positions` 可卖数量

### 触发事件落了但批次无单

- 检查 `om_exit_trigger_events`
- 检查 OrderSubmitService 是否被拒绝
- 检查 Position Management 是否影响了退出单（理论上卖单应允许）
