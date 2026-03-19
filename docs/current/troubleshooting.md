# 当前排障

第二阶段的排障顺序统一为：先确认运行面，再确认数据流，再确认页面或单个模块。不要先改代码。

## 基础命令

```powershell
docker compose -f docker/compose.parallel.yaml ps
py -3.12 script/freshquant_health_check.py --surface api --format summary
py -3.12 script/freshquant_health_check.py --surface symphony --format summary
Get-ChildItem logs/runtime -Recurse -Filter *.jsonl | Sort-Object LastWriteTime -Descending | Select-Object -First 20 FullName,LastWriteTime
powershell -ExecutionPolicy Bypass -File script/fq_local_preflight.ps1 -Mode Check
powershell -ExecutionPolicy Bypass -File script/fq_apply_deploy_plan.ps1 -FromGitDiff origin/main...HEAD
```

- 需要页面层健康检查时，优先执行 `py -3.12 script/freshquant_health_check.py --surface web --format summary`
- 这个入口会忽略系统代理环境，优先用于 deploy 后健康检查和日常排障；当前忽略键包括 `ALL_PROXY`、`HTTP_PROXY`、`HTTPS_PROXY`、`NO_PROXY` 及其小写变量
- 如果上一轮 `fq_apply_deploy_plan.ps1` 已经产生 `deploy-state-*.json`，优先执行 `powershell -ExecutionPolicy Bypass -File script/fq_apply_deploy_plan.ps1 -ResumeLatest`，不要把已完成的 Docker / baseline 阶段整轮重跑

## 本地 preflight 没有自动生效

现象：
- `git push` 前没有触发本地预检
- 明明当前 `HEAD` 没跑过预检，但 push 还是直接发出去了

先检查：
- `git config --get core.hooksPath`
- `Get-ChildItem .githooks`
- `powershell -ExecutionPolicy Bypass -File script/install_repo_hooks.ps1`
- `powershell -ExecutionPolicy Bypass -File script/fq_local_preflight.ps1 -Mode Check`

常见根因：
- 仓库 `core.hooksPath` 没指到 `.githooks`
- 当前会话没跑过 `install.bat`
- 本机没有可用的 `powershell.exe` 或 `pwsh`

处理：
- 重新执行 `powershell -ExecutionPolicy Bypass -File script/install_repo_hooks.ps1`
- 确认 `.githooks/pre-push` 存在
- 手动执行一次 `powershell -ExecutionPolicy Bypass -File script/fq_local_preflight.ps1 -Mode Ensure`

## 运行面被代理污染

现象：
- 页面或数据库链路正常，但外发 HTTP 请求失败
- `requests` / `urllib` 报 SOCKS、ProxyError、InvalidSchema 一类异常
- 同一 webhook 或 URL 手工直连能通，运行进程里却失败

先检查：
- `Get-ChildItem Env:ALL_PROXY,Env:all_proxy,Env:HTTP_PROXY,Env:http_proxy,Env:HTTPS_PROXY,Env:https_proxy,Env:NO_PROXY,Env:no_proxy`
- `Get-Content D:/fqpack/config/envs.conf`
- `Get-Content D:/fqdata/log/fqnext_realtime_xtdata_consumer_err.log -Tail 200`

常见根因：
- 宿主机 Machine/User 级环境残留代理
- supervisor 运行环境没有把代理变量清空
- 某个外发请求直接继承了系统代理

处理：
- 确认 `D:/fqpack/config/envs.conf` 中代理变量均为空
- 重新启动受影响宿主机进程或执行 `script/fqnext_host_runtime_ctl.ps1 -Mode EnsureServiceAndRestartSurfaces`
- 若仍有失败，优先看 stderr 是否是业务级 HTTP 拒绝，而不是代理错误

## Memory context 缺失或过期

现象：
- `Symphony` / `Global Stewardship` / 自由 Codex 会话启动后仍重复全量扫描仓库。
- 会话环境里没有 `FQ_MEMORY_CONTEXT_PATH`，或指向的 markdown 不存在。
- `.codex/memory/**` 已更新，但 context pack 仍反映旧事实。

