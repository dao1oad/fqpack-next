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

- **RFC**：0009-project-local-uv-python-312
- **变更**：宿主机与 Docker 的 Python 运行面统一切换到项目内 `.venv`；FreshQuant `docker/Dockerfile.rear` 与 `third_party/tradingagents-cn/Dockerfile.backend` 改为通过 `uv sync --frozen` 构建运行环境，CI 也改为基于 `uv` 同步锁定依赖。`TA-Lib` Python 包升级到 `0.6.8`，改为直接使用带 wheel 的发行版，不再依赖宿主机 MSI 或容器内 `.deb` 的前置安装链路。`docker/compose.parallel.yaml` 允许通过 `FQNEXT_REAR_IMAGE`、`FQNEXT_WEBUI_IMAGE`、`FQNEXT_TA_BACKEND_IMAGE`、`FQNEXT_TA_FRONTEND_IMAGE` 覆盖镜像标签，并将 `Dockerfile.rear` 的构建收口到单一服务复用；`ta_backend` 在本地并行 Compose 下若未显式提供 `JWT_SECRET`，会回落到开发默认值 `change-me-in-production`。
- **影响面**：`Miniconda fqkit` 不再是标准运行环境；宿主机脚本、Docker 命令、CI 和后续 Supervisor 都需要以项目 `.venv` 为准。依赖旧的 `pip install ./...`、`pip install -r freeze.txt`、外部 Python/conda 环境或容器内系统级 `TA-Lib` 安装的部署脚本需要调整。多 worktree / 多分支并行验证时，如需隔离镜像缓存与标签，需要显式覆盖 `FQNEXT_*_IMAGE`；生产环境若使用 TradingAgents-CN，应显式配置非默认 `JWT_SECRET`。
- **迁移步骤**：1) 在仓库根目录执行 `create_venv.bat` 与 `install.bat --skip-web`；2) 日常命令统一改为 `uv run ...` 或 `.venv\Scripts\python.exe ...`；3) Docker 改用 `docker compose -f docker/compose.parallel.yaml up -d --build`，由镜像内 `.venv` 启动；如在多个 worktree / 分支间并行验证，先覆盖 `FQNEXT_*_IMAGE`；4) TradingAgents-CN 后端使用 `third_party/tradingagents-cn/uv.lock` 构建 `/app/.venv`，并在生产环境显式设置 `JWT_SECRET`。
- **回滚方案**：恢复 `install.bat/install.py` 的旧顺序、恢复 Dockerfile 中的 `pip install` 链路与外部 `TA-Lib` 安装步骤，并将宿主机服务命令切回原 `Miniconda fqkit` 解释器。

- **日期**：2026-03-07
- **RFC**：0008-tradingagents-cn-integration-phase1
- **变更**：`TradingAgents-CN` 接入层的默认深度分析模型从 `deepseek-chat` 调整为 `deepseek-reasoner`，并在 `ta_backend` 启动时自动把活动系统配置与 DeepSeek 模型目录迁移到该默认值；若 `deepseek-reasoner` 仅在工具调用兼容链路失败，则自动回退到 `deepseek-chat` 继续任务。
- **影响面**：依赖 `TradingAgents-CN` 默认模型配置的页面、脚本和运维流程会观察到 `deep_analysis_model` 默认值变化；模型目录中新增 `deepseek-reasoner`，启动后活动配置会被自动补齐。
- **迁移步骤**：重新构建并启动 `ta_backend` / `ta_frontend`；登录后可在 `/api/config/settings` 或前端配置页确认 `quick_analysis_model=deepseek-chat`、`deep_analysis_model=deepseek-reasoner`。若要恢复旧行为，可在系统配置里手动改回 `deepseek-chat`。
- **回滚方案**：移除 `bootstrap_reasoner_defaults` 启动步骤，恢复 `deepseek-chat` 为默认深度模型，并删除 `deepseek-reasoner` 的默认注册与回退逻辑。

