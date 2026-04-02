# 当前运行面

## 宿主机与 Docker 分层

### Windows 宿主机承担

- XTQuant / XTData 连接。
- Mongo 通过 `127.0.0.1:27027` 接入 Docker `fq_mongodb`；宿主机链路不要再使用 `127.0.0.1:27017`。
- `fqnext-supervisord` 宿主机底座与其托管的交易/运行链 Python 进程。
- Guardian monitor。
- XT account sync worker（作为 XT 账户数据的增量补偿同步入口，默认每 15 秒轮询 `assets / credit_detail / positions / orders / trades`；其中 `credit_detail` 保持高频刷新以驱动仓位管理状态，只把新增 `orders / trades` 送入 ingest；`credit_subjects` 只在启动和每日计划时间做低频同步，并在启动时做一次单标的实时仓位 fallback 种子刷新；若 `positions` 快照为空或严重缩水、但同轮 `credit_detail.market_value` 仍显著为正，则该轮快照会进入 quarantine，不覆盖 `xt_positions`，也不触发自动平账；这个 quarantine 现在也覆盖小账户单票/双票严重缩水的场景，同时 worker 会记录 warning 说明 quarantine 原因）。
- TPSL tick listener。
- 需要直接访问券商、终端、`TDX_HOME` 或 Windows 本地目录的组件。

当前运行面还有两条与订单对账相关的固定语义：

- `ExternalOrderReconcileService` 对 buy gap 会同时记录 `initial/latest/chosen` 三组价格快照；运行面和排障口径里若看到 `chosen_price_policy=freeze_initial`，表示最终确认价按首次发现快照冻结，而不是跟随长时间观测漂移。
- Guardian 遇到“持仓 entry 已确认但 arranged fills 不可用”的场景时，当前会显式区分 `arrangement_degraded` 与 `entry_without_slices`；这两种情况默认保守跳过，不再误记成“无持仓”。

### Docker 并行环境承担

- MongoDB：宿主机 `27027 ->` 容器内 `27017`
- Redis：`6380 -> 6379`
- ClickHouse HTTP：`18123 -> 8123`
- ClickHouse native：`19000 -> 9000`
- API Server：`15000 -> 5000`
- TDXHQ：`15001 -> 5001`
- Dagster Webserver：`11003 -> 10003`
- QAWebServer：`18010 -> 8010`
- Web UI：`18080 -> 80`
- Runtime indexer：`fq_runtime_indexer`
- TradingAgents backend：`13000 -> 8000`
- TradingAgents frontend：`13080 -> 80`

对应编排文件是 `docker/compose.parallel.yaml`。

## 当前正式入口

- 自由会话硬入口：`codex_run/start_codex_cli.bat`、`codex_run/start_codex_app_server.bat`
- 自由会话 bootstrap：`runtime/memory/scripts/bootstrap_freshquant_memory.py`
- 共享部署计划脚本：`script/freshquant_deploy_plan.py`
- deploy 后运维面检查脚本：`script/check_freshquant_runtime_post_deploy.ps1`
- 宿主机运行时控制脚本：`script/fqnext_host_runtime_ctl.ps1`
- 仓库级本地预检正式入口：`script/fq_local_preflight.ps1`
- 本地开 PR 的正式入口：`script/fq_open_pr.ps1`
- 仓库 `git push` 会通过 `.githooks/pre-push` 调用本地预检；首次接入或 hook 丢失时，用 `script/install_repo_hooks.ps1` 恢复 `core.hooksPath`
- 当前本地预检会缓存 docs guard / pre-commit / pytest / review-thread 检查结果；当前分支已有关联 PR 且 `gh` 已登录时，会直接阻断 unresolved review threads
- 当前本地预检命中 `morningglory/fqwebui/**`、`.github/workflows/ci.yml` 或 `script/fq_local_preflight.ps1` 变更时，会额外执行 `npm run lint`、`npm run test:browser-smoke`、`npm run test:unit`、`npm run build`
- FQNext 宿主机 Supervisor service：`fqnext-supervisord`
- Supervisor XML-RPC 入口：`http://127.0.0.1:10011/RPC2`
- formal deploy 状态根目录：`D:/fqpack/runtime/formal-deploy`
- memory context pack 产物根目录：`D:/fqpack/runtime/artifacts/memory/context-packs`
- 冷记忆目录：`.codex/memory`
- 热记忆 Mongo database：`fq_memory`

## 会话与记忆口径

- memory refresh 会先同步远程 `origin/main`，再从该 ref 的 `.codex/memory/**` 与 `docs/current/modules/*.md` 汇总开发参考记忆。
- 会话通过环境变量 `FQ_MEMORY_CONTEXT_PATH` 注入本轮 context pack，并通过 `FQ_MEMORY_CONTEXT_ROLE` 暴露当前角色。
- 若当前会话没有现成 `FQ_MEMORY_CONTEXT_PATH`，应先执行 `bootstrap_freshquant_memory.py` 再继续仓库探索。
- 自由会话启动 `codex app-server` 时默认走 `stdio://`；没有客户端接入前可以保持静默。
- 关闭 `start_codex_app_server.bat` 的窗口，或在窗口里按 `Ctrl+C`，都会停止当前 `codex app-server`。
- memory context 只作为启动辅助信息，不能覆盖 GitHub、`docs/current/**` 或实际 deploy 证据。

