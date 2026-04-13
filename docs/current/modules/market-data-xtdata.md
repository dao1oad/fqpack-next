# XTData 行情链路

## 职责

XTData 链路负责把宿主机 XTData 行情转换成 FreshQuant 可消费的实时事件流。它承担四件事：

- 从 XTQuant 订阅当前监控池的全量行情。
- 把 tick 推入 Redis 分片队列。
- 合成 1 分钟 bar，并继续向下游发布 bar close 事件。
- 在 consumer 侧做 prewarm、结构计算、实时缓存与运行观测。

## 入口

- producer
  - `python -m freshquant.market_data.xtdata.market_producer`
- consumer
  - `python -m freshquant.market_data.xtdata.strategy_consumer --prewarm`

producer 是唯一 XTData 入口；consumer 是唯一 bar 队列消费入口。

## 依赖

- 宿主机 XTQuant / XTData 环境
- `XTQUANT_PORT`，默认 `58610`
- Redis
- QuantAxis 历史库
- 监控池来源
  - `guardian_1m = xt_positions + must_pool`
  - `guardian_and_clx_15_30 = (xt_positions + must_pool) + stock_pools`
    - 先保留 Guardian 池
    - 再补未过期 `stock_pools`
    - 总数不超过 `monitor.xtdata.max_symbols`

## 数据流

### Tick 链

`XTData -> market_producer -> REDIS_TICK_QUEUE_PREFIX:<shard> -> TpslTickConsumer`

- `market_producer` 的 XTData 回调当前只负责规范化 tick、更新接收心跳、把 tick quote 批次交给后台写队列，并把原始 tick 交给 1 分钟 bar pump。
- tick quote 的 Redis `rpush` 已从 XTData 回调线程移到后台 worker，避免 Redis 抖动直接卡住 XTData 回调链。

### Bar 链

`XTData -> market_producer/OneMinuteBarGenerator -> REDIS_QUEUE_PREFIX:<shard> -> strategy_consumer -> realtime cache / chanlun payload / Guardian`

consumer 会在启动时做历史 prewarm，并在 backlog 很高时进入 catchup 模式，暂时跳过 fullcalc，只保留最新数据。
- `OneMinuteBarGenerator` 当前只在 `whole_quote` 快照带来正向 `volume/amount` 增量时更新 1 分钟 bar 的 OHLC；无成交的 quote-only 快照不会再改写分钟高低收。
- `11:30:00` 与 `15:00:00` 这类交易时段结束边界快照会归入最后一个有效分钟 bar，而不是落到午休或收盘后的无效分钟桶。

## 存储

- Redis
  - tick 分片队列
  - bar 分片队列
  - 实时 Kline cache
- Mongo / QuantAxis
  - 历史分钟线读取
  - 实时结构或补权结果所需的基础数据
  - `realtime_screen_multi_period`

当前模块会在启用 CLX 能力时把命中的多周期 CLX 信号写入 `realtime_screen_multi_period`。

## 配置

- `monitor.xtdata.mode`
  - 决定订阅池来源和 consumer 行为。
  - `guardian_1m` 只服务 Guardian 1 分钟事件链。
  - `guardian_and_clx_15_30` 同时服务：
    - Guardian 1 分钟事件链
    - `stock_pools` 的 15/30 分钟 CLX 模型
  - 兼容旧值：
    - `clx_15_30`
      - 读取时自动归一到 `guardian_and_clx_15_30`
- `monitor.xtdata.max_symbols`
  - 限制订阅池大小。
- `monitor.xtdata.queue_backlog_threshold`
  - 决定 consumer 何时进入 catchup 模式。
- `XTQUANT_PORT`
  - XTData 连接端口。

对 Guardian 主链最重要的是：

- `monitor.xtdata.mode` 启用了 Guardian 能力
  - 正式值可为 `guardian_1m` 或 `guardian_and_clx_15_30`

## 部署/运行

- 这两个进程通常运行在宿主机，不放进 Docker。
- 修改 `freshquant/market_data/**` 后，至少重启 producer 与 consumer。
- consumer 改动涉及结构缓存或 prewarm 逻辑时，建议带 `--prewarm` 重新拉起。
- producer 当前会在交易时段内监控 `rx_age_s`：
  - 当 `connected=1`、`subscribed_codes>0` 且 `rx_age_s >= 120` 秒时，先自动重订阅当前代码池。
  - 若 30 秒后仍持续 stale，则升级为 `xtdata.connect() + 重订阅`。
  - 恢复动作会写入 `subscription_guard` 运行事件，`reason_code=stale_rx`。
- producer 心跳当前额外暴露：
  - `tick_quote_pending_batches`
  - `tick_quote_dropped_batches`

## 排障点

### producer 无数据

- 检查 XTQuant 是否在线。
- 检查 `XTQUANT_PORT`。
- 检查订阅池是否为空。
- 检查最新 `xt_producer` 心跳里的 `rx_age_s`、`tick_count_5m`、`tick_quote_pending_batches`、`tick_quote_dropped_batches`。
- 若 `connected=1`、`subscribed_codes>0`，但 `rx_age_s` 在交易时段持续增长且 `tick_count_5m=0`，优先判断为 producer 订阅/回调链 stale，而不是先怀疑 `minqmt` 客户端配置。
- 检查 `subscription_guard` 事件是否已触发自动 `resubscribe` / `reconnect`；若仍不恢复，再按宿主机运行面入口重启 `market_data`。

### consumer 不更新

- 检查 Redis bar 队列是否持续堆积。
- 检查 `monitor.xtdata.mode` 是否匹配。
- 检查 prewarm 是否异常退出。

### Kline 页面停在旧 bar

- 检查 Redis realtime cache 是否更新。
- 检查 `/api/stock_data` 是否启用了 realtime cache。

### TPSL 不收到 tick

- 检查 tick 分片队列是否有目标 code。
- 检查 producer 是否在向 `REDIS_TICK_QUEUE_PREFIX:<shard>` 推送。
