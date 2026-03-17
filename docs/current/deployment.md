# 当前部署

## 部署原则

- 代码改动后，受影响模块必须重新部署；只合并不部署不算完成。
- Docker 并行环境用于承载通用服务与前端；宿主机负责需要直连券商、XTData 或 Windows 资源的进程。
- FreshQuant / QUANTAXIS 相关 Docker 服务在 `docker/compose.parallel.yaml` 内部固定使用 `fq_mongodb:27017`；不要只覆写 host 而保留宿主机默认 `27027`
- 仓库根目录 legacy 批处理部署脚本 `deploy.bat` / `deploy_rear.bat` 已移除；当前只保留 `docker compose` + `script/fqnext_host_runtime_ctl.ps1` 这套正式入口。
- Docker 侧正式入口优先使用 `powershell -ExecutionPolicy Bypass -File script/docker_parallel_compose.ps1 ...`；该脚本会自动解析主工作树 `.env` / runtime log 目录、注入当前 `HEAD` 到镜像 label、开启 BuildKit，并优先拉取 GHCR 中与当前 commit 匹配的预构建镜像；若远端镜像不可用，再保守回退到本机构建。
- `.github/workflows/docker-images.yml` 在 `main` push 后会先解析受影响镜像；只有改到的服务真正 build，未改到的服务只把现有 `:main` digest retag 成当前 commit SHA，保持 registry-first deploy 命中。
- `.github/workflows/deploy-production.yml` 会在 `Docker Images` 成功后自动触发，并在 `[self-hosted, windows, production]` runner 上执行 `py -3.12 script/ci/run_formal_deploy.py` 完成正式环境 deploy。
- `deploy-production.yml` 在真正执行正式 deploy 前，会通过 GitHub API 再次校验 `github.event.workflow_run.head_sha` 是否仍然是当前 `main` tip；对历史成功 workflow 的 rerun 会直接拒绝，避免把正式环境误回滚到旧 commit。
- `deploy-production.yml` 不依赖 `actions/checkout`；它会在 Windows runner 上用 PowerShell 直接下载目标 SHA 的源码归档并展开到 `GITHUB_WORKSPACE`，绕开该宿主机上 `git/libcurl` 对 GitHub 的不稳定 fetch 链路。
- 由于 zipball 工作区没有 `.git`，`script/ci/run_formal_deploy.py` 在增量 deploy 场景会改用 GitHub compare API 计算 `last_success_sha -> current main` 的 changed paths，而不是依赖本地 `git diff`。
- `deploy-production.yml` 中仓库自定义的 PowerShell step 固定使用 `-NoProfile -ExecutionPolicy Bypass -File {0}`；正式 self-hosted runner 即使本机 PowerShell policy 更严格，也不会在 step 启动前被策略拦截。
- 这里的约束是“只允许部署当前 main tip”，不是“任意一次成功的 main workflow 都可重复 deploy”。
- `fq_webui` 构建上下文固定为 `morningglory/fqwebui`，并使用子目录 `.dockerignore` 排除 `node_modules` / `web` 等构建噪音；rear 镜像继续使用仓库根上下文，但通过根 `.dockerignore` 和分层 `uv sync` 缓存降低重建成本。
- `api`、`dagster`、`qa` 当前共享同一套 rear 镜像；命中这些部署面时，部署计划会先刷新 shared rear image，再启动受影响容器，避免 `dagster` / `qa` 单独重启时继续吃旧镜像。
- `Merging` 只负责 merge 与 handoff；merge 后由单个全局 Codex 自动化统一判断 deploy、health check、runtime ops check 和 cleanup。
- 部署动作结束后必须先做接口层健康检查，再做 deploy 后运维面检查；两者都通过后才进入 cleanup。
- `Global Stewardship` 的实际收口链路固定为：`deploy -> health check -> runtime ops check -> cleanup`。
- 当前 Done 判定固定为：`merge + ci + docs sync + deploy + health check + cleanup`。
- 当前 `health check` 的执行口径包含接口层检查；如果本轮实际发生 deploy，还必须追加一轮 deploy 后 `runtime ops check`。
- 正式收口前先用 `py -3.12 script/freshquant_deploy_plan.py` 生成部署计划；不要在会话内临场重新推理 Docker / 宿主机边界。
- 自动正式部署的状态文件固定为 `D:\fqpack\runtime\symphony-service\artifacts\formal-deploy\production-state.json`；会记录上一次成功部署的 commit、最近一次尝试时间与最近一次部署 surfaces。
- 自动正式部署每次都会把 artifacts 写到 `D:\fqpack\runtime\symphony-service\artifacts\formal-deploy\runs\<timestamp>-<sha>\`，包含 plan、命令日志与 runtime baseline/verify 输出。

## 常用部署命令

### 全量并行环境

```powershell
powershell -ExecutionPolicy Bypass -File script/docker_parallel_compose.ps1 up -d --build
```

- `main` 合并后的镜像预构建 workflow：`.github/workflows/docker-images.yml`
- `main` 合并后的正式自动部署 workflow：`.github/workflows/deploy-production.yml`
- 默认镜像发布位置：`GHCR`
- 正式收口时优先拉取 registry 中与当前 commit 匹配的镜像；只有不命中或拉取失败时，才会本机构建

### 自动正式部署

- `deploy-production.yml` 由 `Docker Images` 成功事件触发，不需要额外审批。
- `script/ci/run_formal_deploy.py` 会读取 `production-state.json` 中的上一次成功部署 SHA，计算 `last_success_sha -> current main HEAD` 的 changed paths，再调用 `script/freshquant_deploy_plan.py` 得到本轮 deploy plan。
- 如果触发事件里的 SHA 已经不是当前 `main` tip，`deploy-production.yml` 会直接失败，不会对历史成功 run 继续 deploy。
- workflow 本身会通过 GitHub API 校验 `main` tip，并通过 `zipball/<sha>` 下载目标版本源码；正式 deploy 不再依赖 runner 本地 `git fetch/checkout` 成功。
- 如果工作区来自 zipball 而没有 `.git`，`run_formal_deploy.py` 会使用 `GH_TOKEN + github.repository` 调 compare API 生成增量 changed paths。
- 如果 `production-state.json` 尚不存在，首次会按 bootstrap 模式执行全量 surface deploy；成功后才写入初始状态。
- 如果本轮 diff 不命中任何 deployment surface，workflow 仍会推进 `production-state.json` 到当前 commit，但不会执行 deploy / health check / runtime ops check。
- 失败时只更新最近一次 attempt，不自动回滚，也不会推进 `last_success_sha`。

### 共享部署计划解析

```powershell
py -3.12 script/freshquant_deploy_plan.py --changed-path freshquant/rear/api_server.py --changed-path morningglory/fqwebui/src/views/GanttUnified.vue --format summary
```

### 只重建 API / Web

```powershell
powershell -ExecutionPolicy Bypass -File script/docker_parallel_compose.ps1 up -d --build fq_apiserver fq_webui
```

### 只重建 TradingAgents

```powershell
powershell -ExecutionPolicy Bypass -File script/docker_parallel_compose.ps1 up -d --build ta_backend ta_frontend
```

### 宿主机重装正式 Symphony

```powershell
powershell -ExecutionPolicy Bypass -File runtime/symphony/scripts/activate_github_first_formal_service.ps1
```

### 宿主机仅同步并重载 Symphony

首次安装按需管理员桥接任务：

```powershell
powershell -ExecutionPolicy Bypass -File runtime/symphony/scripts/install_freshquant_symphony_restart_task.ps1
```

- 该脚本会先把当前 `runtime/symphony/**` 同步到 `D:\fqpack\runtime\symphony-service`，再注册计划任务
- 安装时会给执行安装的 Windows 用户追加该任务的读取/执行权限，供后续普通会话调用 `invoke_freshquant_symphony_restart_task.ps1`

后续普通会话更新 `runtime/symphony/**` 时：

```powershell
powershell -ExecutionPolicy Bypass -File runtime/symphony/scripts/sync_freshquant_symphony_service.ps1
powershell -ExecutionPolicy Bypass -File runtime/symphony/scripts/invoke_freshquant_symphony_restart_task.ps1
```

- 默认计划任务名：`fq-symphony-orchestrator-restart`
- 默认状态文件：`D:\fqpack\runtime\symphony-service\artifacts\admin-bridge\restart-status.json`
- 重载任务会在服务进入 `Running` 后继续轮询 `http://127.0.0.1:40123/api/v1/state`，只有状态文件记录 `success=true` 且 `health_status_code=200` 才算桥接成功
- 如果计划任务尚未安装，或需要重装正式服务本体，仍使用 `reinstall_freshquant_symphony_service.ps1` / 激活脚本并在提升权限 PowerShell 中执行

### 宿主机同步 Python 依赖

```powershell
.\install.bat --skip-web
```

- `install.bat` 会先清理 `morningglory/fqchan01/python/build`，再在 `uv sync --frozen` 阶段对本地原生包 `fqchan01` 强制执行 `refresh + reinstall`，避免宿主机继续复用损坏的 `fqchan01` 源码构建产物或缓存。
- 如果部署目标包含 Guardian / Chanlun 相关宿主机链路，重装后应额外执行 `python -c "import fqchan01; print('IMPORT_OK')"` 做一次本地导入确认。
- 正式运行面默认无代理；`D:/fqpack/config/envs.conf` 应显式清空 `ALL_PROXY`、`HTTP_PROXY`、`HTTPS_PROXY`、`NO_PROXY` 及其小写变量，`TradingAgents-CN` 后端启动时也会再次清理这些变量。

### 宿主机 Supervisor 底座安装

```powershell
powershell -ExecutionPolicy Bypass -File script/install_fqnext_supervisord_service.ps1
powershell -ExecutionPolicy Bypass -File script/install_fqnext_supervisord_restart_task.ps1
```

- 正式宿主机底座 service 名称：`fqnext-supervisord`
- 管理员桥接任务名：`fqnext-supervisord-restart`
- 管理员桥接任务 runner 会复制到稳定宿主机路径：`D:\fqpack\supervisord\scripts\run_fqnext_supervisord_restart_task.ps1`
- `D:\fqpack\supervisord\frequant-next.bat` 仅保留为兼容人工入口，不再作为 `Global Stewardship` 正式入口

## 模块部署矩阵

| 变更路径 | 需要部署的模块 | 最低动作 |
| --- | --- | --- |
| `freshquant/rear/**` | API Server | 重建 `fq_apiserver` 容器或重启 API 进程 |
| `freshquant/order_management/**` | 订单管理、API、broker/ingest 相关宿主机进程 | 重建 API；执行 `powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode EnsureServiceAndRestartSurfaces -DeploymentSurface order_management -BridgeIfServiceUnavailable` |
| `freshquant/position_management/**` | 仓位管理 | 执行 `powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode EnsureServiceAndRestartSurfaces -DeploymentSurface position_management -BridgeIfServiceUnavailable` |
| `freshquant/tpsl/**` | TPSL | 执行 `powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode EnsureServiceAndRestartSurfaces -DeploymentSurface tpsl -BridgeIfServiceUnavailable` |
| `freshquant/market_data/**` | XTData producer / consumer | 执行 `powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode EnsureServiceAndRestartSurfaces -DeploymentSurface market_data -BridgeIfServiceUnavailable`；必要时重新 prewarm |
| `freshquant/__init__.py` / `freshquant/runtime/network.py` | API、Dagster、全部 FreshQuant 宿主机运行面 | 重建 `fq_apiserver`；重启 Dagster；执行 `powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode EnsureServiceAndRestartSurfaces -DeploymentSurface market_data,guardian,position_management,tpsl,order_management -BridgeIfServiceUnavailable` |
| `freshquant/message/**` | XTData consumer / Guardian 通知链 | 执行 `powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode EnsureServiceAndRestartSurfaces -DeploymentSurface market_data,guardian -BridgeIfServiceUnavailable` |
| `freshquant/trading/**` | API、Dagster、XTData / Guardian 交易日历链 | 重建 `fq_apiserver`；重启 Dagster；执行 `powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode EnsureServiceAndRestartSurfaces -DeploymentSurface market_data,guardian -BridgeIfServiceUnavailable` |
| `freshquant/config.py` / `freshquant/freshquant.yaml` | Dagster、XTData、Guardian 共享旧配置链 | 重启 Dagster；执行 `powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode EnsureServiceAndRestartSurfaces -DeploymentSurface market_data,guardian -BridgeIfServiceUnavailable` |
| `freshquant/strategy/**` 或 `freshquant/signal/**` | Guardian | 执行 `powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode EnsureServiceAndRestartSurfaces -DeploymentSurface guardian -BridgeIfServiceUnavailable` |
| `sunflower/QUANTAXIS/**` | QAWebServer 与依赖 QUANTAXIS 的宿主机策略链路 | 重建 `fq_qawebserver`；同步重启受影响宿主机 Guardian / strategy 进程 |
| `freshquant/data/gantt*` / `freshquant/shouban30_pool_service.py` | Gantt/Shouban30 读模型与 API | 重建 API；必要时重跑 Dagster 任务 |
| `morningglory/fqwebui/**` | Web UI | 重建 `fq_webui` |
| `morningglory/fqdagster/**` / `morningglory/fqdagsterconfig/**` | Dagster | 重启 `fq_dagster_webserver` 与 `fq_dagster_daemon` |
| `morningglory/fqxtrade/fqxtrade/**` | broker / ingest 等 vendored 订单链 | 执行 `powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode EnsureServiceAndRestartSurfaces -DeploymentSurface order_management -BridgeIfServiceUnavailable` |
| `third_party/tradingagents-cn/**` | TradingAgents-CN | 重建 `ta_backend` 与 `ta_frontend`；后端运行时默认直连，不再继承任何 `*_PROXY` / `*_proxy` 环境变量 |
| `runtime/symphony/**` | 正式 orchestrator | 已预装计划任务时执行 `sync_freshquant_symphony_service.ps1` + `invoke_freshquant_symphony_restart_task.ps1`；否则使用 `reinstall_freshquant_symphony_service.ps1` 或激活脚本 |

## 健康检查

统一使用正式入口：

```powershell
py -3.12 script/freshquant_health_check.py --surface api --format summary
py -3.12 script/freshquant_health_check.py --surface web --format summary
py -3.12 script/freshquant_health_check.py --surface tradingagents --format summary
py -3.12 script/freshquant_health_check.py --surface symphony --format summary
```

- 脚本固定禁用系统代理；当前会显式忽略 `ALL_PROXY`、`HTTP_PROXY`、`HTTPS_PROXY`、`NO_PROXY` 及其小写变量
- 默认串行检查并带重试，避免 Windows 本机短连接探针造成假阴性
- 如需补充特定地址，可追加 `--url http://127.0.0.1:18080/runtime-observability`

### API

```powershell
py -3.12 script/freshquant_health_check.py --surface api --format summary
```

### Web UI

```powershell
py -3.12 script/freshquant_health_check.py --surface web --format summary
```

### TradingAgents

```powershell
py -3.12 script/freshquant_health_check.py --surface tradingagents --format summary
```

### Symphony

```powershell
py -3.12 script/freshquant_health_check.py --surface symphony --format summary
```

### Deploy 后运维面检查

本轮有实际 deploy 时，必须先采 baseline，再在接口健康检查通过后执行 verify：

```powershell
powershell -ExecutionPolicy Bypass -File runtime/symphony/scripts/check_freshquant_runtime_post_deploy.ps1 -Mode CaptureBaseline -OutputPath <baseline.json>
powershell -ExecutionPolicy Bypass -File runtime/symphony/scripts/check_freshquant_runtime_post_deploy.ps1 -Mode Verify -BaselinePath <baseline.json> -OutputPath <verify.json> -DeploymentSurface api,market_data
```

- `DeploymentSurface` 取值固定为：`api`、`web`、`dagster`、`qa`、`tradingagents`、`symphony`、`market_data`、`guardian`、`position_management`、`tpsl`、`order_management`；未知值会直接报错，不会静默跳过检查
- `script/fqnext_host_runtime_ctl.ps1` 支持逗号分隔的多 surface 形式，例如 `-DeploymentSurface market_data,guardian`
- 输出 JSON 至少包含：`baseline`、`docker_checks`、`service_checks`、`process_checks`、`warnings`、`failures`、`passed`
- 固定检查基础容器：`fq_mongodb`、`fq_redis`
- 按本轮部署面追加检查容器：`fq_apiserver`、`fq_webui`、`fq_dagster_webserver`、`fq_dagster_daemon`、`fq_qawebserver`、`ta_backend`、`ta_frontend`
- 运维面检查会自动把 compose project 前缀后的容器名（例如 `fqnext_20260223-fq_apiserver-1`）归一化回正式服务名
- 固定记录宿主机服务：`fq-symphony-orchestrator`、`fqnext-supervisord`；只有命中对应宿主机部署面时，`Running` 才是 deploy 通过前提
- 关键进程语义固定为：deploy 前已运行的不能在 deploy 后消失；本轮明确要求恢复的必须恢复；deploy 前本来就没运行且本轮未涉及的只记 warning
- 脚本支持 `-DockerSnapshotPath`、`-ServiceSnapshotPath`、`-ProcessSnapshotPath`，供手工回放或测试复现使用

### 运维面辅助命令

```powershell
powershell -ExecutionPolicy Bypass -File script/docker_parallel_compose.ps1 ps
Get-Service fq-symphony-orchestrator
Get-Service fqnext-supervisord
powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode Status
```

## 部署后必须确认的事实

- API 蓝图能返回，不是只监听端口。
- Web UI 页面不是空白页，关键页面 `/gantt`、`/gantt/shouban30`、`/position-management`、`/tpsl`、`/runtime-observability` 能打开。
- 如果本轮改了 Shouban30 工作区或 `sync-to-tdx` 语义，确认 `fq_apiserver` 已挂载 `${FQPACK_TDX_SYNC_DIR:-D:/tdx_biduan}`，并实测 `D:\tdx_biduan\T0002\blocknew\30RYZT.blk` 被更新。
- XTData 相关修改后，producer/consumer 日志持续产出，Redis 队列不持续堆积。
- 如果改了运行观测或 XTData runtime 埋点，确认 `/runtime-observability` 页面能看到 `xt_producer` / `xt_consumer` 的 5 分钟 heartbeat 与关键指标，而不是只看到启动事件。
- TPSL / Position worker 修改后，进程没有“启动即退”。
- 宿主机 deployment surface 修改后，`fqnext-supervisord` 保持 `Running`，且 `script/fqnext_host_runtime_ctl.ps1 -Mode Status` 能返回目标 program 为 `RUNNING`。
- Symphony 修改后，`Merging -> Global Stewardship` handoff、批量 deploy 判定和 follow-up issue only 规则仍然可用。
- 如果本轮有实际 deploy，`check_freshquant_runtime_post_deploy.ps1` 的 verify 结果必须 `passed=true`，且 `failures` 为空。
- 如果通过计划任务桥接重载 Symphony，还要确认 `artifacts\admin-bridge\restart-status.json` 记录 `success=true` 且 `health_status_code=200`。

## Global Stewardship 收口规则

- merge 后原 issue 进入 `Global Stewardship`，不直接 `Done`。
- 单个全局 Codex 自动化按当前 `main` 和部署面并集统一决定是否批量 deploy，并先用 `script/freshquant_deploy_plan.py` 计算本轮 Docker / 宿主机动作。
- 当前自动化入口是 `.github/workflows/deploy-production.yml`；它在正式 Windows self-hosted runner 上调用 `script/ci/run_formal_deploy.py`，不再依赖 merge 会话手工触发 deploy。
- Docker deploy 一律优先走 `script/docker_parallel_compose.ps1`，不要在正式收口链路里临时手拼 `FQ_COMPOSE_ENV_FILE` 或绕开 smart-build / git SHA label 注入。
- 若 GHCR 中已存在与当前 commit 匹配的预构建镜像，正式 deploy 应优先走 `pull + up -d --no-build`；只有不命中时才回退本机构建。
- 本轮没有实际 deploy 时，不执行 runtime ops check。
- 本轮有实际 deploy 时，必须先 `CaptureBaseline`，再在 health check 后执行 `Verify`。
- 命中宿主机 deployment surface 时，统一通过 `script/fqnext_host_runtime_ctl.ps1` 控制 `fqnext-supervisord`，不要再直接依赖 `.bat` 或手工找进程。
- 只有 health check 与 runtime ops check 都通过，才允许 cleanup / close 原 issue。
- runtime ops check 失败时，不做 cleanup，不关闭原 issue；代码问题只创建或复用 follow-up issue，外部环境问题则记录 blocker / clear condition / evidence / target recovery state。
- 如果发现需要代码修复的问题，只创建 follow-up issue，由下一轮 `Symphony` 接手。
- 原 issue 只有在其变更已包含在一次成功发布中，且 health check、runtime ops check 与 cleanup 完成后，才允许关闭。

## Cleanup 要求

- cleanup 由 `Global Stewardship` 执行，不再由 `Merging` 会话直接收口。
- 删除已合并远端 feature branch。
- 删除当前 issue 的 Symphony workspace 或本次临时 worktree。
- 清理临时脚本、临时 compose override、过期 artifacts。
- 如果原 issue 仍被 open follow-up issue 阻塞，则暂不关闭原 issue。
- 不清理 Mongo、Redis、`.venv`、正式日志目录或在线服务。
