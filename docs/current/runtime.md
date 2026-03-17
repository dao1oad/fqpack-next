# 当前运行面

## 宿主机与 Docker 分层

### Windows 宿主机承担

- XTQuant / XTData 连接。
- Mongo 通过 `127.0.0.1:27027` 接入 Docker `fq_mongodb`；宿主机链路不要再使用 `127.0.0.1:27017`。
- `fqnext-supervisord` 宿主机底座与其托管的交易/运行链 Python 进程。
- Guardian monitor。
- Position management worker（刷新账户级状态；启动时做一次单标的实时仓位 fallback 种子刷新）。
- TPSL tick listener。
- Symphony 正式单实例 orchestrator。
- 需要直接访问券商、终端、`TDX_HOME` 或 Windows 本地目录的组件。

### Docker 并行环境承担

- MongoDB：宿主机 `27027 ->` 容器内 `27017`
- Redis：`6380 -> 6379`
- API Server：`15000 -> 5000`
- TDXHQ：`15001 -> 5001`
- Dagster Webserver：`11003 -> 10003`
- QAWebServer：`18010 -> 8010`
- Web UI：`18080 -> 80`
- TradingAgents backend：`13000 -> 8000`
- TradingAgents frontend：`13080 -> 80`

对应编排文件是 `docker/compose.parallel.yaml`。

## 当前正式服务

