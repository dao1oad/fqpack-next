# ETF 数据参考

## 当前 ETF 口径

ETF 在 FreshQuant 中与 A 股共用大部分接口，但有几处语义不同：

- 识别逻辑通常依赖代码前缀，例如 `15`、`16`、`51`、`52`、`53`、`56`、`58`、`159`
- 某些 ATR/网格参数计算会按指数/ETF 路径处理，而不是普通个股路径
- must_pool 允许 `etf_cn`，因此 ETF 也可能进入 Guardian 订阅和交易范围

## 当前入口

- CLI
  - `python -m freshquant.cli etf.day save`
  - `python -m freshquant.cli etf.min save`
  - `python -m freshquant.cli etf.xdxr save` / `etf.adj save` 仅保留为 legacy 人工诊断入口
- HTTP
  - 与 A 股共用 `/api/stock_data` 等行情接口
- 监控池
  - `must_pool` 中 `instrument_type=etf_cn` 的记录可进入监控范围

当前标准 ETF 同步口径由工作日 Dagster `etf_data_job` 执行：

- 同步 `etf_list`
- 同步 `index_day/index_min` 口径的 ETF BFQ 历史数据并通过完整性门禁
- 发布 `etf_postclose_ready` marker
- Windows QFQ worker 读取 marker，以 XTData `preClose` 在 inactive slot 增量构建，full audit 通过后 CAS 切换 `quantaxis.qfq_ready`

## 与普通 A 股的差异

- 价格和补权语义可能更接近指数数据
- 网格交易间距计算会走 ETF/指数的 ATR 路径
- 页面展示仍走 Kline/Gantt 通用视图，不另开一套页面

ETF 当前前复权链路：

- `ETF BFQ ready -> XTData preClose -> etf_adj_qfq_a/b inactive slot -> full audit -> qfq_ready active_slot -> freshquant.data.qfq_reader`
- 页面、策略与共享 QuantAxis 适配层每次读取 active marker，严格校验 snapshot、coverage、正因子、重复键、source exclusion 与 snapshot-bound intraday override
- 合同不满足时返回 `QFQ_DATA_NOT_READY`；Stock/ETF Kline HTTP 路由映射为 503，不回退 `adj=1.0` 或 legacy 集合。源 bar 中的 QASU sentinel 占位行（`vol/volume` 与 `amount` 均为 `5.877471754e-39`）与快照构建同一语义：K 线读取路径在缺失因子日期全部可证明为占位行时剔除这些行后继续返回（如 512600 历史占位日期），不整体 503
- `quantaxis.etf_xdxr` / `quantaxis.etf_adj` 不在正常 schedule，也不是在线 reader 真值；相关 CLI/asset 仅用于 legacy 人工诊断

## 当前排查

### ETF 在页面能查到，但策略不关注

- 检查 `must_pool.instrument_type`
- 检查监控池是否已刷新

### ETF 网格结果异常

- 检查是否误按普通股票 ATR 路径计算
- 检查对应 instrument info 是否正确识别成 `etf_cn`

### ETF 前复权在扩缩股日前后不连续

- 执行 `python -m freshquant.market_data.xtdata.qfq_worker status --scope etf --strict`，核对 active snapshot 的 `factor_asof`
- 对目标代码执行 `python -m freshquant.market_data.xtdata.qfq_worker audit --scope etf --mode full --code 512000`
- 核对 `quantaxis.qfq_ready` 指向的 active collection、该 code 的 factor coverage 与响应 `adjustment_version`
- 若 active slot 审计失败，在 QFQ writer 独占 lease 下人工执行 `build --scope etf --target-date YYYY-MM-DD`；不手工修改 marker，不回填 legacy `etf_adj`
