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

### Bar 链

`XTData -> market_producer/OneMinuteBarGenerator -> REDIS_QUEUE_PREFIX:<shard> -> strategy_consumer -> realtime cache / chanlun payload / Guardian`

consumer 会在启动时做历史 prewarm，并在 backlog 很高时进入 catchup 模式，暂时跳过 fullcalc，只保留最新数据。

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

## 排障点

### producer 无数据

- 检查 XTQuant 是否在线。
- 检查 `XTQUANT_PORT`。
- 检查订阅池是否为空。

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
