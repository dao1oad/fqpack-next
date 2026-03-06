# 破坏性变更清单（Breaking Changes）

> 任何破坏性变更落地时必须追加记录，并引用对应 RFC。若接口区域发生实现调整但无破坏性，也在此登记。

## 记录模板

- **日期**：YYYY-MM-DD
- **RFC**：NNNN-<topic>
- **变更**：做了什么不兼容或重要的接口调整
- **影响面**：哪些模块、脚本、服务或用户会受到影响
- **迁移步骤**：如何升级
- **回滚方案**：如何撤回

## 变更记录

- **日期**：2026-03-05
- **RFC**：0002-etf-qfq-adj-sync
- **变更**：ETF K 线查询默认从 `bfq` 调整为 `qfq`，通过新增 `quantaxis.etf_xdxr/etf_adj` 并在查询侧应用复权因子实现。
- **影响面**：依赖 `freshquant/quote/etf.py` 或 `freshquant/chanlun_service.py:get_data_v2()` 的策略、回测和可视化结果可能变化。
- **迁移步骤**：如需保留 `bfq`，请直接读取底层原始集合或回滚本变更。
- **回滚方案**：移除 ETF 查询侧对 `etf_adj` 的应用逻辑，并停用 `etf_xdxr/etf_adj` 同步资产。

- **日期**：2026-03-05
- **RFC**：0003-xtdata-producer-consumer-fullcalc
- **变更**：A 股分钟实时链路从“TDX 轮询 realtime + `monitor_stock_zh_a_min.py` 轮询 `get_data_v2`”切换为“XTData Producer/Consumer 事件驱动 + fullcalc 统一推送结构”；Guardian 改为订阅 `CHANNEL:BAR_UPDATE`（`--mode event`）。
- **影响面**：
  - 部署不再需要启动 TDX realtime 采集进程（如 `freshquant.market_data.stock_cn_a_collector`），避免双写；
  - 分钟监控默认依赖 Redis Pub/Sub + Redis List 队列 + MiniQMT/XTData；
  - `DBfreshquant.stock_realtime/index_realtime` 的写入来源变更为 XTData Consumer（股票写入 qfq，ETF 写入 bfq；ETF 查询侧仍应用 qfq）。
- **迁移步骤**：
  1) Mongo params：设置 `monitor.xtdata.mode` 为 `guardian_1m` 或 `clx_15_30`（严格二选一，重启进程生效），并设置 `monitor.xtdata.max_symbols<=50`；
  2) 启动 `python -m freshquant.market_data.xtdata.market_producer`（需 MiniQMT）；
  3) 启动 `python -m freshquant.market_data.xtdata.strategy_consumer --prewarm`；
  4) Mode A 时启动 `python -m freshquant.signal.astock.job.monitor_stock_zh_a_min --mode event`（替代轮询）。
- **回滚方案**：停止上述 Producer/Consumer/Guardian(event) 进程，恢复启动旧的 TDX realtime 采集链路与 Guardian 轮询模式（`--mode poll` 或旧脚本链路）。

- **日期**：2026-03-06
- **RFC**：0005-kline-slim-mvp-5m-30m-overlay
- **变更**：无对外破坏性变更。`/api/stock_data` 新增 **opt-in** 的 Redis-first 实时查询路径，仅当请求显式带 `realtimeCache=1`（或 `true/yes`）且属于实时支持周期时才启用；默认请求继续保持 `get_data_v2()` 返回契约。前端新增 `/kline-slim` 页面，并在无 `endDate` 的实时模式下默认附带该参数。
- **影响面**：`KlineSlim` 实时页面会优先从 Redis 缓存取数；旧页面、历史查询与非支持周期行为不变。
- **迁移步骤**：旧调用方无需调整。如需让新页面也关闭该路径，可移除 `realtimeCache=1` 参数或回退到 `get_data_v2()` 全量计算路径。
- **回滚方案**：移除 `/api/stock_data` 的 `realtimeCache` 分支，前端下线 `/kline-slim` 或继续使用纯 fallback 请求。

- **日期**：2026-03-06
- **RFC**：0006-gantt-postclose-readmodel
- **变更**：新增独立 MongoDB 分库 `freshquant_gantt` 承载 XGB/JYGS 原始同步与 `plate_reason_daily/gantt_*/shouban30_*` 读模型；新增统一最小接口 `/api/gantt/*`，且只保留盘后 Dagster 更新，不再兼容旧分支盘中 snapshot 注入与板块理由 fallback。
- **影响面**：
  - 依赖旧分支 `/api/xgb/*`、`/api/jygs/*`、旧 `/api/gantt/shouban30/*` 返回结构的页面或脚本不能直接复用；
  - 运维需要额外备份 `freshquant_gantt`，不能再假设专题数据写入 `freshquant` 主库；
  - 缺失板块理由将直接导致读模型构建失败，而不是静默降级。
- **迁移步骤**：
  1) 配置 `mongodb.gantt_db=freshquant_gantt`（或环境变量 `FRESHQUANT_MONGODB__GANTT_DB`）；
  2) 部署并启用 `job_gantt_postclose` / `gantt_postclose_schedule`；
  3) 页面或调用方切换到 `/api/gantt/plates`、`/api/gantt/stocks`、`/api/gantt/shouban30/plates`、`/api/gantt/shouban30/stocks`；
  4) 停用旧分支依赖的盘中实时 Gantt/Shouban30 读取链路。
- **回滚方案**：停用 `gantt_postclose_schedule` 与 `/api/gantt/*` 新接口，保留 `freshquant_gantt` 数据不删库；调用方退回旧分支页面/API。