先检查：
- `Get-ChildItem Env:FQ_MEMORY_CONTEXT_PATH`
- `Get-ChildItem Env:FQ_MEMORY_CONTEXT_ROLE`
- `Get-Content $env:FQ_MEMORY_CONTEXT_PATH`
- `py -3.12 runtime/memory/scripts/bootstrap_freshquant_memory.py --repo-root . --service-root D:/fqpack/runtime/symphony-service`
- `Get-Content D:/fqpack/runtime/symphony-service/artifacts/cleanup-requests/<issue>.json`
- `py -3.12 runtime/memory/scripts/refresh_freshquant_memory.py --issue-identifier GH-166 --issue-state "In Progress" --branch-name <branch> --git-status clean`
- `py -3.12 runtime/memory/scripts/compile_freshquant_context_pack.py --issue-identifier GH-166 --role codex`
- `Get-Content D:/fqpack/runtime/symphony-service/artifacts/<issue>/deployment-comment.md`
- `Get-Content D:/fqpack/runtime/symphony-service/artifacts/cleanup-results/<issue>.json`

常见根因：
- `run_freshquant_codex_session.ps1` 启动前没有成功执行 memory refresh / compile。
- `run_freshquant_codex_session.ps1` 为当前 issue state 解析错了 role，导致 `Global Stewardship` 仍拿到普通 `codex` context pack。
- 直接在 Codex app 中打开仓库时，没有走 `codex_run/start_codex_cli.bat`，且也没有手动执行 `bootstrap_freshquant_memory.py`，就开始做通用 repo 扫描。
- 直接双击 `codex_run/start_codex_app_server.bat` 后误以为“没有持续输出就是没启动”；实际上 `codex app-server` 默认走 `stdio://`，没有客户端接入前可以保持静默。
- `fq_memory` 不可写，导致热记忆集合为空。
- `cleanup-requests/<issue>.json` 缺失或字段不全，导致 context pack 无法显示 PR / branch / repository 元数据。
- `deployment-comment.md` 或 `cleanup-results/<issue>.json` 缺失，导致 deploy / health / cleanup 摘要只能回退为 `unavailable`
- `.codex/memory/**` 缺少种子文件，或 context pack 产物目录不可写。
- agent 读取了旧的 memory context，但没有回到 GitHub / `docs/current/**` / deploy 结果确认正式真值。

处理：
- 先手动重跑 `refresh_freshquant_memory.py` 和 `compile_freshquant_context_pack.py`
- 对自由会话，优先通过 `codex_run/start_codex_cli.bat` 或 `codex_run/start_codex_app_server.bat` 进入；如果当前已经在会话里，再直接运行 `bootstrap_freshquant_memory.py`
- `start_codex_app_server.bat` 正常启动后会先打印 memory context 摘要；如果窗口仍在，就说明前台 app-server 仍在运行。关闭窗口或按 `Ctrl+C` 会停止它。
- 确认 `D:/fqpack/runtime/symphony-service/artifacts/memory/context-packs/<issue>/<role>.md` 已更新
- 确认 Mongo `fq_memory` 中至少有 `task_state`、`knowledge_items`、`context_packs`
- 如果 memory context 和正式真值冲突，优先修正式真值或刷新 memory，不要反向手改 context pack

## API 无响应

现象：
- `15000` 端口不可访问，或前端页面全部报接口错误。

先检查：
- `docker compose -f docker/compose.parallel.yaml ps`
- `py -3.12 script/freshquant_health_check.py --surface api --format summary`

常见根因：
- `fq_apiserver` 没启动或容器异常退出。
- Mongo/Redis 依赖没准备好，API 容器循环重启。
- `.env` 没传给 `FQ_COMPOSE_ENV_FILE`。

处理：
- 重建 API：`docker compose -f docker/compose.parallel.yaml up -d --build fq_apiserver`
- 或优先使用 `powershell -ExecutionPolicy Bypass -File script/fq_apply_deploy_plan.ps1 -ChangedPath freshquant/rear/api_server.py -RunHealthChecks`

## ETF 前复权错误

现象：
- ETF 在页面上跨扩缩股日出现价格断层
- 例如事件日后 close 约为事件日前的一半，但事件日前没有按前复权回落

先检查：
- `python -m freshquant.cli etf.xdxr save --code 512000`
- `python -m freshquant.cli etf.adj save --code 512000`
- `python -m freshquant.cli etf.xdxr save --code 512800`
- `python -m freshquant.cli etf.adj save --code 512800`
- 查询 `quantaxis.etf_xdxr` 是否存在 `category=11` / `suogu`
- 查询 `quantaxis.etf_adj` 是否在事件日前生成了 `adj=0.5` 这类因子
- 请求 `/api/stock_data?period=1d&symbol=512000&endDate=2025-08-08`

