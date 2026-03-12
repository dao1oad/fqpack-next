# Guardian 策略

## 职责

负责消费行情与状态，生成买卖意图，但不直接作为订单事实层。

## 入口

- `freshquant.strategy.guardian`
- `freshquant.signal.astock.job.monitor_stock_zh_a_min`

## 依赖

- XTData consumer
- 持仓 / must_pool / stock_pool
- order management 提交能力

## 数据流

行情 -> Guardian -> submitter / order management

## 存储

依赖持仓、股票池与策略状态存储，不维护订单主账本。

## 配置

关注 guardian mode、buy grid、持仓门禁。

## 部署/运行

常作为宿主机 worker 运行。

## 排障点

- worker 未启动
- 池子数据为空
- submit gate 拒绝
- buy grid 参数错误
