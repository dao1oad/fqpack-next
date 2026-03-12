# 当前总览

## 项目目标

FreshQuant 当前阶段以“稳定现有系统、修复潜在 bug、统一当前事实文档”为主，不再以迁移过程治理为主。

## 已落地核心能力

- Flask API：`future / stock / general / gantt / order / runtime / tpsl`
- CLI：`stock / etf / index / future / xt-* / om-order`
- XTData producer / consumer
- Guardian 策略
- 订单管理 / 仓位管理 / TPSL
- Gantt / Shouban30 页面与读模型
- KlineSlim 多周期图层
- Runtime Observability
- TradingAgents-CN 并行接入

## 主要目录

- `freshquant/`：核心后端、worker、CLI、API
- `morningglory/fqwebui/`：前端页面
- `morningglory/fqdagster/`：Dagster 运行面
- `runtime/symphony/`：Symphony 运行模板与脚本
- `third_party/tradingagents-cn/`：TradingAgents-CN

## 当前维护重点

- 修复跨模块潜在 bug
- 降低文档漂移
- 收敛部署与 cleanup 语义
- 让 Design Review、CI、deploy、health check、cleanup 连成一条闭环