常见根因：
- `quantaxis.etf_xdxr` 缺失扩缩股事件，导致 `etf_adj` 整段生成成 `1.0`
- ETF 历史库已更新，但没有重跑 `etf_xdxr -> etf_adj`
- 旧实现把上游空响应当真，单次同步把已有 `etf_xdxr` 清空

处理：
- 优先重跑 `etf.xdxr` 和 `etf.adj`
- 如果是全市场历史缺口，执行一次 ETF 全量回填：
  - `python -m freshquant.cli etf.xdxr save`
  - `python -m freshquant.cli etf.adj save`
- 如果库里 `etf_adj` 已正确，而页面仍错误，再查 `/api/stock_data` 所在运行面是否仍在读旧库或旧容器

## Docker API 报 `fq_mongodb:27027`

现象：
- `15000` 或 `18080/api/*` 请求超时
- `fq_webui` 日志出现 `504 upstream timed out`
- `fq_apiserver` 日志出现 `ServerSelectionTimeoutError: fq_mongodb:27027`

先检查：
- `docker exec <fq_apiserver> /freshquant/.venv/bin/python -c "from freshquant.bootstrap_config import bootstrap_config; print({'host': bootstrap_config.mongodb.host, 'port': bootstrap_config.mongodb.port, 'db': bootstrap_config.mongodb.db})"`
- `docker exec <fq_apiserver> env | findstr MONGODB`
- `docker compose -f docker/compose.parallel.yaml config`

常见根因：
- 容器环境只覆写了 `FRESHQUANT_MONGODB__HOST=fq_mongodb`，没有同时覆写 `FRESHQUANT_MONGODB__PORT=27017`
- `freshquant_bootstrap.yaml` 或容器环境只覆写了 Mongo host，但没有同时把端口收口到容器内 `27017`

处理：
- 在 `docker/compose.parallel.yaml` 为 `fq_apiserver`、`fq_tdxhq`、`fq_dagster_webserver`、`fq_dagster_daemon`、`fq_qawebserver` 同时显式注入 `FRESHQUANT_MONGODB__HOST=fq_mongodb`、`FRESHQUANT_MONGODB__PORT=27017`、`MONGODB=fq_mongodb`、`MONGODB_PORT=27017`
- 如果并行环境还依赖主工作树 `.env`，也同步补齐 `FRESHQUANT_MONGODB__PORT=27017` 与 `MONGODB_PORT=27017`
- 重建受影响容器后，再检查 `bootstrap_config.mongodb` 是否解析为 `{'host': 'fq_mongodb', 'port': 27017, ...}`

## Web 页面空白

现象：
- `18080` 可打开但页面白屏，或单页能进、数据区全空。

先检查：
- `py -3.12 script/freshquant_health_check.py --surface web --format summary`
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
  - 在组件 Event 视图看 `xt_producer` 的 `bootstrap` / `config_resolve` / `subscription_load` / `heartbeat`
  - 在组件 Event 视图看 `xt_consumer` 的 `bootstrap` / `heartbeat`
  - 在 health 卡片上看 `xt_producer` 的心跳年龄、`收 tick`、`5m ticks`、`订阅`
  - 在 health 卡片上看 `xt_consumer` 的心跳年龄、`最近处理`、`5m bars`、`backlog`

## Guardian 不触发或不下单

现象：
- 页面有信号，但没有订单请求。

先检查：
- 运行命令是否是 `--mode event`
- `monitor.xtdata.mode` 是否是 `guardian_1m` 或 `guardian_and_clx_15_30`
- `must_pool` / `xt_positions` 是否包含目标股票
- `pm_current_state` 是否允许开仓

常见根因：
- Guardian monitor 没有按 event 模式启动。
- 信号超过 30 分钟被跳过。
- buy/sell 冷却键仍在 Redis 里。
- Position management 因 `HOLDING_ONLY` 或 `FORCE_PROFIT_REDUCE` 拒绝。

处理：
- 查 runtime 里的 `guardian_strategy`、`position_gate`、`order_submit`
- 在 `/runtime-observability` 先切到全局 Trace，优先看 `trace_kind=guardian_signal` 的最近链路
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
- `/api/gantt/shouban30/plates?provider=xgb&days=30`

