---
name: legacy-freshquant-migration-modules-survey
description: 旧仓库 D:\fqpack\freshquant 的代码结构与运行逻辑调研，聚焦 10 个后续重点迁移模块（xtdata producer/consumer、guardian、止盈止损、仓位管理、订单管理、结构化日志、KlineSlim、数据同步、甘特图、30日热门缠论筛选）。
---

# 旧仓库 freshquant：重点迁移模块调研

- **调研日期**：2026-03-05
- **现状追加**：2026-03-11
- **旧仓库**：`D:\fqpack\freshquant`（待迁移/参考实现）
- **目标仓库**：`D:\fqpack\freshquant-2026.2.23`（目标架构，本期迁移承载）

本文面向“后续迁移/重构（RFC 前置）”的代码调研总结，重点覆盖用户明确列出的 10 个迁移模块，并给出旧仓库实现的**入口文件**、**数据流**、**存储结构**、**运行形态**与**迁移落点/风险**。

> 重要：本文主体描述的是**旧仓实现**。如需判断目标仓当前状态，请先读 `docs/agent/项目目标与代码现状调研.md` 与 `docs/migration/progress.md`。旧仓路径、模块名和接口形态不应直接当作目标仓当前事实引用。

## 0.1 截至 2026-03-10 的目标仓迁移落点

| 模块 | 目标仓当前状态 | 目标仓落点 / RFC |
|------|----------------|------------------|
| 1. XTData producer / consumer | 已落地 | `freshquant/market_data/xtdata/*`，RFC `0003` |
| 2. Guardian | 已持续收敛，仍沿用现有策略模块 | `freshquant/strategy/guardian.py`；运行链已接入 RFC `0003`、`0007`、`0013`、`0014`、`0019`、`0026` |
| 3. 止盈止损 | 已独立模块化 | `freshquant/tpsl/*`，RFC `0014` |
| 4. 仓位管理 | 已独立模块化 | `freshquant/position_management/*`，RFC `0013` |
| 5. 订单管理 | 已独立模块化；`observe_only` broker 演练模式已落地 | `freshquant/order_management/*`，RFC `0007`、`0020`、`0030` |
| 6. 结构化日志 / SystemLogs | 未按旧仓形态迁入，已被新运行观测替代 | `freshquant/runtime_observability/*`、`/api/runtime/*`、`/runtime-observability`，RFC `0026` |
| 7. KlineSlim | 已落地并持续迭代 | `morningglory/fqwebui/src/views/KlineSlim.vue`、`/api/stock_data_chanlun_structure`，RFC `0005`、`0015`、`0018`、`0022` |
| 8. XGB / JYGS 数据同步 | 已落地到读模型链路 | `freshquant/data/gantt_readmodel.py` + Dagster，RFC `0006`、`0012` |
| 9. 甘特图 | 已落地统一页面、共享图表组件与接口 | `freshquant/rear/gantt/routes.py`、`GanttUnified.vue`、`GanttHistory.vue`，RFC `0006`、`0011`、`0012` |
| 10. Shouban30 / 缠论筛选 | 已纳入 Gantt 读模型、盘后快照与页面 | `/api/gantt/shouban30/*`、`freshquant/data/gantt_readmodel.py`、`GanttShouban30Phase1.vue`，RFC `0006`、`0012`、`0017`、`0023`、`0025`、`0027` |

---

## 0. TL;DR：10 个模块与旧仓库入口

1) **xtdata tick 生产者/消费者（替换 TDX 轮询分钟 bar）**
- Producer：`freshquant/market_data/xtdata/market_producer.py`
- Consumer：`freshquant/market_data/xtdata/strategy_consumer.py`
- 缓存/推送：`freshquant/util/period.py`、`freshquant/market_data/xtdata/clx_helper.py`、`freshquant/rear/websocket_server.py`

2) **Guardian 算法重构为系统策略**
- 策略：`freshquant/strategy/guardian.py`
- 监控入口：`freshquant/signal/astock/job/monitor_stock_zh_a_min.py`

3) **独立止盈止损模块**
- 止盈 Grid：`freshquant/strategy/grid.py`（配置/状态/去重：`freshquant/strategy/grid_*_manager.py`）
- 止损 StopLoss：`freshquant/strategy/stoploss.py`
- 单笔止损（按成交）：`freshquant/strategy/toolkit/fill_stoploss_helper.py`

4) **独立仓位管理模块（分控影响下单）**
- 配置：`freshquant/strategy/toolkit/position_manager.py`
- 风控：`freshquant/strategy/toolkit/position_risk_guard.py`
- 下单入队拦截：`freshquant/strategy/toolkit/order_manager.py`

