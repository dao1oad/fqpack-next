# 破坏性变更清单（Breaking Changes）

> 任何破坏性变更落地时必须追加记录，并引用对应 RFC。

## 记录模板

- **日期**：YYYY-MM-DD
- **RFC**：NNNN-<topic>
- **变更**：做了什么不兼容的变化
- **影响面**：哪些模块/脚本/用户会受影响
- **迁移步骤**：如何升级（包含命令/配置修改）
- **回滚方案**：如何撤回

## 变更记录

- **日期**：2026-03-05
- **RFC**：0002-etf-qfq-adj-sync
- **变更**：ETF K 线查询默认从 `bfq` 切换为 `qfq`（通过新增 `quantaxis.etf_xdxr/etf_adj` 并在查询侧应用复权因子）。
- **影响面**：依赖 `freshquant/quote/etf.py:queryEtfCandleSticks*` 或 `freshquant/chanlun_service.py:get_data_v2()` 的策略/回测/可视化结果可能变化。
- **迁移步骤**：如需 `bfq`，请直接读取底层原始集合 `quantaxis.index_day/index_min`（或回滚本变更）。
- **回滚方案**：移除 ETF 查询侧对 `etf_adj` 的应用逻辑，并停用/移除 `etf_xdxr/etf_adj` 同步资产。

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
