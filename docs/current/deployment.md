# 当前部署

## 部署原则

- 代码改动后，受影响模块必须重新部署；只合并不部署不算完成。
- 本地会话只负责开发、测试和预检查。
- 正式 deploy 只允许基于最新远程 `main` 已合并 SHA。
- Docker 并行环境用于承载通用服务与前端；宿主机负责需要直连券商、XTData 或 Windows 资源的进程。
- 部署动作结束后必须先做接口层健康检查，再做 deploy 后运维面检查；两者都通过后才进入 cleanup。
- 当前 Done 判定固定为：`merge + ci + docs sync + deploy + health check + cleanup`。
- 正式收口前先用 `py -3.12 script/freshquant_deploy_plan.py` 生成部署计划；不要在会话内临场重新推理 Docker / 宿主机边界。
- formal deploy 产物固定写入 `D:/fqpack/runtime/formal-deploy`。

## 常用部署命令

### 全量并行环境

```powershell
docker compose -f docker/compose.parallel.yaml up -d --build
```

- 这条命令只用于显式全量重建；日常 selective deploy 统一优先走 `script/fq_apply_deploy_plan.ps1`
- Docker 构建默认启用 BuildKit 本地缓存；未显式设置时，`script/docker_parallel_compose.ps1` 会把 `FQ_DOCKER_BUILD_CACHE_ROOT` 设为仓库下的 `.artifacts/docker-build-cache`
- Runtime Observability 的 ClickHouse 默认通过 `FQ_RUNTIME_CLICKHOUSE_USER/FQ_RUNTIME_CLICKHOUSE_PASSWORD` 创建并使用专用查询用户；不要再让 API / indexer 走无凭证 `default`
- 当前默认不会主动拉取 GHCR 远端缓存；只有显式设置 `FQ_ENABLE_REMOTE_CACHE_PULL=1` 时，`docker_parallel_compose.ps1` 才会进入 `remote_cached` 分支并执行 `docker pull`
- `main` 合并后的镜像发布 workflow：`.github/workflows/docker-images.yml`
- `main` 合并后的正式自动部署 workflow：`.github/workflows/deploy-production.yml`
- 正式 deploy canonical repo root：`D:\fqpack\freshquant-2026.2.23`
- 本机 deploy mirror：`D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production`
- 正式收口时由 `FQ_DOCKER_FORCE_LOCAL_BUILD=1` 强制本机构建；GHCR 不再是正式 deploy 前置

### 自动正式部署

- `deploy-production.yml` 由 `push main` 直接触发，不需要额外审批。
- `script/ci/run_formal_deploy.py` 会读取 `production-state.json` 中的上一次成功部署 SHA，计算 `last_success_sha -> current main HEAD` 的 changed paths，再调用 `script/freshquant_deploy_plan.py` 得到本轮 deploy plan。
- 如果触发事件里的 SHA 已经不是当前 main tip，`deploy-production.yml` 会直接失败，不会对过时 push 继续 deploy。
- workflow 本身会先从 canonical repo root bootstrap/同步本机 deploy mirror `D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production`，再在该目录下执行 `py -3.12 -m uv sync --frozen` 与 `run_formal_deploy.py`。
- workflow 会显式把 canonical repo root 与本机 deploy mirror 加入 git `safe.directory`，避免 runner 在多 worktree 场景下拒绝执行 git。
- 正式 deploy 要求 production runner 宿主机已安装的 Python 3.12；缺失时会在 deploy 前直接失败。
- 正式 deploy 要求 production runner 宿主机已安装的 uv；缺失时会在 deploy 前直接失败。
- 本轮正式 deploy 会显式导出 `FQ_DOCKER_FORCE_LOCAL_BUILD=1`，避免 `docker_parallel_compose.py` 把 `--build` 改写成 GHCR pull 路径。
- 如需临时恢复 GHCR 远端缓存试验，可在人工会话显式设置 `FQ_ENABLE_REMOTE_CACHE_PULL=1`；正式 production deploy 默认不使用该路径。

### 共享部署计划解析

```powershell
py -3.12 script/freshquant_deploy_plan.py --changed-path freshquant/rear/api_server.py --changed-path morningglory/fqwebui/src/views/GanttUnified.vue --format summary
```

### 本地预检查

```powershell
powershell -ExecutionPolicy Bypass -File script/fq_local_preflight.ps1 -Mode Ensure
```

- `script/fq_local_preflight.ps1` 是本地会话同步到远程 `main` 前的标准预检查入口；默认会对最新远程 `main` 做 fetch，并验证 governance / pre-commit / pytest / review threads。
- `script/fq_apply_deploy_plan.ps1` 仍然保留，用于手工 selective deploy 或断点续跑 deploy phase。

```powershell
powershell -ExecutionPolicy Bypass -File script/fq_apply_deploy_plan.ps1 -FromGitDiff origin/main...HEAD
```

### 正式 deploy

```powershell
py -3.12 script/ci/run_formal_deploy.py --repo-root <deploy-mirror> --format summary
```

- formal deploy 会先解析最新远程 `origin/main` SHA，再按 `last_success_sha -> latest origin/main sha` 计算部署范围。
- 本地未 merge 的 worktree 不能直接当正式 deploy 来源。

### 宿主机同步 Python 依赖

```powershell
.\install.bat --skip-web
```

### 宿主机 Supervisor 底座安装

```powershell
powershell -ExecutionPolicy Bypass -File script/install_fqnext_supervisord_service.ps1
powershell -ExecutionPolicy Bypass -File script/install_fqnext_supervisord_restart_task.ps1
```

- 正式宿主机底座 service 名称：`fqnext-supervisord`
- 管理员桥接任务名：`fqnext-supervisord-restart`