5) **订单管理（下单入队 → broker 执行 → 落库/追踪/回调）**
- 生产端（策略）：`freshquant/strategy/toolkit/order_manager.py`
- 生产端（Web API）：`freshquant/rear/stock/trading_routes.py`（`POST /api/stock_order`）
- 执行端（broker/puppet）：`morningglory/fqxtrade/fqxtrade/xtquant/broker.py`、`morningglory/fqxtrade/fqxtrade/xtquant/puppet.py`
- 追踪与运维：`freshquant/strategy/toolkit/order_tracking_service.py`、`freshquant/strategy/toolkit/strategy_tracker.py`、`freshquant/command/order.py`

6) **独立结构化日志模块（并网页可视化）**
- 写入：`freshquant/logging/structured_logger.py`、`freshquant/logging/bar_monitor_structlog.py`、`freshquant/logging/guardian_signal_logger.py`
- API：`freshquant/rear/system_logs/routes.py`
- 前端：`morningglory/fqwebui/src/views/SystemLogs.vue`

7) **K 线行情模块：KlineSlim 页面**
- 前端：`morningglory/fqwebui/src/views/KlineSlim.vue`、`morningglory/fqwebui/src/views/js/kline-slim.js`
- 前端缓存/WS：`morningglory/fqwebui/src/utils/dataStore.js`、`morningglory/fqwebui/src/utils/websocket.js`
- 后端数据：`freshquant/rear/stock/data_routes.py`（`/api/stock_data`、`/api/stock/chanlun_structure`）

8) **数据同步模块（XGB/选股通 + JYGS/韭研公社 热点板块/热点股）**
- XGB 抓取/落库：`freshquant/data/xgb_cache_service.py`、`freshquant/dagster/jobs/xgb_cache_jobs.py`、`freshquant/dagster/schedules/xgb_cache_schedule.py`
- XGB 盘中快照 runner：`freshquant/data/job/xgb_cache_jobs.py`
- JYGS 盘中监控：`freshquant/signal/astock/job/monitor_jygs_combined.py`（调用 `monitor_jygs_action_yidong.py` 等）
- JYGS 盘后回补：`freshquant/dagster/ops/jygs_action.py` → `freshquant/signal/astock/job/jygs_action_backfill.py`

9) **甘特图绘制（板块/个股）**
- 后端接口：`freshquant/rear/xgt/cache_routes.py`（`/api/xgb/history/gantt/*`）、`freshquant/rear/jygs/gantt_routes.py`（`/api/jygs/history/gantt/*`）
- 生成逻辑：`freshquant/data/xgb_cache_service.py`、`freshquant/data/jygs_gantt_service.py`
- 前端页面/组件：`morningglory/fqwebui/src/views/GanttUnified.vue`、`morningglory/fqwebui/src/views/components/XgbHistoryGantt.vue`

10) **缠论股票筛选（30 日热门 → 缠论筛选 → 预选池/blk）**
- 后端路由：`freshquant/rear/gantt/shouban30_routes.py`
- 服务实现：`freshquant/data/gantt_shouban30_service.py`
- 缠论计算/过滤内核：`freshquant/tdx/toolkit/volume_turnover_screener.py`
- 前端页面：`morningglory/fqwebui/src/views/GanttShouban30.vue`、API：`morningglory/fqwebui/src/api/ganttShouban30.js`

---

## 1. 旧仓库整体运行形态（理解数据为什么“能跑起来”）

旧仓库并非单体应用，核心由几条“常驻链路”组成：

### 1.1 行情链路（xtdata）

- **Producer（订阅 tick → 聚合分钟 bar 事件）**：`freshquant/market_data/xtdata/market_producer.py`
  - 连接 `xtquant.xtdata`（无限重试等待 MiniQMT/QMT 就绪）
  - tick 回调尽量“轻量”：只合并进泵/写队列，避免阻塞 xtdata 推送线程
  - 输出：Redis List 队列（`FQ:QUEUE:BAR_EVENT:*`）写入 `BAR_CLOSE` 事件（按 code 分片）

- **Consumer（消费 BAR_CLOSE → fullcalc → 写 Redis 缓存 + Pub/Sub）**：`freshquant/market_data/xtdata/strategy_consumer.py`
  - `BLPOP` 读取队列分片，批处理 fullcalc（多进程/多线程）
  - 输出：
    - Redis K 线缓存：`CACHE:KLINE:<code>:<period_backend>`（详见 `freshquant/util/period.py`）
    - Pub/Sub：`CHANNEL:BAR_UPDATE`（供 WebSocket 推送给前端）

