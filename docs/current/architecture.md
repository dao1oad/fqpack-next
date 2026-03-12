# 当前架构

## 总体分层

- 行情层：XTData producer / consumer
- 策略层：Guardian
- 交易层：order management / position management / TPSL / xtquant broker
- 展示层：Flask API + Vue Web UI
- 数据处理层：Dagster / Gantt / Shouban30 read model
- 观测层：runtime observability

## 关键调用链

- XTData -> consumer -> Guardian -> order management -> xtquant broker
- XTData -> API / Web UI -> Kline / Gantt / Runtime views
- Dagster -> Gantt / Shouban30 read model -> gantt routes -> Vue views
- Runtime events -> observability assembler -> `/api/runtime/*` -> `/runtime-observability`

## 进程边界

- Flask API：`freshquant.rear.api_server`
- Guardian 入口：`freshquant.signal.astock.job.monitor_stock_zh_a_min`
- 仓位 worker：`freshquant.position_management.worker`
- TPSL worker：`freshquant.tpsl.tick_listener`
- xtquant broker：`fqxtrade.xtquant.broker`

## 模块边界

- 策略层只负责生成买卖意图，不是订单事实层
- 订单管理负责订单受理、主账本、投影、回报 ingest
- 仓位管理负责提交门禁与仓位事实对齐
- TPSL 是独立止盈止损模块，不与 Guardian 合并
- TradingAgents-CN 与主交易链路保持边界隔离
