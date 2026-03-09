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

- **日期**：2026-03-09
- **RFC**：0026-gantt-shouban30-filters-and-reason-popovers
- **变更**：`/api/gantt/shouban30/stocks` 已新增 `is_credit_subject / near_long_term_ma_passed / is_quality_subject` 及其辅助字段；`/gantt/shouban30` 页面已新增 `融资标的 / 均线附近 / 优质标的` 三个交集筛选按钮，并将理由展示从默认 `show-overflow-tooltip` 切换为卡片式 `el-popover`。盘后构建链现已新增 `quality_stock_universe` 基础集合，用于固化旧分支固定优质 `block_names` 名单对应的股票集合。
- **影响面**：直接消费 `/api/gantt/shouban30/stocks` 的调用方、`/gantt/shouban30` 页面用户、Dagster 盘后任务耗时与数据链路、以及依赖旧 tooltip 展示与无额外筛选页面行为的截图/文档都会受到影响。
- **迁移步骤**：1) 部署包含 RFC 0026 的后端、Dagster 和前端代码；2) 运行或等待 `job_gantt_postclose` 更新优质基础集合并重建目标交易日 `shouban30`；3) 调用方按新字段读取三类筛选标记；4) 页面用户改用按钮交集过滤，不再假设列表只受默认缠论筛选控制；5) 如需验证展示效果，应重点检查理由 popover 样式和交集筛选后的板块计数是否同步变化。
- **回滚方案**：回退 `quality_stock_universe`、`gantt_readmodel.py`、Dagster `gantt.py`、`GanttShouban30Phase1.vue` 与 popover 组件改动，重新构建不带新增筛选字段的 `shouban30` 快照。

- **日期**：2026-03-09
- **RFC**：0025-gantt-shouban30-exclude-bj-stocks
- **变更**：`/api/gantt/shouban30/plates|stocks` 的快照语义进一步收口为“仅覆盖 A 股候选”，盘后构建阶段会直接排除 `43/83/87/92` 开头的北交所标的；过滤后若某板块已无剩余候选股，该板块也不再写入 `shouban30_plates`。同轮修复了 `shouban30` 盘后缠论筛选向 `/api/stock_data_chanlun_structure` 传入裸 `code6` 的错误，统一改为 prefixed symbol，避免将可计算股票误判为 `structure_unavailable`。
- **影响面**：`/gantt/shouban30` 页面、`/api/gantt/shouban30/plates|stocks` 调用方、依赖旧候选统计的截图/说明文档，以及任何仍假设北交所标的会出现在 `shouban30` 快照中的脚本都会受到影响。统计值会下降，部分仅由北交所标的构成的板块会直接消失。
- **迁移步骤**：1) 部署包含 RFC 0025 的后端与 Dagster 代码；2) 重建或等待 `job_gantt_postclose` 重建目标交易日 `30/45/60/90` 四档 `shouban30` 快照；3) 调用 `/api/gantt/shouban30/plates|stocks` 时，不再假设会返回北交所 `43/83/87/92` 标的或纯北交所板块；4) 若有历史报表需要与旧口径对齐，应显式注明“旧口径包含北交所候选”。
- **回滚方案**：回退 `freshquant/data/gantt_readmodel.py` 与相关测试/文档，重新构建受影响交易日的 `shouban30` 快照，恢复旧的“北交所标的也进入候选集”语义。

