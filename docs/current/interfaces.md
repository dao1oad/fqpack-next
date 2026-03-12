# 当前接口

## CLI

- 入口：`freshquant/cli.py`
- 主要命令组：`stock / etf / index / future / xt-* / om-order`

## API

- 入口：`freshquant/rear/api_server.py`
- blueprint：`future / stock / general / gantt / order / runtime / tpsl`

## Web

- 前端主目录：`morningglory/fqwebui/src/views/`
- 关键页面：Gantt、Shouban30、Kline、Runtime Observability

## Worker / 服务入口

- Guardian：`freshquant.signal.astock.job.monitor_stock_zh_a_min`
- Position worker：`freshquant.position_management.worker`
- TPSL：`freshquant.tpsl.tick_listener`
- Broker：`fqxtrade.xtquant.broker`
