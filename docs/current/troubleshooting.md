# 当前排障

第二阶段的排障顺序统一为：先确认运行面，再确认数据流，再确认页面或单个模块。不要先改代码。

## 基础命令

```powershell
docker compose -f docker/compose.parallel.yaml ps
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:15000/api/runtime/components
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:40123/api/v1/state
Get-ChildItem logs/runtime -Recurse -Filter *.jsonl | Sort-Object LastWriteTime -Descending | Select-Object -First 20 FullName,LastWriteTime
```

## API 无响应

现象：
- `15000` 端口不可访问，或前端页面全部报接口错误。

先检查：
- `docker compose -f docker/compose.parallel.yaml ps`
- `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:15000/api/runtime/components`

常见根因：
- `fq_apiserver` 没启动或容器异常退出。
- Mongo/Redis 依赖没准备好，API 容器循环重启。
- `.env` 没传给 `FQ_COMPOSE_ENV_FILE`。

处理：
- 重建 API：`docker compose -f docker/compose.parallel.yaml up -d --build fq_apiserver`

## Web 页面空白

现象：
- `18080` 可打开但页面白屏，或单页能进、数据区全空。

先检查：
- `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:18080/`
- 浏览器 DevTools 是否是接口 4xx/5xx

常见根因：
- `fq_webui` 没使用最新构建。
- API 正常，但对应页面依赖的路由返回空数组或 409。
- Kline/Gantt 页面依赖的历史数据或读模型为空。

处理：
- 重建前端：`docker compose -f docker/compose.parallel.yaml up -d --build fq_webui`

## XTData 链路不更新

现象：
- Kline 最新 bar 不动，Guardian 不触发，TPSL 无 tick。

先检查：
- producer 是否在跑：`python -m freshquant.market_data.xtdata.market_producer`
- consumer 是否在跑：`python -m freshquant.market_data.xtdata.strategy_consumer --prewarm`
- `monitor.xtdata.mode` 是否符合场景
- `XTQUANT_PORT` 是否正确

常见根因：
- XTQuant 端口错了。
- 订阅池为空，producer 实际没有订阅任何代码。
- Redis 队列堆积，consumer 进入 catchup 模式。

处理：
- 修正 `monitor.xtdata.mode` 与 `monitor.xtdata.max_symbols`
- 重启 producer / consumer
- 通过 runtime 页面看：
  - `xt_producer` 的心跳年龄、`收 tick`、`5m ticks`、`订阅`
  - `xt_consumer` 的心跳年龄、`最近处理`、`5m bars`、`backlog`

## Guardian 不触发或不下单

现象：
- 页面有信号，但没有订单请求。

先检查：
- 运行命令是否是 `--mode event`
- `monitor.xtdata.mode` 是否是 `guardian_1m`
- `must_pool` / `xt_positions` 是否包含目标股票
- `pm_current_state` 是否允许开仓

常见根因：
- 事件模式没开，进程实际跑的是老轮询逻辑。
- 信号超过 30 分钟被跳过。
- buy/sell 冷却键仍在 Redis 里。
- Position management 因 `HOLDING_ONLY` 或 `FORCE_PROFIT_REDUCE` 拒绝。

处理：
- 查 runtime 里的 `guardian_strategy`、`position_gate`、`order_submit`
- 需要时清理冷却键并重启 Guardian

## 订单已提交但没有成交回流

现象：
- `om_order_requests` 有记录，但前端/仓位没有更新。

先检查：
- `om_orders`、`om_order_events` 是否写入
- broker/gateway 进程是否在消费 `STOCK_ORDER_QUEUE`
- `xt_orders`、`xt_trades` 是否有外部回报

常见根因：
- broker 队列消费异常。
- XT 回报 ingest 没启动或报错。
- reconcile 没把外部回报外部化成内部订单。

处理：
- 重启 broker / ingest / reconcile 对应进程
- 对照 `om_trade_facts` 与 `xt_trades`

## TPSL 不执行

现象：
- 配了 takeprofit/stoploss，但行情到了也没有退出单。

先检查：
- `python -m freshquant.tpsl.tick_listener` 是否在跑
- Redis tick 队列是否有目标 code
- `/api/tpsl/takeprofit/<symbol>` 是否能读到 profile
- `xt_positions` 是否有可卖数量

常见根因：
- 目标 code 不在 active TPSL universe。
- cooldown lock 未释放。
- 价格触发了，但没有可用持仓数量。

处理：
- 看 `om_takeprofit_states`、`om_exit_trigger_events`
- 重启 TPSL worker，必要时执行 rearm

## Gantt / Shouban30 无数据

现象：
- `/gantt` 页面空白，或 `/gantt/shouban30` 返回 409。

先检查：
- `gantt_plate_daily`、`gantt_stock_daily`、`shouban30_plates`、`shouban30_stocks`
- `/api/gantt/plates?provider=xgb`
- `/api/gantt/shouban30/plates?provider=xgb`

常见根因：
- Dagster 任务未跑。
- `as_of_date` 对应快照还没生成。
- `stock_window_days` 不在 `30|45|60|90`。

处理：
- 重跑 Dagster 作业
- 确认读模型索引与快照日期

## Runtime Observability 无 trace

现象：
- `/runtime-observability` 页面无数据。

先检查：
- `logs/runtime` 或 `FQ_RUNTIME_LOG_DIR` 是否有 `.jsonl`
- `/api/runtime/components`
- `/api/runtime/health/summary`

常见根因：
- 业务进程没启用或没走到 runtime logger。
- 路径被环境变量指到别的目录。
- 页面筛选条件过严。
- 原始事件只有 `heartbeat`，或缺少 `trace_id` / `request_id` / `internal_order_id`，因此不会进入 trace 列表。
- 组件卡片是固定核心组件全集；如果显示 `unknown / no data`，说明组件存在但最近没有可聚合的 health 数据。

处理：
- 直接 tail 原始文件，而不是只看页面
- 先看 `/api/runtime/events` 或 raw browser，确认最近事件是否带关联键
- 清空筛选后刷新页面

## Symphony 任务卡住

现象：
- Issue 被领取但不前进，或 cleanup 不收口。

先检查：
- `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:40123/api/v1/state`
- `Get-Service fq-symphony-orchestrator`
- `runtime/symphony-service/artifacts/`

常见根因：
- Draft PR 还没完成 `Design Review`
- GitHub token 失效
- 正式服务没加载最新 workflow

处理：
- 看 Draft PR 评论与 `APPROVED`
- 重装正式服务或重启 `fq-symphony-orchestrator`