- **日期**：2026-03-09
- **RFC**：0023-gantt-shouban30-postclose-chanlun-snapshot
- **变更**：`/api/gantt/shouban30/plates|stocks` 的运行语义从“页面读取后再由前端复用 `/api/stock_data_chanlun_structure` 做 30m 缠论筛选”切换为“只读取盘后 Dagster 预计算快照”。`shouban30_plates` 新增 `candidate_stocks_count / failed_stocks_count / chanlun_filter_version`，且 `stocks_count` 语义改为“通过默认 30m 缠论筛选后的唯一标的数”；`shouban30_stocks` 新增 `chanlun_passed / chanlun_reason / chanlun_higher_multiple / chanlun_segment_multiple / chanlun_bi_gain_percent / chanlun_filter_version`。盘后构建阶段会直接过滤 `其他 / 公告 / ST股 / ST板块` 四类板块，并在同一交易日的 `30/45/60/90` 四档窗口之间共享缠论结果缓存。命中缺少 `chanlun_filter_version` 的 legacy snapshot 时，后端返回 409“快照未构建完成”，页面不再做前端现算 fallback。
- **影响面**：`/gantt/shouban30` 页面、`/api/gantt/shouban30/plates|stocks` 调用方、`job_gantt_postclose` 构建耗时、`shouban30_*` 读模型 schema，以及任何依赖旧前端现算链路或旧 `stocks_count` 语义的脚本/说明文档都会受到影响。
- **迁移步骤**：1) 部署包含 RFC 0023 的后端、Dagster 与前端代码；2) 运行或等待 `job_gantt_postclose` 重建最新交易日的 `30/45/60/90` 四档 `shouban30` 快照；3) 调用 `/api/gantt/shouban30/plates|stocks` 时按新字段读取 `stocks_count / candidate_stocks_count / failed_stocks_count / chanlun_* / chanlun_filter_version`；4) 前端或调用方若收到 409 `shouban30 chanlun snapshot not ready`，应提示“首板缠论快照未构建完成”并等待盘后快照完成，而不是再去逐股调用 `/api/stock_data_chanlun_structure`。
- **回滚方案**：回退 `freshquant/data/gantt_readmodel.py`、`freshquant/rear/gantt/routes.py`、`morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py`、`morningglory/fqwebui/src/views/GanttShouban30Phase1.vue` 及相关测试/构建产物，恢复 RFC 0017 的首期页面和旧 `shouban30` 字段语义。

- **日期**：2026-03-09
- **RFC**：0024-xtdata-subscription-pool-and-qfq-refresh
- **变更**：`market_producer` 的订阅池从“`monitor_codes ∪ active_tpsl_codes`”收敛为“只订阅 `load_monitor_codes(...)`”；`stock_realtime` 与 `index_realtime` 统一改为只存 `raw/bfq`，股票与 ETF 的 qfq 读取语义统一为“历史 raw + realtime raw 先拼接，再应用 base `stock_adj/etf_adj` 与当日 `intraday override`”。同时新增宿主机 `freshquant.market_data.xtdata.adj_refresh_worker`，用于在盘前写入 `quantaxis.stock_adj_intraday / etf_adj_intraday`。
- **影响面**：宿主机 `xtdata producer / consumer`、`freshquant.data.stock`、`freshquant.quote.etf`、任何直接读取 `stock_realtime/index_realtime` 且假设股票 realtime 已经是 qfq 的脚本、以及宿主机 supervisor 运维配置都会受到影响。
- **迁移步骤**：1) 部署包含 RFC 0024 的代码；2) 停止宿主机 `market_producer / strategy_consumer`；3) 清理或重建当天 `stock_realtime / index_realtime`，避免旧 qfq realtime 数据与新 raw 数据混存；4) 新增并启动 `python -m freshquant.market_data.xtdata.adj_refresh_worker`，与 `credit_subjects.worker` 一起纳入 `fqnext_reference_data` 组；5) 重启 `market_producer / strategy_consumer / API`，确认实时窗口、Redis 缓存与盘前 override 正常生成。
- **回滚方案**：回退 `freshquant/market_data/xtdata/market_producer.py`、`freshquant/market_data/xtdata/strategy_consumer.py`、`freshquant/data/stock.py`、`freshquant/quote/etf.py`、`freshquant/data/adj_intraday.py`、`freshquant/market_data/xtdata/adj_refresh_*` 与对应 supervisor/docs 变更；清理当天 raw-only realtime 数据后，恢复旧的股票 qfq realtime 写入语义与 TPSL 并集订阅逻辑。

