# 当前架构

## 总体分层

- 行情层
  - `freshquant.market_data.xtdata.market_producer`
  - `freshquant.market_data.xtdata.strategy_consumer`
  - 负责 XTData 订阅、tick 分发、分钟 bar 生成、结构计算与缓存。
- 策略层
  - `freshquant.signal.astock.job.monitor_stock_zh_a_min`
  - `freshquant.strategy.guardian`
  - 负责把信号转换成买卖意图，但不负责订单事实。
- 交易执行层
  - `freshquant.order_management.*`
  - `freshquant.position_management.*`
  - `freshquant.tpsl.*`
  - `fqxtrade.xtquant.broker`
  - 负责门禁、订单受理、broker 下发、回报 ingest、止盈止损。
- 展示层
  - `freshquant.rear.*`
  - `morningglory/fqwebui`
  - 负责 API、Web UI 与历史/实时视图展示。
- 数据处理层
  - `freshquant.data.gantt_readmodel`
  - `freshquant.shouban30_pool_service`
  - `morningglory/fqdagster`
  - 负责热门板块读模型、首板筛选读模型与工作区落库。
- 观测层
  - `freshquant.runtime_observability.*`
  - 负责 runtime 事件写盘、聚合与可视化。

## 核心调用链

### 实时交易链

`XTData producer -> Redis tick/bar queue -> XTData consumer -> Guardian -> PositionManagement gate -> OrderManagement submit -> Redis STOCK_ORDER_QUEUE -> broker/puppet gateway -> XT 回报 ingest -> projection / TPSL profile`

### 止盈止损链

`XTData producer -> Redis TICK_QUOTE queue -> TpslTickConsumer -> TpslService -> OrderSubmitService -> broker -> XT 回报 ingest`

### 图表与读模型链

`Dagster / readmodel job -> Mongo gantt_db -> gantt routes -> GanttUnified / GanttShouban30Phase1 / KlineSlim`

### 运行观测链

`各模块 RuntimeEventLogger -> logs/runtime/<runtime_node>/<component>/<date>/*.jsonl -> runtime assembler -> /api/runtime/* -> RuntimeObservability.vue`

## 进程边界

- API Server
  - `python -m freshquant.rear.api_server --port 5000`
  - 聚合所有 HTTP 蓝图，不直接做重计算。
- Guardian monitor
  - `python -m freshquant.signal.astock.job.monitor_stock_zh_a_min --mode event`
  - 监听 bar 更新并调用 `StrategyGuardian`。
- XTData producer
  - `python -m freshquant.market_data.xtdata.market_producer`
  - 唯一负责订阅 XTData 全量行情并向 Redis 推送 tick 事件。
- XTData consumer
  - `python -m freshquant.market_data.xtdata.strategy_consumer --prewarm`
  - 唯一负责 bar 队列消费、结构计算与缓存回写。
- Position worker
  - `python -m freshquant.position_management.worker --interval 3`
  - 定期刷新仓位门禁状态。
- TPSL worker
  - `python -m freshquant.tpsl.tick_listener`
  - 消费 tick 队列并触发止盈止损。
- Broker / Puppet gateway
  - 不在本目录直接暴露 HTTP，靠 Redis 队列与 XT 回报回流。

## 模块边界

- Guardian 只负责决定“要不要下这个策略单”，不是订单账本。
- Position Management 只负责是否允许提交，不负责真正下单。
- Order Management 是订单事实层，维护请求、内部订单、事件、买入 lot、卖出分配与外部单对齐。
- TPSL 是独立退出策略，依赖订单事实和持仓，不跟 Guardian 共用状态机。
- Gantt 与 Shouban30 只消费读模型与工作区集合，不参与交易链。
- Runtime Observability 是旁路系统，允许丢日志，不允许卡住主交易链。
- TradingAgents-CN 与主交易链完全解耦，只共享 Mongo/Redis 基础设施和宿主机配置。

## 关键耦合点

- `must_pool` 与 `xt_positions` 同时影响 XTData 订阅池和 Guardian 买入范围。
- 订单管理 ingest 会在买入成交后回写 buy lot，并为 TPSL 准备退出上下文。
- 卖出成交后会重置 Guardian buy grid 状态，避免旧层级持续生效。
- Shouban30 当前只把页面结果同步到 `stock_pre_pools` / `stock_pools`，并单独负责 `30RYZT.blk` 输出；它不再把 `/gantt/shouban30` 页面动作直接写进 `must_pool`。