常见根因：
- Dagster 任务未跑。
- `end_date` 对应快照还没生成。
- `days` 不在 `30|45|60|90`。
- 交易日日历源瞬时失败；当前实现会在移除 `ALL_PROXY`、`HTTP_PROXY`、`HTTPS_PROXY`、`NO_PROXY` 及其小写变量后自动重试 3 次，但连续失败时仍拿不到最新完成交易日。
- XGB / JYGS 上游 HTTPS 瞬时抖动；当前实现会在移除 `ALL_PROXY`、`HTTP_PROXY`、`HTTPS_PROXY`、`NO_PROXY` 及其小写变量后自动重试 3 次，但连续失败时仍会让当天 Dagster 作业失败。
- `jygs` 最近历史存在缺口，最近 `90` 个交易日 hole scan 还没补齐。
- 上游 `jygs` 某个交易日确实没有热点；此时原始集合会保留 `is_empty_result=true` marker，但 gantt `series` 不会有点位。
- 上游返回了别的 `trade_date`；此时会落 `empty_reason=upstream_trade_date_mismatch` marker，但该日期仍应继续进入 hole scan 重试。
- 上游 `jygs action_field` 可能夹带单条缺 `reason` 的历史主题行；当前实现会跳过坏行并继续同步当天其余主题。若整天过滤后没有可用主题，则会落 `empty_reason=invalid_theme_fields` marker，而不是把整条 Dagster 作业打断。
- Shouban30 最新快照可能字段齐全但仍是旧交易日窗口语义；如果 `stock_window_from` 早于对应自然日窗口起点，当前实现会把它视为 legacy snapshot，需补跑重建。

处理：
- 重跑 Dagster 作业
- 确认读模型索引与快照日期
- 在任务运行环境检查 `ALL_PROXY`、`all_proxy`、`HTTP_PROXY`、`http_proxy`、`HTTPS_PROXY`、`https_proxy`、`NO_PROXY`、`no_proxy` 是否被错误注入，再确认 AkShare 到 Sina 可访问
- 若日志里是 `flash-api.xuangubao.cn` / `app.jiuyangongshe.com` 的 `SSLError`、`ConnectionError`、`ReadTimeout` 一类请求异常，先确认当天自动 3 次重试后是否仍失败；仍失败时再补跑 Dagster
- 若 `/api/gantt/plates?provider=jygs&days=15/30/45/60/90` 的 `dates` 轴完整但 `series` 很少，先看 `jygs_action_fields` / `jygs_yidong`
- 若 marker 是 `empty_reason=upstream_trade_date_mismatch`，不要当成已补完；继续补跑 Dagster，等待上游返回目标交易日
- 若日志里出现 `skipping invalid jygs theme rows`，说明是上游单条主题缺 `reason`；先核对该 trade_date 其他主题是否已正常落库，再确认是否需要人工补录该主题说明
- 若目标交易日既没有真实 `jygs` 数据，也没有 `is_empty_result=true` marker，说明 recent hole scan 还没覆盖到；继续补跑 Dagster
- 若 `/gantt/shouban30` 在不同 `days` 间切换后最早上板时间不变，优先检查 `shouban30_plates.stock_window_from`；确认是旧交易日窗口快照后，不需要手工删旧数据，直接重跑当前重建流程覆盖即可

## Shouban30 `sync-to-tdx` 成功但宿主机 `.blk` 不变

现象：
- `/api/gantt/shouban30/pre-pool/sync-to-tdx` 或 `/api/gantt/shouban30/stock-pool/sync-to-tdx` 返回 `200`
- 但 `D:\tdx_biduan\T0002\blocknew\30RYZT.blk` 没变化

先检查：
- `docker compose -f docker/compose.parallel.yaml config`
- `docker compose -f docker/compose.parallel.yaml exec fq_apiserver sh -lc "ls -la /opt/tdx/T0002/blocknew"`
- `docker compose -f docker/compose.parallel.yaml exec fq_apiserver sh -lc "python - <<'PY'\nfrom freshquant.bootstrap_config import bootstrap_config\nprint({'home': bootstrap_config.tdx.home, 'hq_endpoint': bootstrap_config.tdx.hq_endpoint})\nPY"`

常见根因：
- `fq_apiserver` 没有挂载 `${FQPACK_TDX_SYNC_DIR:-D:/tdx_biduan}:/opt/tdx`
- `FRESHQUANT_TDX__HOME` 没指到 `/opt/tdx`
- 宿主机目录不是 `D:\tdx_biduan`，但 `FQPACK_TDX_SYNC_DIR` 没同步调整