- **日期**：2026-03-09
- **RFC**：0022-kline-slim-multi-period-chanlun-display
- **变更**：`KlineSlim` 的默认显示语义从“`5m` 主图 + 固定 `30m` 缠论叠加”调整为“默认仅显示 `5m`，`1m / 15m / 30m` 通过图例按需打开”；图表层同时恢复旧仓四周期配色、线宽倍率，以及 `高级别段 / 段中枢 / 高级段中枢` 图层。
- **影响面**：依赖旧默认可见 `30m` 叠加的用户在新版页面中需要手动点开 `30m` 图例；`KlineSlim` 前端轮询也从“固定主图 + 固定叠加”变为“仅刷新当前可见周期集合”。
- **迁移步骤**：1) 如需旧视觉效果，进入 `/kline-slim` 后手动打开 `30m` 图例；2) 如需叠加更多周期，按需打开 `1m / 15m / 30m`；3) 若依赖默认展示语义做培训或截图说明，更新为新版图例驱动说明。
- **回滚方案**：回退 `morningglory/fqwebui/src/views/KlineSlim.vue`、`src/views/js/kline-slim.js`、`src/views/js/draw-slim.js`、`src/views/js/kline-slim-chanlun-periods.mjs` 及对应测试，恢复 RFC 0005 的固定 `30m` overlay 实现。

- **日期**：2026-03-08
- **RFC**：0021-xtdata-default-guardian-mode
- **变更**：`monitor.xtdata.mode` 在未设置、空字符串或非法值时的运行时缺省语义，从 `clx_15_30` 调整为 `guardian_1m`；`preset/params.py` 初始化默认写入也同步改为 `guardian_1m`。显式配置 `clx_15_30` 或 `guardian_1m` 的实例行为不变。
- **影响面**：宿主机 `xtdata producer / consumer`、Guardian event 监听入口，以及任何依赖“未配置 mode 时默认走 stock_pools / clx_15_30”这一旧语义的运行环境都会受到影响。缺省配置环境重启后会优先按 `xt_positions + must_pool` 预热和订阅。
- **迁移步骤**：1) 若希望保持旧行为，显式设置 `monitor.xtdata.mode=clx_15_30`；2) 若接受新默认值，无需写配置，只需重启宿主机 `xtdata producer / consumer`；3) 验证日志中的 `mode=guardian_1m`、`prewarm start: codes>0` 与 Redis `CACHE:KLINE:*` 是否恢复。
- **回滚方案**：回退 `freshquant/market_data/xtdata/pools.py`、`market_producer.py`、`strategy_consumer.py`、`freshquant/preset/params.py` 与 `freshquant/signal/astock/job/monitor_stock_zh_a_min.py` 中的默认值收口改动，恢复缺省 `clx_15_30` 语义。