## 开发与发布工作流

- 默认工作流是 `local session -> feature branch -> PR -> merge remote main -> deploy`。
- 轻量更新允许直接走 `feature branch -> PR`。
- 高影响、破坏性变更应先建 GitHub Issue。
- 本地会话只负责开发、测试和预检查，不是正式 deploy 真值。
- 正式 deploy 只允许基于最新远程 `main` 已合并 SHA。
- 命中宿主机 deployment surface 时，正式入口固定为 `script/fqnext_host_runtime_ctl.ps1`。

## 最小可用运行面

当目标是调试主交易链时，至少需要：

- MongoDB
- Redis
- API Server
- XTData producer
- XTData consumer
- Guardian monitor
- XT account sync worker
- Order submit / broker / XT 回报 ingest
- TPSL worker（如果验证退出逻辑）

当目标是调试前端展示时，至少还需要：

- Web UI
- Gantt/Shouban30 对应读模型数据
- Runtime Observability 原始日志目录

## Runtime Observability 页面口径

- `/runtime-observability` 主视图固定拆成 `全局 Trace` 与 `组件 Event` 两个视角。
- 顶部 `异常链路` 只过滤中间 Trace 列表，不过滤右侧已选 Trace 的完整步骤明细。
- 顶部 `异常节点` 与工具栏 `仅异常` 用于过滤当前右侧步骤/事件明细；查看异常 Trace 时，默认仍可回看完整链路步骤。
- 左侧组件卡片点击后默认进入该组件的完整 `Event` 视图；卡片上的 `异常节点` 按钮才进入该组件的仅异常 Event 视图。
- `broker_gateway` 的健康卡片不只依赖 XtQuant callback；broker 主循环在 `connect()/subscribe()` 成功后也会立刻补一条 `heartbeat connected=1`，避免页面长期停留在旧的重试告警。
- 右侧 Trace 摘要里的 `异常阶段` 列出当前单条 Trace 的异常节点列表。
- 左侧组件卡片里的 `异常节点 N` 是当前选定时间范围内该组件异常 Event 的聚合计数，不等于单条 Trace 的异常节点数。
- 右侧步骤详情区在桌面宽度和浏览器默认 `100%` 缩放下由详情面板自身承接纵向滚动；内容超出可视高度时应出现内部滚动条，不能依赖浏览器缩放才能看全。
- `当前过滤条件下没有节点` 只在当前步骤过滤结果实际为空时显示；若当前 Trace 仍有可见步骤，该提示不应额外占用大块空白区域。

## 并行环境的默认口径