- **WebSocket 推送服务（订阅 BAR_UPDATE → 前端实时刷新）**：`freshquant/rear/websocket_server.py`
  - 前端协议：`{action:'subscribe', codes:[...]}` / `{action:'subscribe_all'}`；心跳 `ping/pong`

> 迁移意义：这条链路是“**从 xtdata 获取 tick 数据** + **消费者生产者模式**”的参考实现，也是“替换现有从 tdx 轮询 realtime 的分钟 bar”最直接的迁移对象。

### 1.2 盘中/盘后数据同步（XGB/JYGS）

- XGB（选股通）：
  - 盘中快照：写 `DBxuangugong.xgb_top_gainer_snapshot`（TTL 3 天）
  - 盘后回补/缓存：写 `DBxuangugong.xgb_top_gainer_history` / `xgb_theme_library` / `xgb_plate_detail` + 构建 `stock_plate`
  - Dagster 调度：`freshquant/dagster/schedules/xgb_cache_schedule.py`（默认工作日 15:30）

- JYGS（韭研公社）：
  - 盘中监控：写 `DBjiuyangongshe.jygs_yidong`（以及 `jygs_action_fields` 等）
  - 盘后回补：Dagster op `op_jygs_action_backfill_recent` 回补最近 N 天，修复漏抓/延迟

这些数据会被甘特图（模块 9）与 30 日热门/缠论筛选（模块 10）复用。

---

## 2. 模块 1：xtdata tick 生产者/消费者（替换 TDX 轮询分钟 bar）

### 2.1 Producer：tick → bar close 事件队列

- 文件：`freshquant/market_data/xtdata/market_producer.py`
- 关键点：
  - **Tick 泵模式**：只维护“最新 tick dict”，避免阻塞推送线程；支持 `FQ_TICK_PUMP_MODE`（coalesce/queue 等）
  - **BAR_CLOSE 事件**：按 1 分钟收敛生成事件，写 Redis list 队列
  - **动态订阅池**：按 guardian/supplement 分组 + 分片重订阅；PoolMonitor 定期检查池变化触发 resubscribe
  - **自愈**：tick stale / bar 不推进等会触发重连、重订阅
  - **可选 tick 落盘**：`freshquant/market_data/xtdata/tick_spooler.py` 写 JSONL，便于离线回放/排障

### 2.2 Consumer：BAR_CLOSE → fullcalc → Redis cache + Pub/Sub

- 文件：`freshquant/market_data/xtdata/strategy_consumer.py`
- 队列读取：
  - 常量：`freshquant/market_data/xtdata/constants.py`
  - Redis list key：`FQ:QUEUE:BAR_EVENT:{0..7}`（`REDIS_QUEUE_SHARDS=8`）
  - 只处理 `type=="BAR_CLOSE"` 的事件
  - 分片缓冲批处理：`SHARD_COUNT/SHARD_BATCH_SIZE/SHARD_FLUSH_TIMEOUT`（从 `constants.py` 导入）

- 写入与推送：
  - Redis K 线缓存（只对实时分钟周期）：`freshquant/util/period.py:get_redis_cache_key()`
    - Key：`CACHE:KLINE:<code>:<period_backend>`（例：`CACHE:KLINE:sz000001:5min`）
    - TTL：默认“当天 24:00”过期（`get_cache_expire_seconds()`）
    - meta：`CACHE:KLINE:meta:<code>:<period_backend>`（可选双写）
  - Pub/Sub：
    - channel：`CHANNEL:BAR_UPDATE`
    - publish：`freshquant/market_data/xtdata/clx_helper.py:HistoryDataManager.publish_bar_update()`
    - payload：`{code, period(frontend), timestamp, data: chanlun_data}`（其中 `data` 里包含 `code/period/date/...`）

### 2.3 WebSocket：前端实时刷新入口

- 服务：`freshquant/rear/websocket_server.py`
- 订阅：
  - 订阅单个：`{action:'subscribe', codes:[...]}`（codes 会 normalize 为 `sz000001` 形式）
  - 订阅全部：`{action:'subscribe_all'}`
- 数据：订阅 `CHANNEL:BAR_UPDATE` 并按订阅集推送原 payload（前端从 `data.data` 中取完整 K 线数据落入本地缓存）

### 2.4 迁移落点与验收建议

- **落点建议**：
  - 保留“事件队列 + Redis cache + Pub/Sub”的三段式边界（便于解耦：行情采集 vs 计算 vs 展示）
  - 迁移时优先对齐对外契约：`/api/stock_data` 的缓存命中 + WebSocket 推送的数据结构