- **日期**：2026-03-08
- **RFC**：0019-guardian-buy-side-grid-sizing
- **变更**：Guardian 买单语义从“`get_trade_amount + position_pct/near_pattern` 旧缩量规则 + `must_pool` 近似持仓处理 + `auto_open` 路径”调整为“持仓加仓使用 `BUY-1/2/3 -> 2/3/4` buy-side grid 状态机，新开仓仅允许 `must_pool` 标的且使用 `initial_lot_amount ?? lot_amount ?? 150000`”；同时去掉“当天卖过就不再买”与 Guardian 本地强制卖分支，新增 `guardian_buy_grid_configs / guardian_buy_grid_states` 运行时数据，以及 stock API / CLI 入口 `guardian_buy_grid_*` / `stock.guardian-grid`。手工修改 `BUY-1/2/3` 会默认重置 `buy_active`，手工改配置/状态会写入 `audit_log`。
- **影响面**：Guardian 自动交易行为、must_pool 新开仓语义、订单跟踪上下文、XT 卖出成交后的 buy-side 状态重置、以及依赖旧 `position_pct/auto_open/near_pattern` 买单数量规则的脚本或排障手册都需要更新；运维新增 Guardian buy-side grid 配置与状态维护入口。
- **迁移步骤**：1) 为需要分层加仓的标的配置 `BUY-1/2/3`；2) 为 must_pool 标的补齐 `initial_lot_amount`（缺省时将按 `lot_amount` 或 15 万回退）；3) 若需要人工修正状态，改用 `/api/guardian_buy_grid_config`、`/api/guardian_buy_grid_state`、`/api/guardian_buy_grid_state/reset` 或 `fqctl stock.guardian-grid *`；4) 不再依赖旧 `position_pct`、`near_pattern`、`auto_open` 和 `xt_trades` 同日限制解释 Guardian 买单。
- **回滚方案**：回退 `freshquant/strategy/guardian.py`、`freshquant/strategy/guardian_buy_grid.py`、`freshquant/order_management/submit/guardian.py`、`freshquant/order_management/submit/service.py`、`freshquant/order_management/tracking/service.py`、`freshquant/order_management/ingest/xt_reports.py`、`freshquant/rear/stock/routes.py`、`freshquant/command/stock.py`、`freshquant/cli.py` 及对应测试，恢复旧 Guardian 买单数量路径和无独立 buy-side grid 状态机的实现。

- **日期**：2026-03-07
- **RFC**：0017-gantt-shouban30-phase1-page
- **变更**：`shouban30_plates / shouban30_stocks` 读模型 schema 扩展了 `stock_window_days` 维度；`/api/gantt/shouban30/plates` 与 `/api/gantt/shouban30/stocks` 新增 `stock_window_days=30|45|60|90` 查询语义并返回 `data.meta`。板块列表字段从旧命名 `stocks_count_90` 收敛为 `stocks_count`，标的列表字段从 `appear_days_90 / stock_reason` 收敛为 `hit_count_window / latest_reason`，并新增 `hit_count_30`、`stock_window_from`、`stock_window_to`。前端新增 `/gantt/shouban30` 页面与头部导航“首板选股”，页面详情改为直接复用 `/api/gantt/stocks/reasons` 的历史全量热门理由，不再触发旧页导出/重算行为。
- **影响面**：任何依赖旧 `shouban30` 返回结构、旧字段名或假设页面进入即自动导出/重算的调用方都需要调整；盘后任务会额外为 30/45/60/90 四档窗口构建 `shouban30` 快照。
- **迁移步骤**：1) 调用 `/api/gantt/shouban30/plates|stocks` 时显式传入 `stock_window_days`；2) 适配 `data.meta` 与新字段名 `stocks_count / hit_count_window / latest_reason`；3) 标的详情统一改用 `/api/gantt/stocks/reasons?code6=<6位代码>&provider=all&limit=0`；4) 页面入口改为 `/gantt/shouban30?p=xgb&stock_window_days=30`。
- **回滚方案**：回退 `freshquant/data/gantt_readmodel.py`、`freshquant/rear/gantt/routes.py`、`morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py`、`morningglory/fqwebui/src/api/ganttShouban30.js`、`morningglory/fqwebui/src/views/GanttShouban30Phase1.vue`、`morningglory/fqwebui/src/router/index.js` 与 `morningglory/fqwebui/src/views/MyHeader.vue`，恢复现有最小 `shouban30` 列表能力。

