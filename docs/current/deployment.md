# 当前部署

## 部署原则

- 代码改动后，受影响模块必须重新部署；只合并不部署不算完成。
- Docker 并行环境用于承载通用服务与前端；宿主机负责需要直连券商、XTData 或 Windows 资源的进程。
- FreshQuant / QUANTAXIS 相关 Docker 服务在 `docker/compose.parallel.yaml` 内部固定使用 `fq_mongodb:27017`；不要只覆写 host 而保留宿主机默认 `27027`
- 仓库根目录 legacy 批处理部署脚本 `deploy.bat` / `deploy_rear.bat` 已移除；当前只保留 `docker compose` + `script/fqnext_host_runtime_ctl.ps1` 这套正式入口。
- Docker 侧正式入口优先使用 `powershell -ExecutionPolicy Bypass -File script/docker_parallel_compose.ps1 ...`；该脚本会自动解析主工作树 `.env` / runtime log 目录、注入当前 `HEAD` 到镜像 label、开启 BuildKit。当前默认只使用本地缓存 / 本机构建；只有显式设置 `FQ_ENABLE_REMOTE_CACHE_PULL=1` 时，才允许回到 GHCR 远端缓存 pull 路径。正式自动 deploy 会额外设置 `FQ_DOCKER_FORCE_LOCAL_BUILD=1`，强制 production 机基于本机 deploy mirror 本地构建。
- `.github/workflows/docker-images.yml` 仍会在 `main` push 后发布镜像到 GHCR，但它不再是正式 deploy 的前置条件；正式 deploy 真值改为本机 deploy mirror。
- `.github/workflows/deploy-production.yml` 当前由 `push main` 直接触发，并在 `[self-hosted, windows, production]` runner 上执行。
- 正式 deploy mirror 固定目录是 `D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production`；该目录使用专用本地分支 `deploy-production-main` fast-forward 到远程 `main`，再由正式 workflow 从这个目录构建和部署。
- `D:\fqpack\freshquant-2026.2.23` 现在只作为 canonical repo root，用于管理/创建正式 mirror worktree；它不再被视为正式构建工作区。
- 该 workflow 依赖正式 Windows runner 宿主机已安装的 Python 3.12 与 uv；也就是说 production runner 上必须已经有“宿主机已安装的 uv”，不再在线执行 `pip install uv` 或下载源码归档。
- `deploy-production.yml` 在真正执行正式 deploy 前，会通过 GitHub API 再次校验 `${{ github.sha }}` 是否仍然是当前 main tip；对已经过时的 push 事件会直接拒绝。
- `deploy-production.yml` 不再下载 `zipball/<sha>`，也不依赖 `actions/checkout`；它会先确保 `D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production` 这个本机 deploy mirror worktree 存在，再把它 fast-forward 到目标 SHA，然后在该目录下执行 `uv sync` 和 `run_formal_deploy.py`。
- production runner service 用户与仓库目录 owner 不一致时，workflow 会先为 canonical repo root 和 mirror root 显式配置 `git safe.directory`，避免 self-hosted Windows service 因 dubious ownership 拒绝执行 git。
- 自动正式部署的状态文件固定为 `D:\fqpack\runtime\symphony-service\artifacts\formal-deploy\production-state.json`；会记录上一次成功部署的 commit、最近一次尝试时间与最近一次部署 surfaces。
- `Merging` 只负责 merge 与 handoff；merge 后由单个全局 Codex 自动化统一判断 deploy、health check、runtime ops check 和 cleanup。
- 部署动作结束后必须先做接口层健康检查，再做 deploy 后运维面检查；两者都通过后才进入 cleanup。
- `Global Stewardship` 的实际收口链路固定为：`deploy -> health check -> runtime ops check -> cleanup`。
- 当前 Done 判定固定为：`merge + ci + docs sync + deploy + health check + cleanup`。
- 当前 `health check` 的执行口径包含接口层检查；如果本轮实际发生 deploy，还必须追加一轮 deploy 后 `runtime ops check`。
- 正式收口前先用 `py -3.12 script/freshquant_deploy_plan.py` 生成部署计划；不要在会话内临场重新推理 Docker / 宿主机边界。
- 正式执行部署时，优先通过 `powershell -ExecutionPolicy Bypass -File script/fq_apply_deploy_plan.ps1` 消费共享部署计划；不要把 Docker 与宿主机动作拆成临时命令。
- `script/fq_apply_deploy_plan.ps1` 当前会为每次正式 deploy 记录阶段状态文件，分阶段收口 `baseline -> docker -> host -> health -> verify`；任一阶段失败后保留已完成阶段与 artifacts，后续应优先用 resume 继续，而不是整轮重跑。
- 提交前应先执行 `powershell -ExecutionPolicy Bypass -File script/fq_local_preflight.ps1 -Mode Ensure`，并保持 `.githooks/pre-push` 已安装，避免把明显失败留到 PR CI。
- 当前 `script/fq_local_preflight.ps1` 除了 docs guard、pre-commit、pytest 外，还会在当前分支已有关联 PR 且 `gh` 已登录时阻断 unresolved review threads。

