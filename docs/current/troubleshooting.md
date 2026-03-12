# 当前排障

## API 无响应

- 先检查 API 进程是否在线
- 检查 `freshquant.rear.api_server` 端口与 compose 映射
- 检查 blueprint 注册是否缺失

## XTData 不更新

- 检查 producer / consumer 进程
- 检查 Redis 端口与连接
- 检查宿主机 XTData 环境

## Guardian 不下单

- 检查 Guardian worker 是否运行
- 检查持仓 / must_pool / submit gate
- 检查 order management 与 broker 链路

## TPSL 不触发

- 检查 `tpsl.tick_listener` 进程
- 检查 `TICK_QUOTE` 实时数据
- 检查止盈止损规则是否已武装

## Gantt / Shouban30 无数据

- 检查 Dagster 或读模型更新
- 检查 gantt routes
- 检查页面筛选条件与接口响应

## Symphony 卡住

- 检查 tracker 是否收到 managed issue
- 检查 Draft PR 上的 `APPROVED / REVISE / REJECTED`
- 检查 deploy / cleanup 脚本日志
