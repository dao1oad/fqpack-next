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

## Docker API 报 `fq_mongodb:27027`

现象：
- `15000` 或 `18080/api/*` 请求超时
- `fq_webui` 日志出现 `504 upstream timed out`
- `fq_apiserver` 日志出现 `ServerSelectionTimeoutError: fq_mongodb:27027`

先检查：
- `docker exec <fq_apiserver> /freshquant/.venv/bin/python -c "from freshquant.config import settings; print(settings.get('mongodb'))"`
- `docker exec <fq_apiserver> env | findstr MONGODB`
- `docker compose -f docker/compose.parallel.yaml config`

常见根因：
- 容器环境只覆写了 `FRESHQUANT_MONGODB__HOST=fq_mongodb`，没有同时覆写 `FRESHQUANT_MONGODB__PORT=27017`
- `freshquant/freshquant.yaml` 的宿主机默认 `mongodb.port=27027` 被保留下来，最终拼成 `fq_mongodb:27027`

处理：
- 在 `docker/compose.parallel.yaml` 为 `fq_apiserver`、`fq_tdxhq`、`fq_dagster_webserver`、`fq_dagster_daemon`、`fq_qawebserver` 同时显式注入 `FRESHQUANT_MONGODB__HOST=fq_mongodb`、`FRESHQUANT_MONGODB__PORT=27017`、`MONGODB=fq_mongodb`、`MONGODB_PORT=27017`
- 如果并行环境还依赖主工作树 `.env`，也同步补齐 `FRESHQUANT_MONGODB__PORT=27017` 与 `MONGODB_PORT=27017`
- 重建受影响容器后，再检查 `settings.get('mongodb')` 是否解析为 `{'host': 'fq_mongodb', 'port': 27017, ...}`

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
- 在 `/runtime-observability` 左侧组件侧栏选中 `guardian_strategy`，先看中间 recent trace 的信号摘要、节点 hover 和最终结论
- 节点详情优先看 `decision_expr`、`decision_context`、`decision_outcome`，Raw Browser 只作为补充
- 需要时清理冷却键并重启 Guardian

## Guardian 宿主机启动即报 Mongo `27017`

现象：
- `python -m freshquant.signal.astock.job.monitor_stock_zh_a_min` 或 `fqnext_guardian_event` 启动即报 `ServerSelectionTimeoutError`
- 栈追到 `freshquant.chanlun_service -> QUANTAXIS -> QAWebServer/qifiserver.py` 一类导入链

先检查：
- 宿主机环境是否有 `FRESHQUANT_MONGODB__HOST=127.0.0.1`
- 宿主机环境是否有 `FRESHQUANT_MONGODB__PORT=27027`
- 异常里目标地址是否仍是 `127.0.0.1:27017`

常见根因：
- 只修了 FreshQuant Dynaconf，vendored `QUANTAXIS` 仍沿用 `qaenv` 的本地 `27017` 默认值
- `qifiserver` 在 import 阶段初始化 manager，模块一导入就连库
- 宿主机进程的 `PYTHONPATH` 没带 `sunflower/QUANTAXIS`，实际导入落到了 `.venv/Lib/site-packages/QUANTAXIS`

处理：
- 宿主机链路统一改到 `127.0.0.1:27027`
- Docker 容器内部继续保持 `fq_mongodb:27017`
- 宿主机 supervisor 模板里的 `PYTHONPATH` 要同时包含仓库根、`morningglory/fqxtrade` 和 `sunflower/QUANTAXIS`
- 当前 `freshquant` 在源码树运行时会优先插入 vendored `QUANTAXIS`；如果仍然打到 `27017`，优先怀疑正式 checkout 还没更新到包含该 bootstrap 与 lazy-init 修复的最新源码
- 如果仍失败，说明 Mongo 端口问题已排除，继续看下一层真实依赖

## Guardian / Chanlun 导入时报 `fqchan01` DLL load failed

现象：
- `python -m freshquant.signal.astock.job.monitor_stock_zh_a_min`
- 或 `python -c "import freshquant.signal.astock.job.monitor_stock_zh_a_min"`
- 报 `ImportError: DLL load failed while importing fqchan01: %1 不是有效的 Win32 应用程序。`

先检查：
- `python -c "import fqchan01; print(fqchan01.__file__)"`
- `python -c "from pathlib import Path; p=Path(r'D:/fqpack/freshquant-2026.2.23/.venv/Lib/site-packages/fqchan01.cp312-win_amd64.pyd'); data=p.read_bytes(); print(p.stat().st_size, data[:2].hex())"`