## 模块部署矩阵

| 变更路径 | 需要部署的模块 | 最低动作 |
| --- | --- | --- |
| `freshquant/rear/**` | API Server | 重建 `fq_apiserver` 容器或重启 API 进程 |
| `freshquant/runtime_observability/**` | Runtime Observability API / ClickHouse / indexer | 重建 `fq_apiserver`，并确认 `fq_runtime_clickhouse`、`fq_runtime_indexer` 已恢复 |
| `freshquant/order_management/**` | 订单管理、API、broker/ingest 相关宿主机进程 | 重建 API；执行 `powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode EnsureServiceAndRestartSurfaces -DeploymentSurface order_management -BridgeIfServiceUnavailable` |
| `freshquant/position_management/**` | 仓位管理（宿主机实际由统一 `xt_account_sync.worker` 承担） | 执行 `powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode EnsureServiceAndRestartSurfaces -DeploymentSurface position_management -BridgeIfServiceUnavailable` |
| `freshquant/xt_account_sync/**` | XT 主动查询统一 worker（仓位管理 + 订单管理） | 执行 `powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode EnsureServiceAndRestartSurfaces -DeploymentSurface position_management -DeploymentSurface order_management -BridgeIfServiceUnavailable` |
| `freshquant/tpsl/**` | TPSL | 执行 `powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode EnsureServiceAndRestartSurfaces -DeploymentSurface tpsl -BridgeIfServiceUnavailable` |
| `freshquant/market_data/**` | XTData producer / consumer | 执行 `powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode EnsureServiceAndRestartSurfaces -DeploymentSurface market_data -BridgeIfServiceUnavailable`；必要时重新 prewarm |
| `freshquant/strategy/**` 或 `freshquant/signal/**` | Guardian | 执行 `powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode EnsureServiceAndRestartSurfaces -DeploymentSurface guardian -BridgeIfServiceUnavailable` |
| `sunflower/QUANTAXIS/**` | QAWebServer 与依赖 QUANTAXIS 的宿主机策略链路 | 重建 `fq_qawebserver`；同步重启受影响宿主机 Guardian / strategy 进程 |
| `freshquant/data/gantt*` / `freshquant/shouban30_pool_service.py` | Gantt/Shouban30 读模型与 API | 重建 API；必要时重跑 Dagster 任务 |
| `freshquant/daily_screening/**` | 每日选股 API 与 `fqscreening` 读模型 | 重建 API；如改动影响自动任务语义，补跑 Dagster 每日筛选任务 |
| `morningglory/fqwebui/**` | Web UI | 重建 `fq_webui` |
| `morningglory/fqdagster/**` / `morningglory/fqdagsterconfig/**` | Dagster | 重启 `fq_dagster_webserver` 与 `fq_dagster_daemon` |
| `third_party/tradingagents-cn/**` | TradingAgents-CN | 重建 `ta_backend` 与 `ta_frontend` |

- `script/fqnext_host_runtime_ctl.ps1 -Mode EnsureServiceAndRestartSurfaces` 当前会先做 surface reconcile；若首次重启失败且启用了 `-BridgeIfServiceUnavailable`，即使 `fqnext-supervisord` service 仍是 `Running`，也允许触发一次管理员桥接并重试一次

## 健康检查

### API

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:15000/api/runtime/components
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:15000/api/runtime/health/summary
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:18123/ping
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

### Deploy 后运维面检查

本轮有实际 deploy 时，必须先采 baseline，再在接口健康检查通过后执行 verify：

```powershell
powershell -ExecutionPolicy Bypass -File script/check_freshquant_runtime_post_deploy.ps1 -Mode CaptureBaseline -OutputPath <baseline.json>
powershell -ExecutionPolicy Bypass -File script/check_freshquant_runtime_post_deploy.ps1 -Mode Verify -BaselinePath <baseline.json> -OutputPath <verify.json> -DeploymentSurface api,market_data
```

- `DeploymentSurface` 取值固定为：`api`、`web`、`dagster`、`qa`、`tradingagents`、`market_data`、`guardian`、`position_management`、`tpsl`、`order_management`
- 输出 JSON 至少包含：`baseline`、`docker_checks`、`service_checks`、`process_checks`、`warnings`、`failures`、`passed`
- 固定检查基础容器：`fq_mongodb`、`fq_redis`
- 固定记录宿主机服务：`fqnext-supervisord`

### 运维面辅助命令

```powershell
docker compose -f docker/compose.parallel.yaml ps
Get-Service fqnext-supervisord
powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode Status
```

## 部署后必须确认的事实

- API 蓝图能返回，不是只监听端口。
- Web UI 页面不是空白页。
- XTData 相关修改后，producer/consumer 日志持续产出，Redis 队列不持续堆积。
- 宿主机 deployment surface 修改后，`fqnext-supervisord` 保持 `Running`，且 `script/fqnext_host_runtime_ctl.ps1 -Mode Status` 能返回目标 program 为 `RUNNING`。
- 如果本轮有实际 deploy，`check_freshquant_runtime_post_deploy.ps1` 的 verify 结果必须 `passed=true`，且 `failures` 为空。

## 正式收口规则

- 本地会话完成之后要同步到远程 `main`。
- 只有最新远程 `main` 的已合并 SHA 可以进入正式 deploy。
- 本轮没有实际 deploy 时，不执行 runtime ops check。
- 本轮有实际 deploy 时，必须先 `CaptureBaseline`，再在 health check 后执行 `Verify`。
- 命中宿主机 deployment surface 时，统一通过 `script/fqnext_host_runtime_ctl.ps1` 控制 `fqnext-supervisord`。
- 只有 health check 与 runtime ops check 都通过，才允许 cleanup。
