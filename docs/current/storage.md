# 当前存储

## Mongo

- 主业务事实存储在 Mongo
- 订单管理、仓位管理、Gantt / Shouban30 读模型各自有边界
- TradingAgents-CN 使用独立数据库口径

## Redis

- 用于 XTData 消息流、缓存与实时 quote 分发
- TPSL 依赖 `TICK_QUOTE` 类实时数据

## 当前存储边界

- 订单事实由 order management 主账本负责
- 仓位门禁由 position management 负责
- Gantt / Shouban30 页面依赖读模型，不直接以原始写模型展示

## 变更规则

任何 schema、集合边界、读写语义变化，都必须先经过 `Design Review`。