常见根因：
- 宿主机 `.venv` 里安装的是损坏的 `fqchan01.cp312-win_amd64.pyd`
- `morningglory/fqchan01/python/build` 留下了陈旧坏产物，后续本地目录打包继续把坏 `.pyd` 带进 `.venv`
- `uv sync --frozen` 复用了坏的本地原生包缓存，导致 `fqchan01` 看起来已安装，但文件本体不是合法 PE
- 这类问题不等同于 Python 3.12 / Win64 ABI 普遍不兼容；同机其他本地原生包可正常导入时，优先怀疑 `fqchan01` 安装产物本身

处理：
- 先运行 `.\install.bat --skip-web`
- 当前安装脚本会先清 `morningglory/fqchan01/python/build`，再对 `fqchan01` 强制执行 `uv` 的 `refresh + reinstall`
- 重装后先执行 `python -c "import fqchan01; print('IMPORT_OK')"`，再执行 `python -c "import freshquant.signal.astock.job.monitor_stock_zh_a_min; print('IMPORT_OK')"`
- 如果 `fqchan01` 仍导入失败，再继续检查 `.venv/Lib/site-packages/fqchan01.cp312-win_amd64.pyd` 是否是合法 `MZ` 文件头，而不要先回退到 Mongo / QUANTAXIS 方向

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
- 交易日日历源瞬时失败；当前实现会在移除代理环境变量后自动重试 3 次，但连续失败时仍拿不到最新完成交易日。
- `jygs` 最近历史存在缺口，最近 `90` 个交易日 hole scan 还没补齐。
- 上游 `jygs` 某个交易日确实没有热点；此时原始集合会保留 `is_empty_result=true` marker，但 gantt `series` 不会有点位。
- 上游返回了别的 `trade_date`；此时会落 `empty_reason=upstream_trade_date_mismatch` marker，但该日期仍应继续进入 hole scan 重试。
- 上游 `jygs action_field` 可能夹带单条缺 `reason` 的历史主题行；当前实现会跳过坏行并继续同步当天其余主题。若整天过滤后没有可用主题，则会落 `empty_reason=invalid_theme_fields` marker，而不是把整条 Dagster 作业打断。

处理：
- 重跑 Dagster 作业
- 确认读模型索引与快照日期
- 在任务运行环境检查 `ALL_PROXY`、`all_proxy`、`HTTP_PROXY`、`HTTPS_PROXY` 是否被错误注入，再确认 AkShare 到 Sina 可访问
- 若 `/api/gantt/plates?provider=jygs&days=15/30/45/60/90` 的 `dates` 轴完整但 `series` 很少，先看 `jygs_action_fields` / `jygs_yidong`
- 若 marker 是 `empty_reason=upstream_trade_date_mismatch`，不要当成已补完；继续补跑 Dagster，等待上游返回目标交易日
- 若日志里出现 `skipping invalid jygs theme rows`，说明是上游单条主题缺 `reason`；先核对该 trade_date 其他主题是否已正常落库，再确认是否需要人工补录该主题说明
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
- 组件卡片是固定核心组件全集；如果显示 `unknown / no data`，说明组件存在但最近没有可聚合的 health 数据。
- `/api/runtime/traces` 与 `/api/runtime/health/summary` 已有数据，但 `fq_webui` 仍在跑旧静态资源，或页面代码仍按 `response.data.*` 读取而不是读取顶层 `traces/components/trace/files/records`。

处理：
- 直接 tail 原始文件，而不是只看页面
- 先看 `/api/runtime/events` 或 raw browser，确认最近事件是否带关联键
- 清空筛选后刷新页面
- 如果 API 有数据但页面统计卡、recent feed、component board 全空，优先重建并重新部署 `fq_webui`，然后强刷浏览器缓存

## Symphony / Global Stewardship 卡住