- **日期**：2026-03-07
- **RFC**：0016-tradingagents-env-sot-sync
- **变更**：`ta_backend` 的 DeepSeek/Tushare 配置来源从“宿主根 `.env`、镜像内 `.env.docker`、Mongo 配置并存”收敛为“仓库根 `.env` 单一真相源 + 启动时同步到 Mongo 镜像”；同时 `config_bridge` 改为环境变量优先，不再让数据库旧值覆盖根 `.env`，默认模型桥接优先读取激活 `system_configs` 的 DeepSeek 配置。
- **影响面**：`third_party/tradingagents-cn` 的 Docker 启动链、Mongo `llm_providers/system_configs`、任务中心 `engine_initialization`、Tushare 数据源初始化，以及配置页观察到的密钥来源都会受影响；手工改 Mongo 或依赖 `.env.docker` 占位值的方式在重启后不再保留。
- **迁移步骤**：1) 仅在仓库根 `.env` 维护 `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`TUSHARE_TOKEN`、`JWT_SECRET`；2) 重建 `ta_backend`；3) 验证 `llm_providers.deepseek`、激活 `system_configs.llm_configs`、激活 `system_configs.data_source_configs[type=tushare]` 与根 `.env` 一致。
- **回滚方案**：回退 `third_party/tradingagents-cn/Dockerfile.backend`、`app/main.py`、`app/services/env_config_sync_service.py`、`app/core/config_bridge.py` 及相关测试，恢复 `.env.docker` 注入和旧的多来源优先级。

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
- **RFC**：0015-kline-slim-sidebar-hot-reasons
- **变更**：`GET /api/get_stock_pre_pools_list` 在 `category` 缺省或为空字符串时，从“只匹配 `category=\"\"`”调整为“返回全分类合并结果”；同时新增 `GET /api/gantt/stocks/reasons`，供 `KlineSlim` hover 展示历史热门记录。
- **影响面**：依赖空 `category` 返回空集或仅空分类数据的调用方会改变结果；`KlineSlim` 页面会新增左侧 4 组股票池和 hover 热门原因弹层。
- **迁移步骤**：如需继续按分类过滤，请显式传入 `category`；如需读取 hover 历史热门记录，改用 `/api/gantt/stocks/reasons?code6=<6位代码>&provider=all`。
- **回滚方案**：恢复 `get_stock_pre_pools_list()` 对空 `category` 的旧查询语义，并回退 `/api/gantt/stocks/reasons`、`stock_hot_reason_daily` 与 `KlineSlim` hover 调用链。

- **日期**：2026-03-07
- **RFC**：0014-stock-etf-tpsl-module
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
- **RFC**：0012-gantt-postclose-incremental-backfill
- **变更**：`job_gantt_postclose` 的默认运行语义从“只处理单个上一交易日”调整为“从 `gantt_plate_daily` 最新已完成交易日的下一天开始，连续回补到按交易日历与 `15:05` 截止时间解析出的最新已完成交易日”；Dagster job 内部入口改为统一的增量回填 op，不再直接串接单日 op 链。
- **影响面**：Dagster 单次 run 可能连续处理多天数据，耗时和日志量都会增加；盘后 `15:05` 之后触发的 run 会将当天视为可处理目标日；运维不能再按“每天固定只跑 1 天”估算执行时间。
- **迁移步骤**：部署包含 RFC 0012 的代码并重建 Dagster 容器；保持现有 `gantt_postclose_schedule` 不变；若存在尾部缺口，下一次 schedule 或手工运行会自动从缺口起点补到最新已完成交易日。
- **回滚方案**：回退 `morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py` 与 `morningglory/fqdagster/src/fqdagster/defs/jobs/gantt.py`，恢复旧的单日 job 实现后重建 Dagster 容器。

