# 仓位管理

## 职责

负责仓位状态、提交门禁与仓位事实对齐。

## 入口

- worker：`freshquant.position_management.worker`

## 依赖

- Mongo
- order management
- Guardian

## 数据流

订单 / 回报 -> 仓位事实更新 -> submit gate -> 策略下单前校验

## 存储

使用独立仓位存储边界。

## 配置

关注仓位数据库、stale state 规则、提交门禁策略。

## 部署/运行

改动后重启 `position_management.worker`。

## 排障点

- 仓位不刷新
- stale state 误判
- gate 拒绝合法请求
