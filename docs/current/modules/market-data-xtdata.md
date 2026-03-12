# XTData 行情链路

## 职责

负责实时行情生产、消费、缓存与对下游策略/展示层的分发。

## 入口

- producer：`freshquant.market_data.xtdata.market_producer`
- consumer：`freshquant.market_data.xtdata.strategy_consumer`

## 依赖

- XTData 宿主机环境
- Redis

## 数据流

XTData -> producer -> Redis -> consumer -> strategy / API / UI

## 存储

实时数据与中间缓存依赖 Redis，部分衍生结果写入 Mongo。

## 配置

关注 XTData endpoint、Redis host/port/db、订阅池和补权刷新参数。

## 部署/运行

通常运行在宿主机 Supervisor 链路中。

## 排障点

- producer 未启动
- consumer 卡住
- Redis 无数据
- 补权刷新异常