- **验收建议**：
  - 09:30~15:00 长时间运行无“bar 不推进”
  - `/api/stock_data` 在实时周期（1m/3m/5m/15m/30m/60m/120m）能稳定命中 Redis
  - 前端 KlineSlim 在关闭轮询后仍能实时刷新（依赖 WS）

---

## 3. 模块 2：Guardian 算法（重构为系统策略）

- 文件：`freshquant/strategy/guardian.py`（`StrategyGuardian` 单例）
- 触发入口：`freshquant/signal/astock/job/monitor_stock_zh_a_min.py`（`strategy = StrategyGuardian()`）
- 关键逻辑（迁移时需保持语义一致）：
  - **阶段化结构化日志**：`freshquant/logging/guardian_signal_logger.py`（stage + summary，`req_id=signal_id`）
  - **仓位检查**：`freshquant/position/stock.py:query_stock_position_pct()`（读 `xt_assets.position_pct`）
  - **阈值/价格校验**：`eval_stock_threshold_price()`，以及 grid 买入/卖出价使用 ask1 等保护
  - **订单入队**：`freshquant/strategy/toolkit/order_manager.py:push_order_to_queue()`（下单前会走仓位风控）

迁移建议：将 Guardian 抽象为“系统级策略（System Strategy）”，把 **输入（行情/持仓/参数）** 与 **输出（订单意图/日志/状态）** 的接口稳定下来，再决定内部算法结构如何重构。

---

## 4. 模块 3：止盈止损（独立模块化）

### 4.1 止盈 Grid（三层 sell 价）

- 策略：`freshquant/strategy/grid.py`（`StrategyGrid`）
- 配置：Mongo `DBfreshquant.grid_configs`（`freshquant/strategy/grid_config_manager.py`）
- 状态：Redis `grid:active:{code}`（`grid_state_manager.py`）
- 去重：Redis `grid:trigger:{code}:{level}:{today}`（`grid_trigger_manager.py`）
- 现状特征：买入分层在策略侧被强制禁用，仅保留 `SELL-1/2/3` 分层卖出触发。

### 4.2 止损 StopLoss（全局 + 单笔）

- 全局止损配置：Mongo `stoploss_configs`（`freshquant/strategy/toolkit/stoploss_helper.py`）
- 单笔止损（按每条买入成交）：Mongo `fill_stoploss_configs`
  - 读取成交：`DBfreshquant.stock_fills`
  - 匹配模式：LIFO/FIFO（env `FILL_STOPLOSS_MATCH_MODE`）
  - 状态：`active/triggered`，触发后记录 trigger 信息

迁移建议：将止盈/止损从“策略内部逻辑”拆成独立模块（Policy/Rule），由策略在下单前后显式调用；并统一止损/止盈的**数据模型与生命周期**（配置 → 生效 → 触发 → 审计）。

---

## 5. 模块 4：仓位管理（分控影响下单）

- 配置读取：`freshquant/strategy/toolkit/position_manager.py`
  - Mongo：`DBfreshquant.params`（`code=xtquant`），字段：`total_position`、`daily_threshold`、`is_force_stop`
- 风控判断：`freshquant/strategy/toolkit/position_risk_guard.py`
  - `check_position_capacity(force=bool(order.force), source=...)`：超阈值拒单；`force` 可绕过并记录
- 生效点：`freshquant/strategy/toolkit/order_manager.py:push_order_to_queue()`
  - 买单入队前强制走 `check_position_capacity`

迁移建议：仓位管理应成为“全局服务”，策略只提交订单意图，最终是否允许下单由仓位服务做决策并返回可审计的 diagnostics。

---

## 6. 模块 5：订单管理（下单入队 → broker 执行 → 落库/追踪/回调）

### 6.1 Redis 队列与优先级（high/normal/low）

- 队列名：
  - normal：`freshquant_order_queue`
  - high：`freshquant_order_queue:high`
  - low：`freshquant_order_queue:low`
- 常量定义：
  - `freshquant/carnation/config.py`：`STOCK_ORDER_QUEUE` / `STOCK_ORDER_QUEUE_HIGH` / `STOCK_ORDER_QUEUE_LOW`
  - `freshquant/strategy/__init__.py`：`ORDER_QUEUE` / `ORDER_QUEUE_HIGH` / `ORDER_QUEUE_LOW`
  - `morningglory/fqxtrade/fqxtrade/__init__.py`：`ORDER_QUEUE` / `ORDER_QUEUE_HIGH` / `ORDER_QUEUE_LOW`
- 生产端队列选择（`freshquant/strategy/toolkit/order_manager.py:push_order_to_queue()`）：
  - `action` 以 `cancel` 开头 → `:high`
  - `action` 以 `sync-` 开头或 `sync-all` → `:low`
  - 其它（`buy/sell`）→ normal