现象：
- Issue 被领取但不前进，merge 后没有进入 `Global Stewardship`，或原 issue 长时间不收口。

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
- `Merging` 会话里直接使用 `gh pr checks --watch`、`gh run watch` 或带 `Start-Sleep` 的长轮询脚本，导致单个 turn 长时间占住 agent，甚至被 stall detector 杀掉后重试
- `Merging` 没有写 handoff comment，或 merge 后没有把原 issue 转到 `Global Stewardship`
- 全局 Codex 自动化没有运行，或没有读取最新 `runtime/symphony/prompts/global_stewardship.md`
- 全局 Codex 自动化把需要代码修复的问题当成纯收口问题，导致原 issue 一直停在 `Global Stewardship`
- 全局 Codex 自动化没有做 follow-up issue 去重，重复创建了多个同源修复任务
- `Design Review` 任务在 Codex 会话里再次触发 `brainstorming`，硬门要求新的人工批准，结果因为会话内没有人工输入面而反复空转
- workspace 只保留了本地路径 `origin`，没有 GitHub remote，导致 `gh pr ...` / `gh issue ...` 在 workspace 内直接失败
- issue 被打到 `blocked`，但没有写明解除条件和应该恢复到哪个状态
- `blocked` 只是状态误标：其实 PR 已 merged / 已有 open PR / 已有 APPROVED，只是没有恢复到 `Global Stewardship` / `Rework` / `In Progress`
- workspace 目录还在，但 `.git` 丢失，导致 `before_run` 反复报 `not a git repository`
- GitHub token 失效
- 正式服务没加载最新 workflow

处理：
- 看 Draft PR 评论与 `APPROVED`
- 新建 GitHub issue 时默认只打 `symphony` 与 `todo`，不要在创建时预贴 `design-review`
- 如果任务是普通 bugfix 或小范围现有模块修复，但没有 Draft PR，优先按低风险路径排查，不要继续等待人工审批
- 如果任务命中高风险条件且已经在 `Design Review`，但没有 linked Draft PR，先看 orchestrator 日志是否已触发一次引导执行；若仍没有 Draft PR，优先排查 GitHub token、`gh`/push 权限、branch/PR 创建失败，而不是继续等待审批
- 如果日志里反复只有通用 repo 扫描而没有 issue 标识、标题、描述，先检查 `WORKFLOW.freshquant.md` 是否仍包含 issue placeholders；`sync_freshquant_symphony_service.ps1` / `start_freshquant_symphony.ps1` 现在会对这份 prompt 做合约校验
- 如果 `Merging` 很慢，先看 session 里是否出现 `gh pr checks --watch`、`gh run watch` 或 `Start-Sleep` 轮询；正式 prompt 现在要求只做一次性检查后结束当前 turn，让 orchestrator 下一轮继续
- 如果 merge 后原 issue 没进入 `Global Stewardship`，先看 `Merging` 会话是否真的写出了 handoff comment，并检查状态标签是否已切换
- 如果原 issue 长时间停在 `Global Stewardship`，先看全局 Codex 自动化最近一轮是否真的读取了 merged PR、当前 `main` 和已有 follow-up issue
- 如果同一个源 issue 被开出多个 follow-up issue，先按 `Source Issue + Symptom Class` 检查去重逻辑，收敛到一个 open 修复任务
- 如果全局自动化把代码问题当成运维问题处理，先核对原 issue 评论里是否已经明确写出“等待 GH-xxx 修复后继续收口”
- 如果日志里明确读入了 issue body，但随后又加载 `brainstorming` 并停在“等待批准”，说明 workflow 仍把 `Design Review` 错当成会话内交互设计阶段；应改成“issue body -> Draft PR packet -> GitHub approval”的单向流程
- 如果 `gh` 在 workspace 内报 “none of the git remotes configured for this repository point to a known GitHub host”，先看当前 workspace 是否只有本地 `origin`；正式 workflow 现在会在 `after_create` / `before_run` 自动补齐 `github` remote
- 如果 issue 停在 `blocked`，先看最新 GitHub 评论是否写清了 blocker、clear condition、evidence 和 target recovery state；没有的话先补齐，再决定是否解除
- 如果 issue 已经有 merged PR、open non-draft PR 或 approved draft PR，但还停在 `blocked`，优先按误标处理；正式 orchestrator 现在会按这些 GitHub 真值自动恢复到 `Global Stewardship` / `Rework` / `In Progress`
- 如果日志里反复出现 `workspace_hook_failed ... not a git repository`，先看 workspace 目录是否缺 `.git`；正式 orchestrator 现在会先自愈重建一次，再决定是否继续报错
- 如果 PR 标题、PR 正文、Issue / PR 评论仍然出现英文说明，先检查 `WORKFLOW.freshquant.md` 与 `runtime/symphony/templates/*.md` 是否已经同步到正式服务
- 检查正式服务是否已加载最新 `runtime/symphony/WORKFLOW.freshquant.md`
- 看 issue 当前标签与状态是否仍停在 `todo`，以及 orchestrator 日志里是否出现 `Todo -> In Progress` 自动推进记录
- 重装正式服务或重启 `fq-symphony-orchestrator`