- **日期**：2026-03-06
- **RFC**：0007-stock-etf-order-management
- **变更**：无破坏性接口变更。本轮在公共接口区新增 `fqctl om-order`、`/api/order/*`、`/api/order-management/*`，并将 Guardian 与 `xtquant buy/sell/cancel` 下单入口切换到新的订单域受理层；旧 `/api/stock_order` 以兼容适配方式保留。另将旧 `stock_fills` 人工写入口（`freshquant/data/astock/fill.py`、`freshquant/toolkit/import_deals.py`、`/api/stock_fills/reset`）改为先写 `freshquant_order_management.om_*` 主账本，再由兼容投影视图对外提供 `stock_fills` 语义；`clean_stock_fills()` / `compact_stock_fills()` 只保留 legacy `stock_fills` 集合维护，不再作为订单事实写入口。
- **影响面**：CLI、HTTP API、Guardian 策略入口与 XTQuant CLI 现在都会先生成 `om_*` 主账本记录，再进入执行队列；人工导入、重置网格与后续排障也需要优先查看 `internal_order_id`、`buy_lot_id`、`trade_fact_id` 等订单域标识，而不是假设 `freshquant.stock_fills` 是主事实表。
- **迁移步骤**：优先改用 `fqctl om-order submit/cancel`、`/api/order/submit`、`/api/order/cancel`、`/api/order-management/buy-lots/<buy_lot_id>`、`/api/order-management/stoploss/bind`；若仍依赖 `/api/stock_order`，可继续使用兼容入口。对于手工导入与网格 reset，不再直接写 `freshquant.stock_fills`，而是通过现有 CLI/API 入口触发订单域手工写服务。
- **回滚方案**：回退 `freshquant/rear/order/routes.py`、`freshquant/cli.py`、`freshquant/strategy/guardian.py`、`morningglory/fqxtrade/fqxtrade/xtquant/cli_commands.py`、`freshquant/data/astock/fill.py`、`freshquant/toolkit/import_deals.py`、`freshquant/rear/stock/routes.py` 与 broker/puppet 桥接改动，恢复旧的直接队列写入与 `stock_fills` 直接写入路径。

- **日期**：2026-03-06
- **RFC**：0007-stock-etf-order-management
- **变更**：无破坏性接口变更。为保证 CI 与 Linux runner 下的一致性，`morningglory/fqxtrade/fqxtrade/xtquant/cli_commands.py` 与 `freshquant/position/cn_future.py` 去除了对 `pendulum` 的硬依赖，`freshquant/rear/stock/routes.py` 为缺失 `func_timeout` 的环境增加了兼容 fallback，`freshquant/order_management/ingest/xt_reports.py` 将 XT 回报时间统一按 `Asia/Shanghai` 解释，避免日期受宿主机时区漂移。
- **影响面**：`xtquant sync-*` CLI 的 `fire_time` 现在由标准库 `datetime` 生成；最小依赖环境下导入股票路由与期货持仓读模块不再因缺失 `pendulum/func_timeout` 失败；Linux/UTC 环境下订单回报日期与中国市场语义保持一致。
- **迁移步骤**：调用方无需调整；若依赖旧的本地时区推断行为，应统一改为以中国市场时区解释 XT 时间戳。
- **回滚方案**：恢复 `pendulum`、移除 `func_timeout` fallback，并将 XT 回报时间恢复为宿主机本地时区解释。

- **日期**：2026-03-06
- **RFC**：0007-stock-etf-order-management
- **变更**：无破坏性接口变更。`freshquant/order_management/reconcile/service.py` 在将成交回报外部化之前，先对 `ACCEPTED/QUEUED/SUBMITTING` 且尚未回填 `broker_order_id` 的内部订单做匹配，避免在途内部单被误建成外部订单；`freshquant/rear/order/routes.py` 将 `/api/stock_order` 的非数字 `quantity` 输入统一转换为 400 参数错误，而不再抛出 500。
- **影响面**：XT 成交回报早于 `broker_order_id` 回填时，会优先回写到已有内部订单，不再生成重复的 `external_reported` 订单；依赖 `/api/stock_order` 的调用方在传入非法 `quantity` 时将稳定收到 400 与错误消息 `quantity must be numeric`。
- **迁移步骤**：调用方无需修改成功路径；如有依赖非法 `quantity` 触发 500 的外部监控，应改为按 400 参数错误处理。
- **回滚方案**：恢复 `reconcile_trade_reports()` 的旧外部化判定与 `/api/stock_order` 对 `quantity` 的直接 `int()` 转换逻辑。

- **日期**：2026-03-07
- **RFC**：0007-stock-etf-order-management
- **变更**：无破坏性接口变更。`freshquant/data/astock/holding.py:get_stock_holding_codes()` 的读取口径从“仅订单域持仓投影”调整为“`xt_positions` 与订单域持仓投影并集”，并为 holding codes 缓存增加 15 秒 TTL 兜底；`freshquant/order_management/ingest/xt_reports.py` 在真实持仓变化后主动触发 `mark_stock_holdings_projection_updated()`。
- **影响面**：Guardian、交易池与其他依赖 `get_stock_holding_codes()` 的路径，会更早把券商端新增但尚未完全入账的外部持仓代码识别为持仓股；漏掉显式失效时，holding codes 最长约 15 秒自动收敛。
- **迁移步骤**：调用方无需修改；若有依赖旧的“仅投影口径”行为做调试脚本，应改为同时接受 `xt_positions` 带来的更早识别结果。
- **回滚方案**：回退 `freshquant/data/astock/holding.py` 与 `freshquant/order_management/ingest/xt_reports.py` 的本次改动，恢复 holding codes 仅依赖订单域持仓投影且只靠版本号失效。