- **日期**：2026-03-07
- **RFC**：0013-position-management
- **变更**：新增独立分库 `freshquant_position_management` 与模块 `freshquant/position_management/`，策略订单在 `OrderSubmitService` 受理前会先读取仓位状态做门禁；人工/API/CLI 手工单继续旁路。对于 `FORCE_PROFIT_REDUCE` 状态下的 Guardian 盈利卖点，本轮只新增占位标志透传到队列，不实现最终强制卖出算法。
- **影响面**：所有 `source=strategy` 的股票/ETF 订单都会新增一层仓位准入判断；当仓位状态缺失或过旧时，策略买入会按默认保守状态 `HOLDING_ONLY` 处理。运维需要备份独立分库 `freshquant_position_management`，并确保独立 worker 周期刷新 `pm_current_state`。
- **迁移步骤**：1) 配置 `position_management.mongo_database`、`xtquant.account_type=CREDIT`、`xtquant.account`、`xtquant.path`；2) 启动 `python -m freshquant.position_management.worker` 持续刷新信用资产；3) 确认 `pm_current_state` 正常更新后，再让 Guardian 等策略通过 `OrderSubmitService` 发单；4) 若后续实现 Guardian 强制减仓算法，应继续沿用当前 `position_management_force_profit_reduce/profit_reduce_mode` 占位字段。
- **回滚方案**：回退 `freshquant/order_management/submit/service.py` 与 `freshquant/position_management/*` 的接入改动，停用仓位管理 worker，并保留 `freshquant_position_management` 历史快照用于排障。

- **日期**：2026-03-08
- **RFC**：0018-kline-slim-chanlun-structure-panel
- **变更**：无破坏性变更。本次新增 `/api/stock_data_chanlun_structure` 作为独立专用接口，并在 `KlineSlim` 增加手动打开的缠论结构半透明面板；现有 `/api/stock_data`、consumer Redis payload 与旧页面契约保持不变。
- **影响面**：仅新增能力，不改变既有调用方行为。需要该能力的前端应显式调用新接口或使用新版 `KlineSlim` 页面。
- **迁移步骤**：旧调用方无需迁移；如需展示高级段/段/笔及中枢明细，切换到 `/api/stock_data_chanlun_structure` 并使用 RFC 0018 对应的前端面板。
- **回滚方案**：删除新接口、`freshquant/chanlun_structure_service.py` 与 `KlineSlim` 面板代码即可，既有 `/api/stock_data` 与其他页面无需调整。

- **日期**：2026-03-08
- **RFC**：0020-credit-account-order-support
- **变更**：`CREDIT` 账户的下单语义从“broker/puppet 内部临时判断”收敛到订单域：提交阶段基于 `om_credit_subjects` 决定 `CREDIT_FIN_BUY / CREDIT_BUY`，执行前基于实时 `query_credit_detail()` 决定 `CREDIT_SELL_SECU_REPAY / CREDIT_SELL`，并对信用账户恢复自动报价模式。宿主机新增 `freshquant.order_management.credit_subjects.worker` 负责同步融资标的列表；XT ingest 与兼容投影改为支持 `23/27 -> buy`、`24/31 -> sell`，且优先信任订单域记录的 `broker_order_type`。
- **影响面**：宿主机 `broker`、`puppet`、信用账户下单路径、XT 回报 ingest、兼容 `stock_fills/stock_orders` 投影，以及宿主机 supervisor 托管进程都会受影响。未启动 `credit_subjects.worker` 的环境，信用买单可能因缺少融资标的列表而被拒绝。
- **迁移步骤**：1) 部署包含 RFC 0020 的代码；2) 在 Windows 宿主机 supervisor 中新增并启动 `python -m freshquant.order_management.credit_subjects.worker`；3) 确认 `freshquant_order_management.om_credit_subjects` 已同步到融资标的列表；4) 保持 `xtquant.account_type=CREDIT`、`xtquant.account`、`xtquant.path` 配置正确；5) 如使用 Docker 并行模式，确保宿主机 worker/broker 连接 `127.0.0.1:27027` 与 `127.0.0.1:6380`。
- **回滚方案**：停止 `credit_subjects.worker`，回退 `freshquant/order_management/credit_subjects/*`、`freshquant/order_management/submit/*`、`freshquant/order_management/ingest/xt_reports.py`、`morningglory/fqxtrade/fqxtrade/xtquant/broker.py`、`morningglory/fqxtrade/fqxtrade/xtquant/puppet.py` 及相关测试，恢复当前普通股票语义与旧兼容投影行为。
