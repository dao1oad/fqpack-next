# 当前运行面

## 运行方式

- Windows 宿主机：XTData、broker、部分 worker、Supervisor
- Docker 并行环境：API、Web UI、Dagster、Mongo、Redis、TradingAgents-CN
- Symphony：宿主机单实例 orchestrator

## 宿主机侧关键进程

- `freshquant.market_data.xtdata.market_producer`
- `freshquant.market_data.xtdata.strategy_consumer`
- `freshquant.signal.astock.job.monitor_stock_zh_a_min`
- `freshquant.position_management.worker`
- `freshquant.tpsl.tick_listener`
- `fqxtrade.xtquant.broker`

## Docker 并行端口

- Web UI：`18080`
- API：`15000`
- TDXHQ：`15001`
- Dagster：`11003`
- Redis：`6380`
- Mongo：`27027`

## Symphony 运行面

- repo-versioned 模板位于 `runtime/symphony/`
- 正式 tracker 目标为 GitHub Issue + Draft PR
- cleanup 由 merge 后宿主机流程完成
