# FreshQuant 当前文档索引

本目录只保留 FreshQuant 当前系统的设计、实现、运行与排障事实。

## 文档规则

- `docs/current/**` 是唯一正式文档集合。
- 文档只描述当前代码与当前运行面的事实。
- 任何会改变当前系统事实的改动，必须在同一 PR 更新对应 `docs/current/**`。

## 建议阅读顺序

1. [当前总览](./current/overview.md)
2. [当前架构](./current/architecture.md)
3. [当前运行面](./current/runtime.md)
4. [当前部署](./current/deployment.md)
5. [当前配置](./current/configuration.md)
6. [当前存储](./current/storage.md)
7. [当前接口](./current/interfaces.md)
8. [当前排障](./current/troubleshooting.md)

## 当前阶段最常用入口

- API 入口：`python -m freshquant.rear.api_server --port 5000`
- Guardian 入口：`python -m freshquant.signal.astock.job.monitor_stock_zh_a_min --mode event`
- 账户同步 worker：`python -m freshquant.xt_account_sync.worker --interval 15`
- XT 自动还款 worker：`python -m freshquant.xt_auto_repay.worker`
- TPSL worker：`python -m freshquant.tpsl.tick_listener`
- XTData producer：`python -m freshquant.market_data.xtdata.market_producer`
- XTData consumer：`python -m freshquant.market_data.xtdata.strategy_consumer --prewarm`
- Docker 并行环境：`docker compose -f docker/compose.parallel.yaml up -d --build`
- formal deploy：`py -3.12 script/ci/run_formal_deploy.py --repo-root <deploy-mirror> --format summary`