- 执行端消费顺序（`morningglory/fqxtrade/fqxtrade/xtquant/broker.py`）：
  - `redis_db.brpop([ORDER_QUEUE_HIGH, ORDER_QUEUE, ORDER_QUEUE_LOW], 300)`：保证撤单/紧急动作优先

### 6.2 订单 payload（最小字段 + 扩展字段）

- 最小字段（策略/WEB 生产端一致）：
  - `action`：`buy|sell|sync-positions|sync-orders|sync-trades|sync-summary|sync-all|...`
  - `symbol` / `price` / `quantity`
  - `fire_time`
  - `strategy_name`
  - `remark`（用于策略追踪，见 6.5）
- 常见扩展字段（执行端会读取/透传）：
  - `retry_count`：重试次数（默认 0）
  - `force`：可绕过仓位风控（见 6.3/6.4 的 `check_position_capacity(force=...)`）
  - `ignore_risk`：跳过禁买 + 仓位风控（用于特殊入口，如打板相关）
  - `ignore_manual`：跳过“手动策略标的”过滤（用于部分订单来源）
  - `price_type`：卖出委托价格类型（由 broker 透传给 `puppet.sell()`）
  - `meta.req_id`：链路 id；生产端缺失时，broker 侧会补齐并写入 `broker:current_req_id`

### 6.3 生产端（策略下单入队 + Web API）

- 策略侧：`freshquant/strategy/toolkit/order_manager.py`
  - `create_buy_order/create_sell_order`：组装订单 dict（会生成/补齐 `remark`，并可写入 diagnostics）
  - `push_order_to_queue()`：
    - 买单：禁买标的 `is_buy_forbidden()` + 仓位风控 `check_position_capacity()`（`force` 可绕过并记录）
    - 卖单：对非回购标的做上限截断（防误操作大额卖出）：
      - `xtquant.max_sell_quantity`（默认 500000）
      - `xtquant.max_sell_amount`（默认 0 表示不限制）
    - 入队：`redis_db.lpush(queue_key, json.dumps(order))`，并补齐 `meta.req_id`

- Web 快捷下单：`freshquant/rear/stock/trading_routes.py`
  - `POST /api/stock_order`：以 `amount` 计算 `quantity`，解析/保护价，做禁买 + 仓位风控后写 `ORDER_QUEUE`

- Realtime 持仓刷新：`freshquant/rear/stock/position_routes.py`
  - 会把 `{"action":"sync-positions"}` 推到 `ORDER_QUEUE_LOW` 并等待 marker 更新（见 6.6）
  - 保护逻辑：若 `broker:current_action` 非空或 `broker:order_queue_len>0`，会跳过入队（避免挤占 broker 实时下单/撤单）

### 6.4 执行端（broker 消费队列 → puppet 对接 MiniQMT/QMT）

- 队列消费者：`morningglory/fqxtrade/fqxtrade/xtquant/broker.py`
  - 消费：`brpop([high, normal, low], 300)`，并补齐 `meta.req_id`
  - 分发：
    - `buy/sell` → `puppet.buy()` / `puppet.sell()`
    - `sync-positions` → `puppet.sync_positions_async()`（强调不阻塞消费线程）
    - `sync-orders/sync-trades/sync-summary/sync-all` → `puppet.sync_*()`（维护类动作）
  - watchdog/metrics（Redis）：
    - `broker:heartbeat`、`broker:last_queue_consume_ts`、`broker:current_action`、`broker:current_req_id`、`broker:current_action_started_ts`、`broker:order_queue_len`

- 交易 API 封装与落库：`morningglory/fqxtrade/fqxtrade/xtquant/puppet.py`
  - 下单前：基于 `remark` 解析更新策略跟踪状态（先置 `PENDING`）
  - 同步/落库（Mongo `DBfreshquant`）：
    - 委托：`xt_orders`
    - 成交：`xt_trades`
    - 持仓：`xt_positions`（由 `sync_positions` 写入）

### 6.4.1 截至 2026-03-11 的目标仓补充说明

下面三点是旧仓实现与目标仓当前治理最容易混淆的地方：

- 目标仓 `order_management` 虽然已独立成域模块，但它本身不是独立 Supervisor worker
  - 订单受理入口仍然是：
    - `Guardian`
    - `freshquant.rear.order.routes`
    - CLI `om-order`
  - 独立常驻的订单域 worker 当前只有 `freshquant.order_management.credit_subjects.worker`
- 目标仓若要跑完整交易链，宿主机需要额外常驻：
  - `freshquant.signal.astock.job.monitor_stock_zh_a_min --mode event`
  - `freshquant.position_management.worker`
  - `freshquant.tpsl.tick_listener`
