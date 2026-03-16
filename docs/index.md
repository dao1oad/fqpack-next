# FreshQuant 当前文档索引

本目录只保留 FreshQuant 当前系统的设计、实现、运行与排障事实。第二阶段的目标不是继续记录迁移过程，而是把现有系统收敛成一套可维护、可排障、可部署的现状文档。

## 文档规则

- `docs/current/**` 是唯一正式文档集合。
- 文档只描述当前代码与当前运行面的事实，不记录 RFC、实施过程、进度流水或复盘。
- 任何会改变当前系统事实的改动，必须在同一 PR 更新对应 `docs/current/**`。
- 需要历史过程时，直接看 Git 历史、PR 和提交记录，不再在 `docs/` 中保存过程文档。

## 建议阅读顺序

1. [当前总览](./current/overview.md)
2. [当前架构](./current/architecture.md)
3. [当前运行面](./current/runtime.md)
4. [当前部署](./current/deployment.md)
5. [当前配置](./current/configuration.md)
6. [当前存储](./current/storage.md)
7. [当前接口](./current/interfaces.md)
8. [当前排障](./current/troubleshooting.md)

## 横切文档

- [当前总览](./current/overview.md)：项目定位、能力清单、运行拓扑、维护重点。
- [当前架构](./current/architecture.md)：分层、调用链、进程边界、模块职责。
- [当前运行面](./current/runtime.md)：宿主机、Docker 并行环境、Symphony 正式运行面。
- [当前部署](./current/deployment.md)：模块部署矩阵、健康检查、Done 判定。
- [当前配置](./current/configuration.md)：Dynaconf、环境变量、关键参数。
- [当前存储](./current/storage.md)：Mongo/Redis 分层、集合边界、读写关系。
- [当前接口](./current/interfaces.md)：CLI、HTTP API、前端路由、后台 worker 入口。
- [当前排障](./current/troubleshooting.md)：第二阶段排障入口与常用命令。

## 核心模块

- [XTData 行情链路](./current/modules/market-data-xtdata.md)
- [Guardian 策略](./current/modules/strategy-guardian.md)
- [订单管理](./current/modules/order-management.md)
- [仓位管理](./current/modules/position-management.md)
- [止盈止损](./current/modules/tpsl.md)
- [标的管理](./current/modules/subject-management.md)
- [甘特图展示](./current/modules/gantt-visualization.md)
- [首板筛选](./current/modules/shouban30-screening.md)
- [Kline Web UI](./current/modules/kline-webui.md)
- [运行观测](./current/modules/runtime-observability.md)
- [TradingAgents-CN](./current/modules/tradingagents-cn.md)

## 参考文档

- [行情数据](./current/reference/market-data.md)
- [ETF 数据](./current/reference/etf-data.md)
- [前端 Workbench 风格](./current/reference/frontend-workbench-style.md)
- [股票池与持仓](./current/reference/stock-pools-and-positions.md)
- [CLXS 信号函数](./current/reference/signal-clxs.md)

## 当前阶段最常用入口

- API 入口：`python -m freshquant.rear.api_server --port 5000`
- Guardian 入口：`python -m freshquant.signal.astock.job.monitor_stock_zh_a_min --mode event`
- 仓位 worker：`python -m freshquant.position_management.worker --interval 3`
- TPSL worker：`python -m freshquant.tpsl.tick_listener`
- XTData producer：`python -m freshquant.market_data.xtdata.market_producer`
- XTData consumer：`python -m freshquant.market_data.xtdata.strategy_consumer --prewarm`
- Docker 并行环境：`docker compose -f docker/compose.parallel.yaml up -d --build`
- Symphony 正式服务健康检查：`Invoke-WebRequest -UseBasicParsing http://127.0.0.1:40123/api/v1/state`