- Symphony 正式服务名：`fq-symphony-orchestrator`
- Symphony 状态接口：`http://127.0.0.1:40123/api/v1/state`
- Symphony 工作区根目录：`D:/fqpack/runtime/symphony-service/workspaces`
- Symphony 按需管理员计划任务：`fq-symphony-orchestrator-restart`
- Symphony 管理员桥接状态文件：`D:/fqpack/runtime/symphony-service/artifacts/admin-bridge/restart-status.json`
- 正式自动部署 workflow：`.github/workflows/deploy-production.yml`
- 正式自动部署 state：`D:/fqpack/runtime/symphony-service/artifacts/formal-deploy/production-state.json`
- 正式自动部署单次运行 artifacts：`D:/fqpack/runtime/symphony-service/artifacts/formal-deploy/runs`
- 管理员桥接任务以 `SYSTEM` + `Highest` 运行；安装脚本会给执行安装的 Windows 用户追加该任务的读取/执行权限，供普通 Codex 会话调用。
- Symphony 运行模板：`runtime/symphony/WORKFLOW.freshquant.md`
- 全局 Codex 自动化提示词模板：`runtime/symphony/prompts/global_stewardship.md`
- Symphony / Global Stewardship 会在启动 `codex` 前通过 `runtime/memory/scripts/refresh_freshquant_memory.py` + `runtime/memory/scripts/compile_freshquant_context_pack.py` 刷新全局记忆并编译 context pack
- 直接在 Codex app 中打开仓库的自由会话，如果没有现成 `FQ_MEMORY_CONTEXT_PATH`，应先执行 `runtime/memory/scripts/bootstrap_freshquant_memory.py` 自举 memory refresh / compile，再读取返回的 `context_pack_path`
- memory refresh 当前会汇总 `.codex/memory/**`、`docs/current/modules/*.md`、`artifacts/cleanup-requests/<issue>.json`、`artifacts/<issue>/deployment-comment.md`、`artifacts/cleanup-results/<issue>.json`，把 PR / deploy / health / cleanup 摘要写入 `fq_memory`
- 会话通过环境变量 `FQ_MEMORY_CONTEXT_PATH` 注入本轮 context pack，并通过 `FQ_MEMORY_CONTEXT_ROLE` 暴露当前角色；`Global Stewardship` 默认编译 `global-stewardship` pack，其它工作区会话默认编译 `codex` pack
- `bootstrap_freshquant_memory.py` 会为自由会话推导 `issue_identifier`：优先用显式参数，其次用 workspace 目录名或 branch 中的 issue id，最后回退到 `LOCAL-<workspace-name>`
- agent 应先读该文件，再回到 GitHub / `docs/current/**` / deploy 结果确认正式真值
- 冷记忆目录：`.codex/memory`
- 热记忆 Mongo database：`fq_memory`
- context pack 产物根目录：`D:/fqpack/runtime/symphony-service/artifacts/memory/context-packs`
- Deploy 后运维面检查脚本：`runtime/symphony/scripts/check_freshquant_runtime_post_deploy.ps1`
- 共享部署计划脚本：`script/freshquant_deploy_plan.py`
- 正式自动部署 orchestrator：`script/ci/run_formal_deploy.py`
- 宿主机运行时控制脚本：`script/fqnext_host_runtime_ctl.ps1`
- FQNext 宿主机 Supervisor service：`fqnext-supervisord`
- FQNext 宿主机 Supervisor RPC：`http://127.0.0.1:10011/RPC2`
- FQNext 宿主机 Supervisor 配置：`D:/fqpack/config/supervisord.fqnext.conf`
- FQNext 宿主机 Supervisor 管理员桥接任务：`fqnext-supervisord-restart`
- FQNext 宿主机 Supervisor 管理员桥接 runner：`D:/fqpack/supervisord/scripts/run_fqnext_supervisord_restart_task.ps1`
- 运维面检查脚本固定支持 `-Mode CaptureBaseline` 与 `-Mode Verify`，输出 JSON `baseline/docker_checks/service_checks/process_checks/warnings/failures/passed`
- 仓库层面的轻量更新允许直接走 `feature branch -> PR`；只有需要 Symphony 编排的任务才进入 issue 状态机
- Symphony-managed 新任务默认通过 issue template 创建，初始标签应为 `symphony + in-progress`
- Symphony workspace 默认从本地工作树 clone，但 `after_create` / `before_run` 会补齐 `github` remote 并把 `remote.pushDefault` 设为 `github`
- 对 Symphony 管理的任务，GitHub Issue body 即执行合同；Symphony 不再管理 `Design Review` 或人工审批
- 对 Symphony 管理的任务，进入 `In Progress` / `Rework` / `Merging` 前，orchestrator 会把 workspace 切到确定性的 issue branch，而不是继续停在本地 `main`
- `Merging` 现在只负责 merge 到 remote `main`、写 handoff comment，并把 issue 转入 `Global Stewardship`
- `Merging` 只认 GitHub PR 真值：required checks、unresolved review threads、mergeability、ruleset policy
- required checks 仍在 pending 时，issue 保持在 `Merging`，不要提前打回 `Rework`
- `Rework` 只用于未 merge 前的确定性仓库内问题；进入时必须同时记录 `blocker_class`、`evidence`、`next_action`、`exit_condition`
- `Global Stewardship` 由单个全局 Codex 自动化负责；它统一处理 deploy、health check、runtime ops check、cleanup 和 follow-up issue 创建
- `Global Stewardship` 在真正执行 deploy 前，应先调用 `script/freshquant_deploy_plan.py` 生成本轮 Docker / 宿主机计划
- 自动正式部署会基于 `production-state.json` 里的 `last_success_sha` 计算本轮增量；首次 bootstrap 时才做全量 deploy
- `Global Stewardship` 只有在本轮实际发生 deploy 时才做 runtime ops check；执行顺序固定为 `deploy -> health check -> runtime ops check -> cleanup`
- 全局记忆层只提供旁路汇总，不新增正式真值源；如果 memory context 与 GitHub / `docs/current/**` / 实际 deploy 结果冲突，正式真值优先
- 命中宿主机 deployment surface 时，正式入口固定为 `script/fqnext_host_runtime_ctl.ps1`；`D:\fqpack\supervisord\frequant-next.bat` 仅保留为兼容人工入口
- 如果当前 Codex 会话没有管理员权限，`runtime/symphony/**` 的重载应走预装的计划任务桥接：普通会话先 `sync_freshquant_symphony_service.ps1`，再调用 `invoke_freshquant_symphony_restart_task.ps1`
- 如果当前 Codex 会话没有管理员权限且 `fqnext-supervisord` service 需要恢复，应走预装的 `fqnext-supervisord-restart` 管理员桥接任务；普通会话不直接承担 service 修复
- `script/fqnext_host_runtime_ctl.ps1 -Mode EnsureServiceAndRestartSurfaces` 在走过 `fqnext-supervisord` service 恢复路径后，会先等待目标 surfaces 的托管进程脱离 `STARTING/STOPPING` 并稳定下来，再执行逐个 restart，避免和 supervisor 自启动阶段发生竞态
- 对 `market_data` surface，`restart-surfaces` / `wait-settled` 的有效超时下限固定为 `180s`；`fqnext_realtime_xtdata_producer`、`fqnext_realtime_xtdata_consumer`、`fqnext_xtdata_adj_refresh_worker` 在 custom `fqnext-supervisord` 上已知可能在收到 start 请求后持续数十秒保持 `EXITED/STARTING`
- `run_freshquant_symphony_restart_task.ps1` 在服务进入 `Running` 后仍会继续轮询 `http://127.0.0.1:40123/api/v1/state`，直到健康检查返回 `200` 或超时，避免把端口释放窗口误判为重载失败。
- merge 后若发现代码问题，只创建 follow-up issue，由下一轮 `Symphony` 接手；不把原 issue 拉回 `Rework`
- `Blocked` 只用于真实外部阻塞；进入 `Blocked` 时必须同时记录阻塞原因、解除条件、当前证据和恢复目标状态（`In Progress` / `Rework` / `Merging` / `Global Stewardship`）
- 如果 GitHub 真值已经表明 `Blocked` 只是误标，orchestrator 会自动恢复：merged PR, pending ops -> `Global Stewardship`；open PR 且 checks pending -> `Merging`；open PR 且存在确定性仓库内失败 -> `Rework`；无 open PR -> `In Progress`
- 如果 workspace 目录存在但缺失 git 元数据，orchestrator 会在下一次执行前自愈重建一次，而不是无限重试 `not a git repository`
- Symphony `sync/start` 会校验 workflow prompt 合约，至少要求保留 issue-managed 任务的 issue 标识、标题、状态、描述、URL、Issue 作为执行合同的规则、GitHub PR 真值规则、以及 issue branch checkout 规则
- Symphony `sync/start` 也会校验 `prompts/merging.md` 的关键 guardrail：`Merging` 只能做一次性检查后结束当前 turn，不应在会话内使用 `gh pr checks --watch`、`gh run watch` 或 `Start-Sleep` 长轮询；`Merging` 不负责 deploy、health check 或 cleanup，只负责 handoff 到 `Global Stewardship`
- Symphony `sync/start` 还会校验 `prompts/global_stewardship.md` 的关键 guardrail：必须按当前 `main` 统一判断部署、实际 deploy 时先采 runtime baseline 再做 runtime ops check、只创建 follow-up issue、不直接建修复 PR、并在无 open follow-up 阻塞时才允许关闭原 issue
- memory refresh / compile 的正式脚本入口位于 `runtime/memory/scripts/**`；第一版只做结构化冷/热记忆和角色化 markdown context pack，不引入向量库或 embedding 检索
- 自由 Codex 会话的正式自举入口是 `runtime/memory/scripts/bootstrap_freshquant_memory.py`
- Symphony 写入 GitHub 的正式文本默认使用简体中文
- 全局 Codex 自动化发现需要代码修复的问题时，只创建 follow-up issue，由下一轮 `Symphony` 接手；不直接建修复 PR
- 运行日志根目录：`logs/runtime`，可被 `FQ_RUNTIME_LOG_DIR` 覆盖