- RFC `0030` 已落地的 `xtquant.value.broker_submit_mode=observe_only` 语义是：
  - broker 仍消费订单队列并产出运行观测
  - `buy / sell / cancel` 全部不与券商交互
  - 不生成 synthetic XT 回报
  - 不改真实持仓、真实仓位、真实 TPSL 事实
  - 订单状态将进入显式状态 `BROKER_BYPASSED`

### 6.5 订单追踪（remark 生命周期 + per-strategy collection）

- 入口：
  - `freshquant/strategy/toolkit/order_tracking_service.py`
  - `freshquant/strategy/toolkit/strategy_tracker.py`
- remark 格式：`策略简称|信号简写|时间|价格|来源`（示例：`guardian|buy_v|0829_1430|10.58|chan_1m`）
- 集合：`DBfreshquant.strategy_orders_<strategy>`（例如 `strategy_orders_guardian`）
  - 状态机：`PENDING → SUBMITTED → PARTIAL_FILLED/FILLED → CANCELED/FAILED`

### 6.6 运维/工具面（查询/清理 + marker）

- CLI：`freshquant/command/order.py`（`xt-order list/rm` 操作 `DBfreshquant.xt_orders`）
- marker：
  - `xt_positions:last_sync`：`puppet.sync_positions_async/sync_positions` 结束后更新；API `realtime=1` 可据此等待“持仓已刷新”

迁移建议：把“订单意图（Order Intent）→ 执行（Broker/Puppet）→ 状态回写/追踪（Tracking）”拆成清晰边界；优先保持队列优先级语义与可观测性（metrics + `req_id`），并在 RFC 中明确消息语义（`brpop` 取出即删，是否需要幂等/补偿/重放）。

---

## 7. 模块 6：结构化日志（JSONL）与网页可视化

### 7.1 写入端

- `freshquant/logging/structured_logger.py`
  - 非阻塞 JSONL spooler
  - 目录：`<root>/<component>/<YYYY-MM-DD>/<component>_structured_<YYYY-MM-DD>_<pid>.jsonl`
  - root 默认：`D:/fqpack/logs/structured`（env：`FQPACK_STRUCT_LOG_DIR`）
- `freshquant/logging/bar_monitor_structlog.py`
  - Producer/Consumer 的启动、心跳、lag/backlog、xtdata reconnect 等监控事件统一写 struct log
- `freshquant/logging/guardian_signal_logger.py`
  - Guardian 的 stage 日志落 struct log（可按 req_id 串起来）

### 7.2 读取端（后端 API + 前端）

- 后端：`freshquant/rear/system_logs/routes.py`
  - `/api/system_logs/components|dates|files|tail`：列目录、读文件尾部
- 前端：`morningglory/fqwebui/src/views/SystemLogs.vue`

迁移建议：保留“**结构化日志（落盘）→ HTTP tail → 前端可视化**”链路，可作为运行节点可视化的最小闭环；后续再考虑接入 OpenTelemetry/集中式日志。

---

## 8. 模块 7：KlineSlim（K 线行情）页面

### 8.1 前端结构与数据流

- 路由：`morningglory/fqwebui/src/router/index.js` → `/kline-slim`
- 页面：`morningglory/fqwebui/src/views/KlineSlim.vue`
- 逻辑：`morningglory/fqwebui/src/views/js/kline-slim.js`
  - 使用 `@tanstack/vue-query`：queryKey = `(symbol, period, endDate)`
  - 核心拉取函数：`getStockData()`（来自 `src/utils/dataStore.js`）
  - **关闭轮询**：`refetchInterval=false`，依赖 WebSocket 实时推送刷新本地缓存

### 8.2 前端 3 级缓存（local → redis → db）

- `morningglory/fqwebui/src/utils/dataStore.js:getStockData()`
  1. **本地缓存**：WebSocket 推送数据落 `localCache`（Map）
  2. **Redis 缓存**：调用 `/api/stock_data?symbol=&period=`（实时周期）
  3. **数据库**：调用 `/api/stock_data?symbol=&period=&endDate=&useAnalysis=true`（历史或 cache miss）

### 8.3 WebSocket 客户端

- `morningglory/fqwebui/src/utils/websocket.js`
  - 连接：`/ws/market`（默认走 Nginx 代理；可用 `VITE_WS_URL/VITE_WS_PORT` 覆盖）
  - 收到消息时：若 `data.data.date` 存在，则 `handleWebSocketData(data.data)` 写入本地缓存

### 8.4 后端接口（K 线与多周期缠论摘要）

