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
- 通过 runtime 页面看 `xt_producer` / `xt_consumer` 心跳与 backlog

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
- `jygs` 最近历史存在缺口，最近 `90` 个交易日 hole scan 还没补齐。
- 上游 `jygs` 某个交易日确实没有热点；此时原始集合会保留 `is_empty_result=true` marker，但 gantt `series` 不会有点位。
- 上游返回了别的 `trade_date`；此时会落 `empty_reason=upstream_trade_date_mismatch` marker，但该日期仍应继续进入 hole scan 重试。

处理：
- 重跑 Dagster 作业
- 确认读模型索引与快照日期
- 若 `/api/gantt/plates?provider=jygs&days=15/30/45/60/90` 的 `dates` 轴完整但 `series` 很少，先看 `jygs_action_fields` / `jygs_yidong`
- 若 marker 是 `empty_reason=upstream_trade_date_mismatch`，不要当成已补完；继续补跑 Dagster，等待上游返回目标交易日
- 若目标交易日既没有真实 `jygs` 数据，也没有 `is_empty_result=true` marker，说明 recent hole scan 还没覆盖到；继续补跑 Dagster

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
- `/api/runtime/traces` 与 `/api/runtime/health/summary` 已有数据，但 `fq_webui` 仍在跑旧静态资源，或页面代码仍按 `response.data.*` 读取而不是读取顶层 `traces/components/trace/files/records`。

处理：
- 直接 tail 原始文件，而不是只看页面
- 先看 `/api/runtime/events` 或 raw browser，确认最近事件是否带关联键
- 清空筛选后刷新页面
- 如果 API 有数据但页面统计卡、recent feed、component board 全空，优先重建并重新部署 `fq_webui`，然后强刷浏览器缓存

## Symphony 任务卡住

现象：
- Issue 被领取但不前进，或 cleanup 不收口。

先检查：
- `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:40123/api/v1/state`
- `Get-Service fq-symphony-orchestrator`
- `runtime/symphony-service/artifacts/`

常见根因：
- Draft PR 还没完成 `Design Review`
- 低风险任务被错误送进 `Design Review` / `brainstorming` 闭环
- 低风险任务在 `Todo` 成功跑完一轮后，没有被自动切到 `In Progress`
- 高风险任务被直接贴上 `design-review`，但 Draft PR 引导创建失败
- 新建 issue 时手工预贴了 `design-review`，导致任务跳过 `Todo` 风险判定并直接进入高风险路径
- 正式服务加载了一份过度简化的 `WORKFLOW.freshquant.md`，prompt 中没有 issue 标识/标题/描述，导致 agent 只会做泛化上下文扫描
- `Design Review` 任务在 Codex 会话里再次触发 `brainstorming`，硬门要求新的人工批准，结果因为会话内没有人工输入面而反复空转
- workspace 只保留了本地路径 `origin`，没有 GitHub remote，导致 `gh pr ...` / `gh issue ...` 在 workspace 内直接失败
- issue 被打到 `blocked`，但没有写明解除条件和应该恢复到哪个状态
- `blocked` 只是状态误标：其实 PR 已 merged / 已有 open PR / 已有 APPROVED，只是没有恢复到 `Merging` / `Rework` / `In Progress`
- workspace 目录还在，但 `.git` 丢失，导致 `before_run` 反复报 `not a git repository`
- GitHub token 失效
- 正式服务没加载最新 workflow

处理：
- 看 Draft PR 评论与 `APPROVED`
- 新建 GitHub issue 时默认只打 `symphony` 与 `todo`，不要在创建时预贴 `design-review`
- 如果任务是普通 bugfix 或小范围现有模块修复，但没有 Draft PR，优先按低风险路径排查，不要继续等待人工审批
- 如果任务命中高风险条件且已经在 `Design Review`，但没有 linked Draft PR，先看 orchestrator 日志是否已触发一次引导执行；若仍没有 Draft PR，优先排查 GitHub token、`gh`/push 权限、branch/PR 创建失败，而不是继续等待审批
- 如果日志里反复只有通用 repo 扫描而没有 issue 标识、标题、描述，先检查 `WORKFLOW.freshquant.md` 是否仍包含 issue placeholders；`sync_freshquant_symphony_service.ps1` / `start_freshquant_symphony.ps1` 现在会对这份 prompt 做合约校验
- 如果日志里明确读入了 issue body，但随后又加载 `brainstorming` 并停在“等待批准”，说明 workflow 仍把 `Design Review` 错当成会话内交互设计阶段；应改成“issue body -> Draft PR packet -> GitHub approval”的单向流程
- 如果 `gh` 在 workspace 内报 “none of the git remotes configured for this repository point to a known GitHub host”，先看当前 workspace 是否只有本地 `origin`；正式 workflow 现在会在 `after_create` / `before_run` 自动补齐 `github` remote
- 如果 issue 停在 `blocked`，先看最新 GitHub 评论是否写清了 blocker、clear condition、evidence 和 target recovery state；没有的话先补齐，再决定是否解除
- 如果 issue 已经有 merged PR、open non-draft PR 或 approved draft PR，但还停在 `blocked`，优先按误标处理；正式 orchestrator 现在会按这些 GitHub 真值自动恢复到 `Merging` / `Rework` / `In Progress`
- 如果日志里反复出现 `workspace_hook_failed ... not a git repository`，先看 workspace 目录是否缺 `.git`；正式 orchestrator 现在会先自愈重建一次，再决定是否继续报错
- 如果 PR 标题、PR 正文、Issue / PR 评论仍然出现英文说明，先检查 `WORKFLOW.freshquant.md` 与 `runtime/symphony/templates/*.md` 是否已经同步到正式服务
- 检查正式服务是否已加载最新 `runtime/symphony/WORKFLOW.freshquant.md`
- 看 issue 当前标签与状态是否仍停在 `todo`，以及 orchestrator 日志里是否出现 `Todo -> In Progress` 自动推进记录
- 重装正式服务或重启 `fq-symphony-orchestrator`