处理：
- 在 `docker/compose.parallel.yaml` 确认 `fq_apiserver` 挂载 `${FQPACK_TDX_SYNC_DIR:-D:/tdx_biduan}` 到 `/opt/tdx`
- 确认 Docker env file 中 `FRESHQUANT_TDX__HOME=/opt/tdx`
- 重建 `fq_apiserver` 后，再核对 `D:\tdx_biduan\T0002\blocknew\30RYZT.blk`

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
- 原始事件只有 `heartbeat`，或缺少 `trace_id` / `intent_id` / `request_id` / `internal_order_id`，因此不会进入全局 Trace 列表。
- 组件卡片是固定核心组件全集；如果显示 `unknown / no data`，说明组件存在但最近没有可聚合的 health 数据。
- `/api/runtime/traces` 与 `/api/runtime/health/summary` 已有数据，但 `fq_webui` 仍在跑旧静态资源，或页面代码仍按 `response.data.*` 读取而不是读取顶层 `traces/components/trace/files/records`。
- 当前 pytest 默认会把 runtime root 指向临时目录；如果现场页面里仍出现 `remark=pytest`、`ord_test_1`、`tp_batch_1` 一类样本，优先怀疑页面读到的不是正式现场目录。

处理：
- 直接 tail 原始文件，而不是只看页面
- 先看 `/api/runtime/events` 或 raw browser，确认最近事件是否带强关联键
- 如果目标是确认 `xt_producer` / `xt_consumer` 是否还活着，优先切到组件 Event 视图，不要把 heartbeat 当 Trace 缺失
- 清空筛选后刷新页面
- 如果 API 有数据但页面统计卡、recent feed、component board 全空，优先重建并重新部署 `fq_webui`，然后强刷浏览器缓存

## Runtime Observability Trace 列表 500

现象：
- 点击 `/runtime-observability` 左侧组件卡片后，前端提示 `Trace 列表加载失败：Request failed with status code 500`

先检查：
- 直接访问 `/api/runtime/traces`
- 目标时间窗里是否存在大量重复的 `request_id` / `internal_order_id` / `broker_trade_id` 关联链

常见根因：
- 旧版 runtime assembler 对强关联 ID 分组仍使用递归 union-find；当 `xt_report_ingest` 因重复回放把链路拉得很深时，会触发 `RecursionError`
- API 已更新，但 `fq_webui` 仍在跑旧静态资源或浏览器缓存没刷新

处理：
- 优先重建并部署 `fq_apiserver`
- 如果 API 已恢复 `200` 但前端仍报错，再重建 `fq_webui` 并强刷浏览器缓存
- 如果同一时间窗里 `XT 回报接入.trade_match` 明显按 `3` 秒节奏重复刷，继续看下一节排查 replay 根因

## XT 回报接入.trade_match 高频

现象：
- `/runtime-observability` 中 `XT 回报接入.trade_match` 高频出现，看起来像“每秒都在新增成交”

先检查：
- 同一 `broker_trade_id` 是否反复出现
- 事件是否集中在约 `3` 秒轮询节奏
- `trade_match` 的 `status` 是否为 `skipped`
- `trade_match.payload.created` / `trade_match.payload.dedup_hit` 是什么
- 对照 `om_trade_facts`、`om_sell_allocations`、Guardian open slices，确认是否真的重复写入

常见根因：
- `fqnext_xt_account_sync_worker` 每 `3` 秒轮询一次 XT 当日全部成交
- 同一 `broker_trade_id` 的成交回报被重复回放
- 旧版代码把 `reconcile_trade_reports()` 的空结果误判成“未处理”，导致同一笔成交反复进入 `xt_report_ingest`

处理：
- 如果 `status=skipped` 且 `payload.created=false`、`payload.dedup_hit=true`，说明重复回放已被当前代码拦截；这不是新成交
- 如果重复事件仍是 `status=info`，或 `om_sell_allocations` / Guardian open slices 仍被重复改写，优先确认 `order_management`、`xt_account_sync`、`xtquant_broker` 是否已部署到包含幂等修复的最新代码
- 真实成交次数以 `om_trade_facts` 中唯一 `broker_trade_id` 数量为准，不要只看 runtime event 次数