- K 线：`freshquant/rear/stock/data_routes.py`
  - `GET /api/stock_data`
    - period 会被统一为前端格式（如 `5min→5m`）
    - 对实时周期且无 endDate：优先读 Redis（`CACHE:KLINE:*`），否则回落 `get_data_v2_analysis/get_data_v2/get_data_v3`
    - `useCache=true`：强制只读缓存，miss 返回 404（用于排障/避免 DB 压力）
  - `GET /api/stock/chanlun_structure`
    - 从 Redis 缓存推导 summary，失败则兜底 `build_structure_summary()`
    - 返回形态：`{symbol, period_list(frontend), periods:{'5m':{higher_segment,...}}, errors, generated_at}`

迁移建议：KlineSlim 的关键不是 Vue/ECharts，而是“**后端数据契约**”（`/api/stock_data` + WS 推送 + period/code 归一化）。迁移时先把这条契约稳定下来，再决定 UI 是否复用或重写。

---

## 9. 模块 8：数据同步（XGB + JYGS 热点板块/热点股）

### 9.1 XGB（选股通）

- 数据抓取/落库：`freshquant/data/xgb_cache_service.py`
  - 外部接口：`https://flash-api.xuangubao.cn/api/*`、`https://xuangutong.com.cn/top-gainer`
  - 核心集合（Mongo `DBxuangugong`）：
    - `xgb_top_gainer_snapshot`：盘中快照（TTL 3 天）
    - `xgb_top_gainer_history`：盘后历史（按 `trade_date, plate_id`）
    - `xgb_theme_library`：题材库
    - `xgb_plate_detail`：题材详情（stocks 甘特 tooltip 的 desc 也会用到）
    - `stock_plate`：股票-题材映射缓存（由 `freshquant/screening/build_stock_plate_cache.py` 构建）

- 调度：
  - Dagster：`freshquant/dagster/schedules/xgb_cache_schedule.py` → `freshquant/dagster/jobs/xgb_cache_jobs.py:xgb_cache_job`
    - 顺序：history → theme → detail → stock_plate（严格串行）
  - 盘中快照 runner（可接 supervisor/cron）：`freshquant/data/job/xgb_cache_jobs.py:job_topgainer_realtime()`

### 9.2 JYGS（韭研公社）

- 盘中监控：`freshquant/signal/astock/job/monitor_jygs_combined.py`
  - 线程化跑：industry chain / ztjt / yidong（交易时段 gating）
  - yidong 落库：`monitor_jygs_action_yidong.py` → `DBjiuyangongshe.jygs_yidong`
  - 板块题材原因：`DBjiuyangongshe.jygs_action_fields`（供 30 日模块补充 plate_reason）

- 盘后回补（修复漏抓/延迟）：
  - Dagster op：`freshquant/dagster/ops/jygs_action.py:op_jygs_action_backfill_recent`
  - 实现：`freshquant/signal/astock/job/jygs_action_backfill.py`

迁移建议：两类数据源的同步应抽象为“数据资产（Assets）”或“可重放 job”，并把**集合 schema + 更新时间语义**写进 RFC（否则后续甘特/筛选很难稳定验收）。

---

## 10. 模块 9：甘特图（板块/个股热力矩阵）

这部分旧仓库已经有较完整的工程化落地说明（可作为迁移验收口径参考）：
- 旧仓库文档：`D:\fqpack\freshquant\docs\ui\gantt_unified_implementation.md`

### 10.1 前端（统一组件渲染 xgb/jygs 两种数据）

- 页面：
  - `morningglory/fqwebui/src/views/GanttUnified.vue`：`/#/gantt?p=xgb|jygs&days=...`
  - `morningglory/fqwebui/src/views/GanttUnifiedStocks.vue`：`/#/gantt/stocks/:plateId?p=xgb|jygs`
- 组件：`morningglory/fqwebui/src/views/components/XgbHistoryGantt.vue`
  - 统一要求后端返回：`{dates,y_axis,series}`，并在前端追加 streak/color 等渲染字段

### 10.2 后端接口与返回结构（统一形态）

- XGB：
  - `GET /api/xgb/history/gantt/plates` → `freshquant/data/xgb_cache_service.py:get_gantt_plates_matrix()`
  - `GET /api/xgb/history/gantt/stocks?plate_id=...` → `get_gantt_stocks_matrix()`
- JYGS：
  - `GET /api/jygs/history/gantt/plates` → `freshquant/data/jygs_gantt_service.py:get_gantt_plates_matrix()`
  - `GET /api/jygs/history/gantt/stocks?plate_id=...` → `get_gantt_stocks_matrix()`

统一返回（前端实际取 `res.data`）：
```json
{ "code": 200, "message": "OK", "data": { "dates": [], "y_axis": [], "series": [] }, "meta": {} }
```