- **日期**：2026-03-07
- **RFC**：0010-host-runtime-docker-mongo-alignment
- **变更**：Docker 并行模式下，宿主机 `broker / xtdata producer / xtdata consumer` 的推荐运行时事实源从宿主机 Mongo `127.0.0.1:27017` 与宿主机 Redis `127.0.0.1:6379` 调整为 Docker Mongo `127.0.0.1:27027` 与 Docker Redis 宿主机映射端口 `127.0.0.1:6380`；同时 `broker` 连接 MiniQMT 时不再忽略 `xtquant.account_type`，会按 `CREDIT/STOCK` 等真实账户类型构造 `StockAccount`。
- **影响面**：实盘排障时需要优先查看 Docker `freshquant.params / xt_positions / xt_trades`，并通过 Docker Redis 队列观察宿主机 `broker / xtdata producer / xtdata consumer` 的消息流，而不再假设宿主机 `27017/6379` 是事实源；使用信用账户的 MiniQMT broker 现在会按真实账户类型连入，持仓同步结果将发生变化。
- **迁移步骤**：
  1. 在宿主机环境文件中显式设置 `FRESHQUANT_MONGODB__HOST=127.0.0.1`、`FRESHQUANT_MONGODB__PORT=27027`、`FRESHQUANT_REDIS__HOST=127.0.0.1` 与 `FRESHQUANT_REDIS__PORT=6380`；
  2. 对 Docker `freshquant` 库执行 `python -m freshquant.initialize --quiet`；
  3. 将宿主机旧库中的 `freshquant.params` 同步到 Docker `freshquant.params`；
  4. 重启宿主机 `broker / xtdata producer / xtdata consumer`。
- **回滚方案**：将宿主机 Mongo/Redis 端口改回 `27017/6379` 并重启宿主机进程；如需恢复旧 broker 行为，回退 `morningglory/fqxtrade/fqxtrade/xtquant/broker.py` 与 `morningglory/fqxtrade/fqxtrade/xtquant/account.py` 的账户类型修复。

- **RFC**：0011-stock-etf-tpsl-module
- **变更**：已落地 XTData `TICK_QUOTE` Redis 队列协议（`QUEUE:TICK_QUOTE:*`）、独立 `freshquant.tpsl` 模块、`/api/tpsl/*` 后端接口，以及订单域 `takeprofit_batch / stoploss_batch` 作用域。止盈止损运行时状态迁移到 `om_takeprofit_profiles / om_takeprofit_states / om_exit_trigger_events`，不再沿用旧分支 `grid_configs / stoploss_configs / fill_stoploss_configs` 执行链。
- **影响面**：XTData producer、独立 TPSL worker、后端 API、订单受理层与运维脚本都需要切换到新模块；依赖旧 `monitor_stock_zh_a_min.py` 中 Grid/StopLoss tick 执行链的运维方式不再适用。
- **迁移步骤**：
  1) 部署包含 `freshquant.tpsl` 与 `/api/tpsl/*` 的新代码；
  2) 启动 `python -m freshquant.market_data.xtdata.market_producer`，确保 `QUEUE:TICK_QUOTE:*` 正常推送；
  3) 启动 `python -m freshquant.tpsl.tick_listener` 作为独立 TPSL worker；
  4) 通过 `/api/tpsl/takeprofit/<symbol>` 配置三层止盈，通过现有 `/api/order-management/stoploss/bind` 绑定 `buy_lot` 单笔止损；
  5) 调用方若要识别新批次卖单，应兼容 `scope_type=takeprofit_batch|stoploss_batch`。
- **回滚方案**：停止 `freshquant.tpsl.tick_listener`，回退 `market_producer.py` 的 `TICK_QUOTE` 推送、`/api/tpsl/*` 蓝图注册与 `takeprofit_batch / stoploss_batch` 相关代码，恢复旧分支的 Grid/StopLoss 执行链或仅保留 `RFC 0007` 的 `buy_lot` 止损绑定能力。
- **日期**：2026-03-07
- **RFC**：0013-position-management
- **变更**：新增独立分库 `freshquant_position_management` 与模块 `freshquant/position_management/`，策略订单在 `OrderSubmitService` 受理前会先读取仓位状态做门禁；人工/API/CLI 手工单继续旁路。对于 `FORCE_PROFIT_REDUCE` 状态下的 Guardian 盈利卖点，本轮只新增占位标志透传到队列，不实现最终强制卖出算法。
- **影响面**：所有 `source=strategy` 的股票/ETF 订单都会新增一层仓位准入判断；当仓位状态缺失或过旧时，策略买入会按默认保守状态 `HOLDING_ONLY` 处理。运维需要备份独立分库 `freshquant_position_management`，并确保独立 worker 周期刷新 `pm_current_state`。
- **迁移步骤**：1) 配置 `position_management.mongo_database`、`xtquant.account_type=CREDIT`、`xtquant.account`、`xtquant.path`；2) 启动 `python -m freshquant.position_management.worker` 持续刷新信用资产；3) 确认 `pm_current_state` 正常更新后，再让 Guardian 等策略通过 `OrderSubmitService` 发单；4) 若后续实现 Guardian 强制减仓算法，应继续沿用当前 `position_management_force_profit_reduce/profit_reduce_mode` 占位字段。
- **回滚方案**：回退 `freshquant/order_management/submit/service.py` 与 `freshquant/position_management/*` 的接入改动，停用仓位管理 worker，并保留 `freshquant_position_management` 历史快照用于排障。
