# 行情数据参考

## 当前行情来源

FreshQuant 当前同时使用三类行情来源：

- XTData / XTQuant
  - 实时 tick 和分钟 bar 的唯一正式入口
- QuantAxis / Mongo 历史库
  - Kline、结构计算、历史回看使用的主要历史数据来源
- Redis realtime cache
  - 前端实时查询与 consumer 最新结果缓存

## 正式入口

- 实时 producer
  - `python -m freshquant.market_data.xtdata.market_producer`
- 实时 consumer
  - `python -m freshquant.market_data.xtdata.strategy_consumer --prewarm`
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
