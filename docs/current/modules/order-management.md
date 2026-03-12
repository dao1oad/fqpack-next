# 订单管理

## 职责

负责订单受理、主账本、回报 ingest、兼容投影、对账与路由。

## 入口

- API：`freshquant.rear.order.routes`
- CLI：`om-order`
- broker 适配：`fqxtrade.xtquant.broker`

## 依赖

- Mongo
- xtquant broker
- Guardian / 手工下单入口

## 数据流

submit / cancel -> order service -> broker -> XT 回报 ingest -> projection / reconcile

## 存储

订单主事实由 order management 主账本维护。

## 配置

关注 broker mode、observe_only、数据库配置、信用账户参数。

## 部署/运行

改动后至少重部署 API 与相关 worker。

## 排障点

- submit 不落库
- broker 不提交
- 回报未 ingest
- reconcile 不收敛
