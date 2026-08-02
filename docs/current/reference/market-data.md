# 行情数据参考

## 当前行情来源

FreshQuant 当前同时使用三类行情来源：

- XTData / XTQuant
  - 实时 tick 和分钟 bar 的唯一正式入口
  - Stock / ETF QFQ canonical 快照的 `preClose` 权威来源
- QuantAxis / Mongo 历史库
  - Kline、结构计算、历史回看使用的主要历史数据来源
- Redis realtime cache
  - 前端实时查询与 consumer 最新结果缓存

## 正式入口

- 实时 producer
  - `python -m freshquant.market_data.xtdata.market_producer`
- 实时 consumer
  - `python -m freshquant.market_data.xtdata.strategy_consumer --prewarm`
- QFQ canonical worker / 运维 CLI
  - `python -m freshquant.market_data.xtdata.qfq_worker worker`
  - `python -m freshquant.market_data.xtdata.qfq_worker status --strict`
  - `python -m freshquant.market_data.xtdata.qfq_worker audit --scope <stock|etf> --mode <structure|tail|full> [--code CODE]`
  - `python -m freshquant.market_data.xtdata.qfq_worker build --scope <stock|etf> --target-date YYYY-MM-DD`
  - `python -m freshquant.market_data.xtdata.qfq_worker build --scope <stock|etf> --target-date YYYY-MM-DD --full`
  - `python -m freshquant.market_data.xtdata.qfq_worker rollback --scope <stock|etf>`
- HTTP 查询
  - `/api/stock_data`
  - `/api/stock_data_v2`
  - `/api/stock_data_chanlun_structure`

## 当前口径

### 实时口径

- producer 从 XTData 订阅监控池全量行情
- tick 写入 Redis tick 分片队列
- bar 写入 Redis bar 分片队列
- consumer 计算结构后把最新结果写回 Redis realtime cache

### 历史口径

- `get_data_v2` 使用 QuantAxis 历史数据
- endDate 为空时，可优先命中 Redis realtime cache
- 指定 `endDate` 时，以历史查询为准
- TDX 股票日线对未上市/暂无源数据代码返回空结果时按 no-op 处理，不执行空批量写入；连接、抓取或真实写库异常仍由 Dagster 标记为失败
- 股票除权除息复权计算使用显式列赋值与 `DataFrame.ffill()`，避免 Pandas 3.0 链式 `inplace`/`fillna(method=...)` 兼容性问题，计算口径不变
- CLX 日线选股按 Stock / ETF 各自 active marker 冻结 QFQ snapshot pair，并通过共享 strict reader 构造 effective universe；marker `source_exclusions` 与逐标的 `QFQ_DATA_NOT_READY` 会在 attempt 前通用隔离并记录，其他异常直接阻断规划，不回退为 `adj=1` 或 BFQ
- Stock / ETF 在线读取统一使用 `freshquant.data.qfq_reader`，按 `quantaxis.qfq_ready` 指向的 active slot 读取 `stock_adj_qfq_a/b`、`etf_adj_qfq_a/b`
- XTData `preClose` QFQ writer 只在 inactive slot 构建并审计，审计成功且 writer lease owner 仍匹配后原子切换 marker；reader 每次请求重新解析 marker，并对 snapshot、coverage、source exclusion 与 override fail closed
- Redis Kline 与 StrategyConsumer 常驻窗口绑定 effective adjustment version；旧 `stock_adj` / `etf_adj` 不再是 reader 真值，旧 writer 在切换健康检查后停止，旧集合保留至少 7 个交易日
- 完整历史请求后仍无 source bars、有界内部 source gap 两端 adjustment proof 不一致，或 primary source 前缀分页稳定报告 `history_prefix_no_progress` 的 code，不写推断因子或 `1.0`，从当前 snapshot 隔离，并在对应 slot `source_exclusions[]` 分别记录 `source_empty_bars`、`source_adjustment_gap_unproven` 或 `source_prefix_unavailable`；A/B 与 rollback 各自保留该审计边界
- `audit --mode structure` 检查 Mongo 结构合同，并读取 XTData instrument `OpenDate` / `IsTrading` 元数据以区分上市前 BFQ 覆盖与 `nontrading_terminal_history`，但不加载 source bars；`tail/full` 另会加载 XTData source bars 并验证 `preClose` 递推，正式发布门禁使用 `full`
- 真实 Index 日线、分钟线与 realtime merge 固定为 BFQ，实时表使用 `freshquant.index_realtime`，不读取 ETF 或 Stock 复权因子

Dagster 盘后桥接口径当前新增两条 ready asset：

- `stock_postclose_ready_asset`
  - 依赖股票日线、分钟线与 `quality_stock_universe` 快照刷新
  - 成功后写入 `freshquant.dagster_pipeline_markers` 中 `pipeline_key=stock_postclose_ready` 的文档
- `etf_postclose_ready_asset`
  - 依赖 ETF 日线和通过五周期完整性门禁的 `etf_min`
  - 成功后写入 `freshquant.dagster_pipeline_markers` 中 `pipeline_key=etf_postclose_ready` 的文档

其中：

- `stock_data_job` 仍由工作日 `16:00` schedule 驱动
- `etf_data_job` 仍由工作日 `16:00` schedule 驱动
- `stock_postclose_ready` 是 Gantt / Daily Screening 盘后链路的正式股票侧就绪信号
- 对旧 `/daily-screening`，`etf_postclose_ready` 仍不是硬门禁
- 对独立 CLX 日线选股，`stock_postclose_ready` success 立即启动 stock partition，`etf_postclose_ready` success 立即启动 ETF partition；两侧互不等待
- 两个 CLX partition 都成功只门控 finalizer、`clx_daily_selection_ready`、正式完整结果和跨资产统计
- `etf_postclose_ready` 当前仅保留给 ETF 扩展链路，不是每日选股硬门禁
- Windows `fqnext_xtdata_qfq_worker` 消费上述两个 success marker，更新对应 scope 的 QFQ canonical 快照；缺失 `qfq_ready` 时只报告 `bootstrap_required`，首次全历史构建由人工 `build` 执行

## 当前常见字段语义

- `symbol`
  - 前端常用 `sh600000` / `sz000001`
- `code6`
  - 六位证券代码
- `period`
  - 前端周期，如 `1m`、`5m`、`30m`、`1d`
- `endDate`
  - `YYYY-MM-DD`

## 常见排查

### 历史数据有，实时不动

- 检查 producer / consumer 是否在线
- 检查 Redis cache 是否更新

### `/api/stock_data` 很慢

- 检查是否命中 realtime cache
- 检查 consumer 是否刚进入 catchup 模式

### 某些股票始终没有实时数据

- 检查它是否在当前监控池
- 检查 `monitor.xtdata.max_symbols` 是否裁掉了它