## 初始化程序第 3 步提示未连接到交易系统或账户信息缺失

现象：
- 运行 `python -m freshquant.initialize`。
- 第 3 阶段 `运行态 bootstrap` 输出 `未连接到交易系统或账户信息缺失`。

先检查：
- `params.xtquant.path` 是否指向 MiniQMT 的 `userdata_mini`
- `params.xtquant.account` / `params.xtquant.account_type` 是否与当前登录账号一致
- MiniQMT 是否不只是进程存在，而是已经登录到目标交易账号

当前行为：
- 初始化程序在第 3 阶段会先按当前 `xtquant` 配置尝试建立一次 XT 交易连接，再做资产/持仓/委托/成交同步。

常见根因：
- `xtquant.path` 指到了安装目录或别的 `userdata_mini`
- `xtquant.account` 与 MiniQMT 当前登录账号不一致
- `xtquant.account_type` 填错，导致订阅失败
- MiniQMT 进程已经启动，但交易账号还没真正登录完成

处理：
- 在系统设置里确认并保存 `xtquant.path / account / account_type`
- 确认 MiniQMT 已登录目标账号后重新执行初始化
- 若仍失败，再单独检查 `fqnext_xtquant_broker` 运行日志里的 connect / subscribe 错误码

## Deploy 后运维面检查失败

现象：
- API / Web health check 已通过，但 `Global Stewardship` 仍不做 cleanup / close。
- Issue 评论或部署说明里出现 runtime ops check `passed=false`。
- `runtime/symphony/scripts/check_freshquant_runtime_post_deploy.ps1 -Mode Verify` 的 `failures` 非空。

先检查：
- `docker compose -f docker/compose.parallel.yaml ps`
- `Get-Service fq-symphony-orchestrator`
- `Get-Service fqnext-supervisord`
- `powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode Status`
- `powershell -ExecutionPolicy Bypass -File runtime/symphony/scripts/check_freshquant_runtime_post_deploy.ps1 -Mode Verify -BaselinePath <baseline.json> -OutputPath <verify.json> -DeploymentSurface <surfaces>`
- compose project 前缀后的容器名（例如 `fqnext_20260223-fq_apiserver-1`）当前会自动归一化；正常情况下不需要再手工准备 Docker snapshot alias

常见根因：
- `fq_mongodb` / `fq_redis` / 本轮要求存在的容器进入 `Restarting`、`Exited` 或 `unhealthy`
- 本轮涉及 `runtime/symphony/**`，但 `fq-symphony-orchestrator` 没恢复到 `Running`
- 本轮涉及宿主机 deployment surface，但 `fqnext-supervisord` 没恢复到 `Running`
- deploy 前已在跑的关键进程被这轮 deploy 打掉，deploy 后没有恢复
- 本轮明确要求恢复的 `market_data` / `guardian` / `position_management` / `tpsl` 进程没有重启成功
- 本轮明确要求恢复的 `order_management` broker / worker 没重启成功
- 自动化漏采 baseline，导致无法按“deploy 前已运行 -> deploy 后仍需存在”的规则判断
- 旧版 verify 依赖 `Win32_Process.CommandLine`，在当前宿主机上可能对 Python 进程产生假阴性；当前脚本已改成 supervisor-first，如果仍失败，优先怀疑 `fqnext-supervisord` 控制面本身而不是业务进程已退出

处理：
- 先按 `verify.json` 的 `docker_checks` / `service_checks` / `process_checks` 定位失败项，不要直接 cleanup
- 如果宿主机 service 本身没起来，优先用 `script/invoke_fqnext_supervisord_restart_task.ps1` 恢复底座，再重新执行 host runtime control
- 如果 `fqnext-supervisord` service 仍是 `Running`，但 `EnsureServiceAndRestartSurfaces` 首次重启失败，优先复核脚本是否已经自动触发过一次管理员桥接；当前正式入口会在这种“service 存活但 control plane 脏掉”的场景下自动 bridge 一次
- 如果是代码问题，只创建或复用 follow-up issue，由下一轮 `Symphony` 接手
- 如果是外部环境问题，在原 issue 记录 blocker / clear condition / evidence / target recovery state
- 修复后重新执行 deploy、health check 和 runtime ops check，只有全部通过后才允许 cleanup / close

## fqnext-supervisord 底座不可用