- 宿主机 `.env` 示例：`deployment/examples/envs.fqnext.example`
- 宿主机 `.env` 示例默认不再携带 `ALL_PROXY`、`HTTP_PROXY`、`HTTPS_PROXY`、`NO_PROXY` 及其小写变量
- Docker API 使用 `FQ_COMPOSE_ENV_FILE` 指向主工作树 `.env`
- GHCR 预构建镜像仅用于加速 Docker 部署，不改变运行真值；实际运行真值仍来自当前 `main`、deploy 结果与 health/runtime ops evidence
- `deploy-production.yml` 在正式 Windows self-hosted runner 上把 deploy state / logs 固化到 `formal-deploy` artifacts 目录，但正式 deploy 真值已经改为本机 mirror，不再依赖下载部署归档或把 Docker Images 作为前置。
- `deploy-production.yml` 不走 `actions/checkout`，而是先把 `D:\fqpack\freshquant-2026.2.23\.worktrees\production-deploy-bootstrap` 这个 bootstrap worktree reset 到目标 SHA，再直接调用那里的 `script/ci/run_production_deploy.ps1`；随后该脚本继续确保 `D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production` 这个本机 deploy mirror worktree 存在并 fast-forward 到目标 SHA。
- bootstrap entrypoint 在 mirror sync 阶段会从当前 entrypoint repo 解析 `sync_local_deploy_mirror.py`，避免 stale `main-deploy-production` 工作树里的旧 helper 把 `.venv\` 清理逻辑回退到 `git clean -ffdX`。
- 如果 live host runtime 仍在占用 `.venv\Lib\site-packages` 里的二进制扩展，正式入口会先 quiesce 宿主机 surfaces、重试 `uv sync`，再统一拉起这些 surfaces；这样 deploy 不会在 `.pyd` / `.dll` rename 阶段直接中断。
- 如果 `D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production\.venv\pyvenv.cfg` 缺失，或保留下来的 `.venv\Scripts\python.exe` 已经不能正常启动，正式入口会把该 mirror `.venv\` 视为损坏状态：先 quiesce 宿主机 surfaces，再用 runner Python 3.12 重建 `.venv` metadata 并重新执行 `uv sync --frozen`，然后才允许进入 formal deploy。
- 正式 production runner 宿主机必须至少存在一个可用的 Python 3.12；如果 `py -3.12` 因旧注册漂移失效，正式入口会回退到已注册的 per-user / system Python 3.12，并回补当前用户 `PythonCore\3.12` 注册。
- 若 runner Python 3.12 里缺少 `uv` 模块，正式入口会先自愈 `python -m uv`，再继续 deploy。
- 正式 deploy 固定导出 `FQ_DOCKER_FORCE_LOCAL_BUILD=1`，确保 mirror 上的 Docker 镜像来自本机构建而不是 GHCR pull。
- 对已经有 `last_success_sha` 的增量正式 deploy，`run_formal_deploy.py` 现在直接在 mirror 的 `.git` 工作树里计算 `last_success_sha..HEAD` changed paths，不再依赖 compare API 作为正式路径。
- mirror 同步完成后，正式入口会先用 runner Python 3.12 在 `D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production` 执行 `python -m uv sync --frozen`，再切到 mirror `.venv\Scripts\python.exe` 调用 `run_formal_deploy.py`。
- formal deploy 命中宿主机 deployment surface 时，会通过 `script/fqnext_supervisor_config.py` 把 `D:\fqpack\config\supervisord.fqnext.conf` 收敛到 `main-deploy-production`，并在配置发生变化或 service 仍吃旧配置时先重载一次 `fqnext-supervisord`。
- 当前宿主机正式 Supervisor program 解释器与 `PYTHONPATH` 真值都固定落在 `D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production`；若运行面 traceback 指到 `.venv\Lib\site-packages\fqxtrade\...`，应视为 deploy/runtime truth 失配。
- `restart-surfaces` 当前以最终 settled state 为准；中途若出现一次 `Exited/Fatal/Backoff/Starting` 的瞬时启动错误，但最终 supervisor 已收敛回 `RUNNING`，运行面不再把这类 program 继续判成重启失败。
- 该 workflow 中的 PowerShell steps 固定带 `-ExecutionPolicy Bypass`，避免 self-hosted Windows runner 的本机执行策略在 step 启动前拦截临时脚本
- 该 workflow 也会显式设置 `$ErrorActionPreference = 'Stop'`，确保 PowerShell cmdlet 的 non-terminating error 仍然按 fail-fast 方式中断正式 deploy
- `script/docker_parallel_compose.ps1` 会优先读取 `FQ_DOCKER_BUILD_CACHE_ROOT`；未显式设置时，Docker BuildKit 本地缓存默认落到仓库 `.artifacts/docker-build-cache`
- 宿主机 FreshQuant / FQXTrade / vendored QUANTAXIS 默认统一解析到 `127.0.0.1:27027`
- Docker 容器内部 Mongo 继续使用服务名 `fq_mongodb:27017`
- Docker 容器内部 Redis 继续使用服务名 `fq_redis:6379`
- `docker/compose.parallel.yaml` 会为核心容器显式注入 `FRESHQUANT_MONGODB__HOST=fq_mongodb`、`FRESHQUANT_MONGODB__PORT=27017`、`FRESHQUANT_REDIS__HOST=fq_redis` 与 `FRESHQUANT_REDIS__PORT=6379`
- `docker/compose.parallel.yaml` 只要变更，正式 deploy plan 就按全量受管 Docker 并行环境容器重建/重启处理，避免 merge 后漏掉运行时配置更新。
- Web UI 默认访问并行 API `http://127.0.0.1:15000`

### 跑本地预检并开 PR

```powershell
powershell -ExecutionPolicy Bypass -File script/fq_local_preflight.ps1 -Mode Ensure
powershell -ExecutionPolicy Bypass -File script/fq_open_pr.ps1 -- --fill
```

### 按变更面执行 selective deploy

```powershell
powershell -ExecutionPolicy Bypass -File script/fq_apply_deploy_plan.ps1 -FromGitDiff origin/main...HEAD
```

## 当前阶段的运行风险

- Docker 里的 Mongo/Redis 与宿主机 broker/xtdata 之间必须通过宿主机端口对齐，否则交易链会出现“页面正常、worker 无数据”。
- 如果宿主机仍靠 `frequant-next.bat` 手工拉起，而不是 `fqnext-supervisord` service 开机自启，就会失去稳定的正式入口与权限边界。
- 如果 `D:\fqpack\config\supervisord.fqnext.conf` 仍指向 `main-runtime`、空目录或 `.venv\Lib\site-packages\fqxtrade`，formal deploy/runtime verify 现在应直接判为异常，而不是继续假设线上跑的是最新代码。
- 如果宿主机进程仍报 `127.0.0.1:27017`，优先检查进程环境是否缺少 `FRESHQUANT_MONGODB__HOST/PORT`。
