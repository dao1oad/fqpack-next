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
- **变更**：A 股分钟实时链路从 “TDX 轮询 realtime + Guardian 轮询 `get_data_v2`” 切换为 “XTData Producer/Consumer 事件驱动 + fullcalc 统一推送结构”；Guardian 改为订阅 `CHANNEL:BAR_UPDATE`。
- **影响面**：部署不再依赖旧 TDX realtime 采集链路；分钟监控依赖 Redis Pub/Sub、Redis List 与 MiniQMT/XTData；`DBfreshquant.stock_realtime/index_realtime` 的写入来源切换为 XTData Consumer。
- **迁移步骤**：设置 `monitor.xtdata.mode` 与 `monitor.xtdata.max_symbols`，启动 `market_producer`、`strategy_consumer --prewarm` 和 `monitor_stock_zh_a_min --mode event`。
- **回滚方案**：停止 Producer/Consumer/Guardian(event)，恢复旧 TDX realtime 链路与 Guardian 轮询模式。

- **日期**：2026-03-06
- **RFC**：0005-kline-slim-mvp-5m-30m-overlay
- **变更**：无对外破坏性变更。`/api/stock_data` 新增 **opt-in** 的 Redis-first 实时查询路径，仅当请求显式带 `realtimeCache=1`（或 `true/yes`）且属于实时支持周期时才启用；默认请求继续保持 `get_data_v2()` 返回契约。前端新增 `/kline-slim` 页面，并在无 `endDate` 的实时模式下默认附带该参数。
- **影响面**：`KlineSlim` 实时页面会优先从 Redis 缓存取数；旧页面、历史查询与非支持周期行为不变。
- **迁移步骤**：旧调用方无需调整。如需让新页面也关闭该路径，可移除 `realtimeCache=1` 参数或回退到 `get_data_v2()` 全量计算路径。
- **回滚方案**：移除 `/api/stock_data` 的 `realtimeCache` 分支，前端下线 `/kline-slim` 或继续使用纯 fallback 请求。