现象：
- `Get-Service fqnext-supervisord` 显示 `Stopped` 或 `Missing`
- `powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode Status` 无法返回 RPC 状态
- `Global Stewardship` 在宿主机 deployment surface 上无法继续重启目标 program

先检查：
- `Get-Service fqnext-supervisord`
- `powershell -ExecutionPolicy Bypass -File script/invoke_fqnext_supervisord_restart_task.ps1`
- `powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode Status`

处理：
- 如果 service 尚未安装，在提升权限会话执行：
  - `powershell -ExecutionPolicy Bypass -File script/install_fqnext_supervisord_service.ps1`
  - `powershell -ExecutionPolicy Bypass -File script/install_fqnext_supervisord_restart_task.ps1`
- 如果 service 已安装但普通会话无权恢复，走 `fqnext-supervisord-restart` 管理员桥接任务
- 恢复后再执行 `script/fqnext_host_runtime_ctl.ps1 -Mode EnsureServiceAndRestartSurfaces -DeploymentSurface <surfaces> -BridgeIfServiceUnavailable`
- 当前正式入口在 `restart-surfaces` 首次失败后会自动做一次 bridge retry；如果仍失败，再按业务日志继续定位，不要无界重复 bridge

## Symphony / Global Stewardship（Issue-managed）卡住

本节仅适用于走 `Symphony` / `Global Stewardship` 的 Issue-managed 任务；仓库级 direct `feature branch -> PR` 不进入这条状态机。

现象：
- Issue 被领取但不前进，merge 后没有进入 `Global Stewardship`，或原 issue 长时间不收口。

先检查：
- `py -3.12 script/freshquant_health_check.py --surface symphony --format summary`
- `Get-Service fq-symphony-orchestrator`
- `runtime/symphony-service/artifacts/`

常见根因：
- Issue-managed 任务的 Issue body 不完整，导致 agent 只能反复做泛化上下文扫描
- 正式服务加载了一份过度简化的 `WORKFLOW.freshquant.md`，prompt 中没有 issue 标识/标题/描述，导致 agent 只会做泛化上下文扫描
- `Merging` 会话里直接使用 `gh pr checks --watch`、`gh run watch` 或带 `Start-Sleep` 的长轮询脚本，导致单个 turn 长时间占住 agent，甚至被 stall detector 杀掉后重试
- `Merging` 没有按 GitHub PR 真值判断，而是错误把评论或主观推断当成 merge 条件
- `pending checks` 被错误打回 `Rework`
- `Rework` 没有写清 `blocker_class / evidence / next_action / exit_condition`
- 在 GitHub 真值没有变化时重复尝试 merge，导致 `Merging <-> Rework` 空转
- `Merging` 没有写 handoff comment，或 merge 后没有把原 issue 转到 `Global Stewardship`
- 全局 Codex 自动化没有运行，或没有读取最新 `runtime/symphony/prompts/global_stewardship.md`
- 会话启动前的 memory refresh / compile 已失败，但 wrapper 没有留下可读的 `FQ_MEMORY_CONTEXT_PATH`
- 全局 Codex 自动化把需要代码修复的问题当成纯收口问题，导致原 issue 一直停在 `Global Stewardship`
- 全局 Codex 自动化没有做 follow-up issue 去重，重复创建了多个同源修复任务
- 本轮实际发生 deploy，但自动化没有先采 baseline 或没有执行 runtime ops check，导致收口条件一直不满足
- runtime ops check 已经失败，但被误以为是 cleanup 卡住；实际上这是设计上的阻断，不应继续 close 原 issue
- workspace 只保留了本地路径 `origin`，没有 GitHub remote，导致 `gh pr ...` / `gh issue ...` 在 workspace 内直接失败
- issue 被打到 `blocked`，但没有写明解除条件和应该恢复到哪个状态
- `blocked` 只是状态误标：其实 PR 已 merged、PR checks 仍在 pending，或 open PR 已有确定性仓库内失败，但没有恢复到 `Global Stewardship` / `Merging` / `Rework`
- workspace 目录还在，但 `.git` 丢失，导致 `before_run` 反复报 `not a git repository`
- GitHub token 失效
- 正式服务没加载最新 workflow