## 常用部署命令

### 全量并行环境

```powershell
docker compose -f docker/compose.parallel.yaml up -d --build
```

- 这条命令只用于显式全量重建；日常 selective deploy 统一优先走 `script/fq_apply_deploy_plan.ps1`
- Docker 构建默认启用 BuildKit 本地缓存；未显式设置时，`script/docker_parallel_compose.ps1` 会把 `FQ_DOCKER_BUILD_CACHE_ROOT` 设为仓库下的 `.artifacts/docker-build-cache`
- 当前默认不会主动拉取 GHCR 远端缓存；只有显式设置 `FQ_ENABLE_REMOTE_CACHE_PULL=1` 时，`docker_parallel_compose.ps1` 才会进入 `remote_cached` 分支并执行 `docker pull`
- `main` 合并后的镜像发布 workflow：`.github/workflows/docker-images.yml`
- `main` 合并后的正式自动部署 workflow：`.github/workflows/deploy-production.yml`
- 正式 deploy canonical repo root：`D:\fqpack\freshquant-2026.2.23`
- 正式 deploy mirror：`D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production`
- 正式收口时由 `FQ_DOCKER_FORCE_LOCAL_BUILD=1` 强制本机构建；GHCR 不再是正式 deploy 前置

### 自动正式部署

- `deploy-production.yml` 由 `push main` 直接触发，不需要额外审批。
- `script/ci/run_formal_deploy.py` 会读取 `production-state.json` 中的上一次成功部署 SHA，计算 `last_success_sha -> current main HEAD` 的 changed paths，再调用 `script/freshquant_deploy_plan.py` 得到本轮 deploy plan。
- 如果触发事件里的 SHA 已经不是当前 main tip，`deploy-production.yml` 会直接失败，不会对过时 push 继续 deploy。
- workflow 本身会先从 canonical repo root bootstrap/同步本机 `D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production` mirror，再在该目录下执行 `py -3.12 -m uv sync --frozen` 与 `run_formal_deploy.py`。
- 正式 deploy 要求 production runner 宿主机已安装的 Python 3.12 与 uv；缺任一工具都会在 deploy 前直接失败。
- 本轮正式 deploy 会显式导出 `FQ_DOCKER_FORCE_LOCAL_BUILD=1`，避免 `docker_parallel_compose.py` 把 `--build` 改写成 GHCR pull 路径。
- 如需临时恢复 GHCR 远端缓存试验，可在人工会话显式设置 `FQ_ENABLE_REMOTE_CACHE_PULL=1`；正式 production deploy 默认不使用该路径。

### 共享部署计划解析

```powershell
py -3.12 script/freshquant_deploy_plan.py --changed-path freshquant/rear/api_server.py --changed-path morningglory/fqwebui/src/views/GanttUnified.vue --format summary
```

### 选择性部署正式入口

```powershell
powershell -ExecutionPolicy Bypass -File script/fq_apply_deploy_plan.ps1 -FromGitDiff origin/main...HEAD
```

### 从失败阶段继续选择性部署

```powershell
powershell -ExecutionPolicy Bypass -File script/fq_apply_deploy_plan.ps1 -ResumeLatest
```

```powershell
powershell -ExecutionPolicy Bypass -File script/fq_apply_deploy_plan.ps1 -ResumeFromStatePath D:\fqpack\freshquant-2026.2.23\.artifacts\manual-deploy\deploy-state-20260319-120000.json
```

- `fq_apply_deploy_plan.ps1` 也支持 `-StatePath <path>`，可把当前 deploy 状态文件固定到指定位置
- resume 只会从第一个未完成阶段继续；已完成阶段不会重复执行

### 按变更路径执行选择性部署

```powershell
powershell -ExecutionPolicy Bypass -File script/fq_apply_deploy_plan.ps1 -ChangedPath freshquant/rear/api_server.py -ChangedPath morningglory/fqwebui/src/views/GanttUnified.vue -RunHealthChecks -RunRuntimeOpsCheck
```

### 只重建 API / Web

```powershell
docker compose -f docker/compose.parallel.yaml up -d --build fq_apiserver fq_webui
```

### 只重建 TradingAgents