## 最小可用运行面

当目标是调试主交易链时，至少需要：

- MongoDB
- Redis
- API Server
- XTData producer
- XTData consumer
- Guardian monitor
- Position worker
- Order submit / broker / XT 回报 ingest
- TPSL worker（如果验证退出逻辑）

当目标是调试前端展示时，至少还需要：

- Web UI
- Gantt/Shouban30 对应读模型数据
- Runtime Observability 原始日志目录
- `/stock-control` 的 Guardian 信号依赖 `stock_signals`
- `/stock-control` 的 stock_pools 模型信号依赖 `realtime_screen_multi_period`
- `/runtime-observability` 当前固定是 `全局 Trace + 组件 Event` 双视图
- Guardian 排障时优先看全局 Trace 中的 `guardian_signal` 链路；组件侧栏主要用于切到对应组件的 Event 视图

## 并行环境的默认口径

- 宿主机 `.env` 示例：`deployment/examples/envs.fqnext.example`
- 宿主机 `.env` 示例默认不再携带 `ALL_PROXY`、`HTTP_PROXY`、`HTTPS_PROXY`、`NO_PROXY` 及其小写变量
- Docker API 使用 `FQ_COMPOSE_ENV_FILE` 指向主工作树 `.env`
- GHCR 预构建镜像仅用于加速 Docker 部署，不改变运行真值；实际运行真值仍来自当前 `main`、deploy 结果与 health/runtime ops evidence
- `deploy-production.yml` 在正式 Windows self-hosted runner 上消费这些 GHCR 镜像，并把 deploy state / logs 固化到 `formal-deploy` artifacts 目录
- 宿主机 FreshQuant / FQXTrade / vendored QUANTAXIS 默认统一解析到 `127.0.0.1:27027`
- Docker 容器内部 Mongo 继续使用服务名 `fq_mongodb:27017`
- `docker/compose.parallel.yaml` 会为 `fq_apiserver`、`fq_tdxhq`、`fq_dagster_webserver`、`fq_dagster_daemon`、`fq_qawebserver` 显式注入 `FRESHQUANT_MONGODB__HOST=fq_mongodb`、`FRESHQUANT_MONGODB__PORT=27017`、`MONGODB=fq_mongodb`、`MONGODB_PORT=27017`，避免容器误继承宿主机默认 `27027`
- `docker/compose.parallel.yaml` 当前会为 `fq_apiserver` 额外挂载 `${FQPACK_TDX_SYNC_DIR:-D:/tdx_biduan}` 到容器内 `/opt/tdx`，供 Shouban30 同步 `30RYZT.blk`
- Web UI 默认访问并行 API `http://127.0.0.1:15000`
- TradingAgents 使用独立 Mongo 库 `tradingagents_cn` 与 Redis `db=8`