处理：
- 对 Issue-managed 任务，先看 Issue body 是否已经写清背景、目标、范围、非目标、验收标准、部署影响
- 需要 Symphony 接管的新建 GitHub issue 时默认只打 `symphony` 与 `in-progress`
- 如果日志里反复只有通用 repo 扫描而没有 issue 标识、标题、描述，先检查 `WORKFLOW.freshquant.md` 是否仍包含 issue placeholders；`sync_freshquant_symphony_service.ps1` / `start_freshquant_symphony.ps1` 现在会对这份 prompt 做合约校验
- 如果会话一开始就回到全仓扫描，先看 `FQ_MEMORY_CONTEXT_PATH` 是否存在，以及 `runtime/memory/scripts/refresh_freshquant_memory.py` / `compile_freshquant_context_pack.py` 最近一次是否执行成功
- 对自由会话，再补查是否绕过了 `codex_run/*.bat`，或 `codex_run/start_freshquant_codex.ps1` 在 bootstrap 阶段提前失败
- 如果 `Merging` 很慢，先看 session 里是否出现 `gh pr checks --watch`、`gh run watch` 或 `Start-Sleep` 轮询；正式 prompt 现在要求只做一次性检查后结束当前 turn，让 orchestrator 下一轮继续
- 如果 PR 无法 merge，先看 required checks、unresolved review threads、`mergeStateStatus` 和 ruleset，不要先看评论里的 `APPROVED`
- 如果 required checks 还在 pending，保持在 `Merging`，不要提前打回 `Rework`
- 如果已经进入 `Rework`，先检查 issue / PR 评论里是否已经写清 `blocker_class / evidence / next_action / exit_condition`
- 如果没有新 commit、新 checks 结果、新 review-thread 变化或新 mergeability 变化，不要重复尝试 merge
- 如果 merge 后原 issue 没进入 `Global Stewardship`，先看 `Merging` 会话是否真的写出了 handoff comment，并检查状态标签是否已切换
- 如果原 issue 长时间停在 `Global Stewardship`，先看全局 Codex 自动化最近一轮是否真的读取了 merged PR、当前 `main` 和已有 follow-up issue
- 如果本轮评论里 health check 已通过但没有 runtime ops check 结果，先检查 `check_freshquant_runtime_post_deploy.ps1` 是否已同步到正式服务，以及 prompt 是否已要求 `CaptureBaseline -> Verify`
- 如果 runtime ops check 结果里 `failures` 非空，不要继续排 cleanup；先按失败项判断是 follow-up issue 还是外部 blocker
- 如果同一个源 issue 被开出多个 follow-up issue，先按 `Source Issue + Symptom Class` 检查去重逻辑，收敛到一个 open 修复任务
- 如果全局自动化把代码问题当成运维问题处理，先核对原 issue 评论里是否已经明确写出“等待 GH-xxx 修复后继续收口”
- 如果 `gh` 在 workspace 内报 “none of the git remotes configured for this repository point to a known GitHub host”，先看当前 workspace 是否只有本地 `origin`；正式 workflow 现在会在 `after_create` / `before_run` 自动补齐 `github` remote
- 如果 issue 已进入 `In Progress` / `Rework`，但 workspace 仍在本地 `main`，先看 issue 是否缺失确定性 `branch_name`，以及 orchestrator 日志里是否出现 issue branch checkout 失败
- 如果 issue 停在 `blocked`，先看最新 GitHub 评论是否写清了 blocker、clear condition、evidence 和 target recovery state；没有的话先补齐，再决定是否解除
- 如果 issue 已经有 merged PR、open PR + pending checks、或 open PR + 确定性仓库内失败，但还停在 `blocked`，优先按误标处理；正式 orchestrator 现在会按这些 GitHub 真值自动恢复到 `Global Stewardship` / `Merging` / `Rework` / `In Progress`
- 如果日志里反复出现 `workspace_hook_failed ... not a git repository`，先看 workspace 目录是否缺 `.git`；正式 orchestrator 现在会先自愈重建一次，再决定是否继续报错
- 如果 PR 标题、PR 正文、Issue / PR 评论仍然出现英文说明，先检查 `WORKFLOW.freshquant.md` 与 `runtime/symphony/templates/*.md` 是否已经同步到正式服务
- 检查正式服务是否已加载最新 `runtime/symphony/WORKFLOW.freshquant.md`
- 看 issue 当前标签是否仍是 `in-progress / rework / merging / blocked / global-stewardship` 之一，以及 orchestrator 日志里是否按新状态机推进
- 重装正式服务或重启 `fq-symphony-orchestrator`