```powershell
docker compose -f docker/compose.parallel.yaml up -d --build ta_backend ta_frontend
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
| `freshquant/strategy/**` 或 `freshquant/signal/**` | Guardian | 执行 `powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode EnsureServiceAndRestartSurfaces -DeploymentSurface guardian -BridgeIfServiceUnavailable` |
| `sunflower/QUANTAXIS/**` | QAWebServer 与依赖 QUANTAXIS 的宿主机策略链路 | 重建 `fq_qawebserver`；同步重启受影响宿主机 Guardian / strategy 进程 |
| `freshquant/data/gantt*` / `freshquant/shouban30_pool_service.py` | Gantt/Shouban30 读模型与 API | 重建 API；必要时重跑 Dagster 任务 |
| `freshquant/daily_screening/**` | 每日选股 API 与 `fqscreening` 读模型 | 重建 API；如改动影响自动任务语义，补跑 Dagster 每日筛选任务 |
| `morningglory/fqwebui/**` | Web UI | 重建 `fq_webui` |
| `morningglory/fqdagster/**` / `morningglory/fqdagsterconfig/**` | Dagster | 重启 `fq_dagster_webserver` 与 `fq_dagster_daemon` |
| `third_party/tradingagents-cn/**` | TradingAgents-CN | 重建 `ta_backend` 与 `ta_frontend` |
| `runtime/symphony/**` | 正式 orchestrator | 已预装计划任务时执行 `sync_freshquant_symphony_service.ps1` + `invoke_freshquant_symphony_restart_task.ps1`；否则使用 `reinstall_freshquant_symphony_service.ps1` 或激活脚本 |

- `script/fqnext_host_runtime_ctl.ps1 -Mode EnsureServiceAndRestartSurfaces` 当前会先做 surface reconcile；若首次重启失败且启用了 `-BridgeIfServiceUnavailable`，即使 `fqnext-supervisord` service 仍是 `Running`，也允许触发一次管理员桥接并重试一次

## 健康检查

### API

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:15000/api/runtime/components
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:15000/api/runtime/health/summary
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:15000/api/gantt/plates?provider=xgb
```

### Web UI

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:18080/
```

### TradingAgents

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:13000/api/health
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:13080/health
```

### Symphony

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:40123/api/v1/state
```

### Deploy 后运维面检查

本轮有实际 deploy 时，必须先采 baseline，再在接口健康检查通过后执行 verify：

```powershell
powershell -ExecutionPolicy Bypass -File runtime/symphony/scripts/check_freshquant_runtime_post_deploy.ps1 -Mode CaptureBaseline -OutputPath <baseline.json>
powershell -ExecutionPolicy Bypass -File runtime/symphony/scripts/check_freshquant_runtime_post_deploy.ps1 -Mode Verify -BaselinePath <baseline.json> -OutputPath <verify.json> -DeploymentSurface api,market_data
```

- `DeploymentSurface` 取值固定为：`api`、`web`、`dagster`、`qa`、`tradingagents`、`symphony`、`market_data`、`guardian`、`position_management`、`tpsl`、`order_management`；未知值会直接报错，不会静默跳过检查
- 输出 JSON 至少包含：`baseline`、`docker_checks`、`service_checks`、`process_checks`、`warnings`、`failures`、`passed`
- 固定检查基础容器：`fq_mongodb`、`fq_redis`
- 按本轮部署面追加检查容器：`fq_apiserver`、`fq_webui`、`fq_dagster_webserver`、`fq_dagster_daemon`、`fq_qawebserver`、`ta_backend`、`ta_frontend`
- 固定记录宿主机服务：`fq-symphony-orchestrator`、`fqnext-supervisord`；只有命中对应宿主机部署面时，`Running` 才是 deploy 通过前提
- 关键进程语义固定为：deploy 前已运行的不能在 deploy 后消失；本轮明确要求恢复的必须恢复；deploy 前本来就没运行且本轮未涉及的只记 warning
- 对 `fqnext-supervisord` 托管的已知宿主机进程，脚本会优先读取 supervisor 真值；只有 supervisor 不可用或没有映射关系时，才回退到 `Win32_Process.CommandLine`
- 脚本支持 `-DockerSnapshotPath`、`-ServiceSnapshotPath`、`-ProcessSnapshotPath`、`-SupervisorSnapshotPath`，供手工回放或测试复现使用

### 运维面辅助命令

```powershell
docker compose -f docker/compose.parallel.yaml ps
Get-Service fq-symphony-orchestrator
Get-Service fqnext-supervisord
powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode Status
```

## 部署后必须确认的事实

- API 蓝图能返回，不是只监听端口。
- Web UI 页面不是空白页，关键页面 `/gantt`、`/gantt/shouban30`、`/daily-screening`、`/position-management`、`/tpsl`、`/runtime-observability` 能打开。
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
