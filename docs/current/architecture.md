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
- 盘后选股工作台层
  - `freshquant.daily_screening.*`
  - `freshquant.screening.strategies.*`
  - 负责把 CLI 选股链路以页面 + SSE 会话的形式重新组织出来，但不替代底层策略实现。
- 数据处理层
  - `freshquant.data.gantt_readmodel`
  - `freshquant.shouban30_pool_service`
  - `morningglory/fqdagster`
  - 负责热门板块读模型、首板筛选读模型与工作区落库。
- 观测层
  - `freshquant.runtime_observability.*`
  - 负责 runtime 事件写盘、聚合与可视化。
- 记忆层
  - `freshquant.runtime.memory.*`
  - 负责把冷记忆、热记忆和角色化 context pack 汇总成 agent 可复用的启动上下文。

## 全局记忆层

- 冷记忆
  - 目录：`.codex/memory/**`
  - 进入 git，保存长期有效的模块边界、deploy surfaces、workflow rules、pitfalls。
- 热记忆
  - 代码入口：`freshquant/runtime/memory/**`
  - 存储：Mongo `fq_memory`
  - 第一版写入 `task_state`、`task_events`、`deploy_runs`、`health_results`、`knowledge_items`、`module_status`、`context_packs`
  - 当前 refresh 会从 `artifacts/cleanup-requests/<issue>.json` 提取 branch / issue / PR 元数据
  - 当前 refresh 会从 `artifacts/<issue>/deployment-comment.md` 提取 deploy / health 摘要，并从 `artifacts/cleanup-results/<issue>.json` 提取 cleanup / done 状态
- context pack
  - 编译入口：`runtime/memory/scripts/compile_freshquant_context_pack.py`
  - 自由 Codex 会话自举入口：`runtime/memory/scripts/bootstrap_freshquant_memory.py`
  - 产物目录：`D:/fqpack/runtime/symphony-service/artifacts/memory/context-packs/**`
  - `Symphony` / `Global Stewardship` 通过 wrapper 预编译并注入 `FQ_MEMORY_CONTEXT_PATH`
  - 自由 Codex 会话若没有现成 `FQ_MEMORY_CONTEXT_PATH`，应先执行 bootstrap 脚本再读取生成的 context pack

记忆层是旁路摘要，不替代 Issue-managed 任务的 GitHub Issue、所有代码更新的 PR+CI、以及 deploy+health+cleanup 真值链。

## 核心调用链

### 实时交易链

`XTData producer -> Redis tick/bar queue -> XTData consumer -> Guardian -> PositionManagement gate -> OrderManagement submit -> Redis STOCK_ORDER_QUEUE -> broker/puppet gateway -> XT 回报 ingest -> projection / TPSL profile`

### 止盈止损链

`XTData producer -> Redis TICK_QUOTE queue -> TpslTickConsumer -> TpslService -> OrderSubmitService -> broker -> XT 回报 ingest`

### 图表与读模型链

`Dagster / readmodel job -> Mongo gantt_db -> gantt routes -> GanttUnified / GanttShouban30Phase1 / KlineSlim`

### 盘后选股工作台链

`DailyScreening.vue -> /api/daily-screening/* -> DailyScreeningService -> CLXS / chanlun strategy -> session store / SSE -> stock_pre_pools`

### 运行观测链

`各模块 RuntimeEventLogger -> logs/runtime/<runtime_node>/<component>/<date>/*.jsonl -> runtime assembler -> /api/runtime/* -> RuntimeObservability.vue`

### 记忆编译链

`.codex/memory/** + docs/current/modules/*.md + artifacts/cleanup-requests/<issue>.json + artifacts/<issue>/deployment-comment.md + artifacts/cleanup-results/<issue>.json -> freshquant.runtime.memory.refresh -> Mongo fq_memory -> freshquant.runtime.memory.compiler -> context pack markdown -> Symphony/Global Stewardship wrapper 或 bootstrap_freshquant_memory.py -> FQ_MEMORY_CONTEXT_PATH`

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
- 每日选股工作台复用 `stock_pre_pools / stock_pools`，但用顶层 `remark` 隔离页面来源，不再把共享集合当成无来源语义的单池子。
- Runtime Observability 是旁路系统，允许丢日志，不允许卡住主交易链。
- 全局记忆层也是旁路系统，只负责减少 agent 重复探索，不允许覆盖正式真值。
- TradingAgents-CN 与主交易链完全解耦，只共享 Mongo/Redis 基础设施和宿主机配置。

## 关键耦合点

- `must_pool` 与 `xt_positions` 同时影响 XTData 订阅池和 Guardian 买入范围。
- 订单管理 ingest 会在买入成交后回写 buy lot，并为 TPSL 准备退出上下文。
- 卖出成交后会重置 Guardian buy grid 状态，避免旧层级持续生效。
- Shouban30 当前把页面结果同步到 `stock_pre_pools` / `stock_pools`，并在 `stock_pool` 工作区提供显式 `must_pool` upsert；`30RYZT.blk` 输出仍只由手动 sync-to-tdx/clear 控制。
