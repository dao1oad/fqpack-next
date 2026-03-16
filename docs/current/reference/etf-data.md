# ETF 数据参考

## 当前 ETF 口径

ETF 在 FreshQuant 中与 A 股共用大部分接口，但有几处语义不同：

- 识别逻辑通常依赖代码前缀，例如 `15`、`16`、`51`、`52`、`53`、`56`、`58`、`159`
- 某些 ATR/网格参数计算会按指数/ETF 路径处理，而不是普通个股路径
- must_pool 允许 `etf_cn`，因此 ETF 也可能进入 Guardian 订阅和交易范围

## 当前入口

- CLI
  - `python -m freshquant.cli etf ...`
  - `python -m freshquant.cli etf.xdxr save`
  - `python -m freshquant.cli etf.adj save`
- HTTP
  - 与 A 股共用 `/api/stock_data` 等行情接口
- 监控池
  - `must_pool` 中 `instrument_type=etf_cn` 的记录可进入监控范围

当前标准 ETF 同步口径：

- `python -m freshquant.cli etf save`
  - 同步 `etf_list`
  - 同步 `index_day/index_min` 口径的 ETF 历史数据
  - 同步 `quantaxis.etf_xdxr`
  - 重算 `quantaxis.etf_adj`

## 与普通 A 股的差异

- 价格和补权语义可能更接近指数数据
- 网格交易间距计算会走 ETF/指数的 ATR 路径
- 页面展示仍走 Kline/Gantt 通用视图，不另开一套页面

ETF 当前前复权链路：

- `TDX get_xdxr_info -> quantaxis.etf_xdxr -> quantaxis.etf_adj -> /api/stock_data`
- `category=11` 的扩缩股事件会写入 `suogu`
- 页面日线/分钟线会读取 `etf_adj`；如果 `etf_xdxr` 缺失，前复权会整段退化成 `adj=1.0`
- `sync_etf_xdxr_all()` 当前默认在上游返回空结果时保留旧 `etf_xdxr`，避免单次空响应把历史扩缩股事件清空

## 当前排查

### ETF 在页面能查到，但策略不关注

- 检查 `must_pool.instrument_type`
- 检查监控池是否已刷新

### ETF 网格结果异常

- 检查是否误按普通股票 ATR 路径计算
- 检查对应 instrument info 是否正确识别成 `etf_cn`

### ETF 前复权在扩缩股日前后不连续

- 先查 `quantaxis.etf_xdxr` 是否存在目标 ETF 的 `category=11` / `suogu`
- 再查 `quantaxis.etf_adj` 是否在事件日前生成了 `adj<1`
- 最后查 `/api/stock_data?period=1d&symbol=<code>&endDate=<date>` 是否已经返回复权后的 close
- 如果历史事件缺失，先执行：
  - `python -m freshquant.cli etf.xdxr save --code 512000`
  - `python -m freshquant.cli etf.adj save --code 512000`