### 10.3 series 结构（需要保持兼容）

- plates：`series[i] = [dateIndex, yIndex, rank, hotCount, limitUpCount, hotStocks]`
- stocks：`series[i] = [dateIndex, yIndex, activeStreakDays, isLimit, desc]`

### 10.4 额外能力：导出/追加 TDX blk

- XGB：`POST /api/xgb/plate/<plateId>/export/tdx-blk/jqzt`
- JYGS：`POST /api/jygs/plate/export/tdx-blk/jqzt`
- 落盘目录：`D:\tdx_biduan\T0002\blocknew`（见 `xgb_cache_service.py` 常量 `TDX_BLK_EXPORT_DIR`）

迁移建议：甘特图本质是“稳定的数据契约 + 一致的 series 语义”。迁移时建议优先复刻后端矩阵生成函数与返回结构，前端可以先不动。

---

## 11. 模块 10：30 日热门 → 缠论筛选 → 预选池/blk（Shouban30 + Chanlun）

### 11.1 30 日导出（plates/stocks 落库）

- 路由：`freshquant/rear/gantt/shouban30_routes.py`
  - `POST /api/gantt/shouban30/export`
  - `GET /api/gantt/shouban30/plates`
  - `GET /api/gantt/shouban30/stocks`
  - `GET /api/gantt/shouban30/stocks/reasons`
- 服务：`freshquant/data/gantt_shouban30_service.py:export_shouban30()`
  - 输入：
    - XGB：`DBxuangugong.xgb_top_gainer_history`
    - JYGS：`DBjiuyangongshe.jygs_yidong` + `jygs_action_fields`（plate_reason）
  - 输出（Mongo `DBpipeline`）：
    - `gantt_shouban30_plates`
    - `gantt_shouban30_stocks`（含 `hit_count_90/hit_count_30/reasons/last_reason`）

### 11.2 缠论 calc（SSE 计算 + 缓存落库）

- SSE：`GET /api/gantt/shouban30/chanlun/calc/stream`
- 服务：`freshquant/data/gantt_shouban30_service.py:iter_chanlun_calc_for_exported_stocks()`
  - union candidates：对 `gantt_shouban30_stocks` 按 `code6` 去重，并携带 `plates_by_provider/last_hit_*` 元信息
  - fullcalc 内核：`freshquant/tdx/toolkit/volume_turnover_screener.py:VolumeTurnoverScreener`
    - 60min + 15min 两套 fullcalc（model_ids 置空，只要缠论结构与段端点）
    - `require_fullcalc=true` 时，fullcalc 不可用将导致该 code 计算失败
  - 缓存写入：`DBpipeline.gantt_shouban30_chanlun_calc`（unique：`as_of_date+code6`）

### 11.3 缠论 filter（从缓存过滤 + 覆盖写 blk）

- HTTP：`POST /api/gantt/shouban30/chanlun/filter`
  - 从 `gantt_shouban30_chanlun_calc` 读取 `calc_meta`，用纯函数 `_filter_from_calc_meta()` 应用阈值：
    - `max_gain_multiple`（默认 2.5）
    - `last_up_seg_max_gain_percent`（默认 30，可置空禁用）
    - 以及按倍数区间分组（`gain_multiple_min/max/include_none`）
  - 默认会覆盖写 `30RYZT.blk`（保持 UI 顺序与 blk 顺序一致）
  - 排序默认 `plate_multiple`（跨 provider 的 plate 去重逻辑在 `shouban30_routes._sort_chanlun_items()`）

### 11.4 预选池（DBpipeline.sanshi_zhangting_pro）与监控模式

- pool 集合：`DBpipeline.sanshi_zhangting_pro`
  - upsert：`gantt_shouban30_service.upsert_sanshi_zhangting_pro_pool_codes()`（默认过期：次日 09:20）
  - list：`list_sanshi_zhangting_pro_pool_items()`（默认过滤过期，并按最新 trade_date_str 收敛）
- 用途：
  - Producer：`market_producer.py` 在 `monitor_range=sanshi_zhangting_pro` 时从该 pool 读取订阅列表
  - Consumer：`strategy_consumer.py` 在该模式下也会尽早丢弃非池内事件，实现“只算池内标的”

迁移建议：该模块牵涉“数据源 → 导出落库 → 缓存计算 → 阈值过滤 → 池/blk 落地 → 行情订阅范围收敛”的闭环，是后续迁移中最需要 **先写 RFC 明确边界与验收** 的部分（尤其是：as_of_date 语义、blk 写入路径、fullcalc 可用性判定、排序/去重规则）。
