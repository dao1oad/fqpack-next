# 止盈止损

## 职责

作为独立模块监听实时 quote，并触发止盈 / 止损卖单。

## 入口

- `freshquant.tpsl.tick_listener`
- `freshquant.rear.tpsl.routes`

## 依赖

- Redis 实时 `TICK_QUOTE`
- order management
- 持仓与 lot 信息

## 数据流

实时 quote -> 规则判断 -> 生成卖单意图 -> order management

## 存储

依赖持仓与规则状态，不维护订单主账本。

## 配置

关注止盈止损阈值、重置/武装策略、Redis 配置。

## 部署/运行

改动后重启 `tpsl.tick_listener`。

## 排障点

- quote 未到达
- 规则未武装
- 卖单未生成