## 运行依赖

- XTData producer 依赖 `XTQUANT_PORT`，默认 `58610`
- XTData producer / consumer / TPSL / Order Management 共享 Redis
- Guardian、Position worker、Order Management、TPSL 共享 Mongo 基础库与运行时事件日志
- XTData `StrategyConsumer` 依赖 Redis `QUEUE:BAR_CLOSE:*` 消费最新 `1m` 收盘价，并同步刷新 `pm_symbol_position_snapshots`
- Shouban30 的 `.blk` 同步依赖宿主机 `bootstrap_config.tdx.home or TDX_HOME`
- Docker 并行环境下，Shouban30 的 API 同步链路依赖 `fq_apiserver` 挂载 `/opt/tdx`
- 当通达信根目录配置为 `D:\tdx_biduan` 时，Shouban30 会写入 `D:\tdx_biduan\T0002\blocknew\30RYZT.blk`
- `xt_producer` / `xt_consumer` 会向 `logs/runtime` 固定每 5 分钟写 1 次 heartbeat，供 `/runtime-observability` 的组件 Event / health 视图聚合；这些 heartbeat 不进入业务 Trace
- pytest 默认通过临时 `FQ_RUNTIME_LOG_DIR` 与 logger cache reset 隔离测试运行日志，避免污染正式 `logs/runtime`
- FQNext 宿主机 Supervisor 仍托管 `fqnext_realtime_xtdata_producer`、`fqnext_realtime_xtdata_consumer`、`fqnext_guardian_event`、`fqnext_position_management_worker`、`fqnext_tpsl_worker`、`fqnext_xtquant_broker`、`fqnext_credit_subjects_worker`、`fqnext_xtdata_adj_refresh_worker`

## 常见运行模式

### 只调 API / 页面

```powershell
powershell -ExecutionPolicy Bypass -File script/docker_parallel_compose.ps1 up -d --build fq_mongodb fq_redis fq_apiserver fq_webui
```

### 调实时交易链

```powershell
python -m freshquant.market_data.xtdata.market_producer
python -m freshquant.market_data.xtdata.strategy_consumer --prewarm
python -m freshquant.signal.astock.job.monitor_stock_zh_a_min --mode event
python -m freshquant.position_management.worker
python -m freshquant.tpsl.tick_listener
```

调这条链路时，`/runtime-observability` 页面至少应看到：

- 在组件 Event 视图看到 `xt_producer` 的 `bootstrap` / `config_resolve` / `subscription_load` / `heartbeat`
- 在组件 Event 视图看到 `xt_consumer` 的 `bootstrap` / `heartbeat`
- 在 health 卡片上看到 `xt_producer` 的心跳年龄、`收 tick`、`5m ticks`、`订阅`
- 在 health 卡片上看到 `xt_consumer` 的心跳年龄、`最近处理`、`5m bars`、`backlog`

### 调 Symphony 正式服务

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:40123/api/v1/state
```

### 调宿主机 Supervisor 正式底座

```powershell
powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode Status
```

## 当前阶段的运行风险

- Docker 里的 Mongo/Redis 与宿主机 broker/xtdata 之间必须通过宿主机端口对齐，否则交易链会出现“页面正常、worker 无数据”。
- 如果宿主机仍靠 `frequant-next.bat` 手工拉起，而不是 `fqnext-supervisord` service 开机自启，`Global Stewardship` 会失去稳定的正式入口与权限边界。
- 如果宿主机进程仍报 `127.0.0.1:27017`，优先检查进程环境是否缺少 `FRESHQUANT_MONGODB__HOST/PORT`，以及是否还在走旧的 `qaenv` 默认值。
- Guardian event 模式要求 `monitor.xtdata.mode` 启用 Guardian 能力；正式值为 `guardian_1m` 或 `guardian_and_clx_15_30`。
- `stock_pools模型信号` 依赖 XTData consumer 在 `guardian_and_clx_15_30` 模式下写 `realtime_screen_multi_period`；库里旧值 `clx_15_30` 也会按该模式执行。
- Runtime Observability 采用旁路写盘，日志队列满时允许丢事件；排障时要同时对照业务集合，而不是只看 runtime 页面。
