# ETF 数据参考

## 当前 ETF 口径

ETF 在 FreshQuant 中与 A 股共用大部分接口，但有几处语义不同：

- 识别逻辑通常依赖代码前缀，例如 `15`、`16`、`51`、`52`、`53`、`56`、`58`、`159`
- 某些 ATR/网格参数计算会按指数/ETF 路径处理，而不是普通个股路径
- must_pool 允许 `etf_cn`，因此 ETF 也可能进入 Guardian 订阅和交易范围

## 当前入口

- CLI
  - `python -m freshquant.cli etf ...`
- HTTP
  - 与 A 股共用 `/api/stock_data` 等行情接口
- 监控池
  - `must_pool` 中 `instrument_type=etf_cn` 的记录可进入监控范围

## 与普通 A 股的差异

- 价格和补权语义可能更接近指数数据
- 网格交易间距计算会走 ETF/指数的 ATR 路径
- 页面展示仍走 Kline/Gantt 通用视图，不另开一套页面

## 当前排查

### ETF 在页面能查到，但策略不关注

- 检查 `must_pool.instrument_type`
- 检查监控池是否已刷新

### ETF 网格结果异常

- 检查是否误按普通股票 ATR 路径计算
- 检查对应 instrument info 是否正确识别成 `etf_cn`
