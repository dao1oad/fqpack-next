# 生产机器访问与环境（100 / 116）

> 本文件记录 FreshQuant 局域网生产机器 `192.168.1.100` 与 `192.168.1.116` 的连接方式、机器环境与部署注意事项，供后续 Agent 直接使用。
> 信息核对时间：2026-08-07（当前远程 `main` = `363d90a8`）。

## 1. 连接方式（SSH）

两台机器均使用同一把私钥，从本机（101 / 当前 Agent 主机）免密连接：

```powershell
# 100
ssh -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=8 `
  -i "$env:USERPROFILE\.ssh\id_fq116" Administrator@192.168.1.100

# 116
ssh -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=8 `
  -i "$env:USERPROFILE\.ssh\id_fq116" Administrator@192.168.1.116
```

- 私钥：`C:\Users\Administrator\.ssh\id_fq116`（公钥 `id_fq116.pub`）
- 用户：`Administrator`（管理员，免密 sudo/提权）
- 在脚本/Agent 中执行远程命令时，把 PowerShell 脚本通过 stdin 管道传入：

```powershell
$payload = @'
Set-Location 'D:\fqpack\freshquant-2026.2.23'
git rev-parse HEAD
'@
$payload | ssh -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=8 `
  -i "$env:USERPROFILE\.ssh\id_fq116" Administrator@192.168.1.116 powershell -NoProfile -Command -
```

> 注意：本机 `~/.ssh/config` 中没有这两台机器的条目；必须用 `-i` 显式指定私钥，并配合 `-o IdentitiesOnly=yes`。

## 2. 机器环境（两机对比）

| 项目 | 100（192.168.1.100） | 116（192.168.1.116） |
| --- | --- | --- |
| 主机名 | `DESKTOP-2420UIN` | `DESKTOP-2420UIN` |
| 操作系统 | Windows 11 专业版 10.0.26200 | Windows 11 专业版 10.0.26200 |
| 架构 / CPU | AMD64 / i9-13900HK | AMD64 / i9-13900HK |
| 内存 | 63.8 GB | 63.8 GB |
| 局域网 IP | `192.168.1.100` | `192.168.1.116`（另有 `192.168.112.1` 虚拟网卡） |
| 出站 HTTPS/PyPI/GitHub | 正常（2026-08-07 实测 200） | **异常**（HTTPS 超时 / `SSL: UNEXPECTED_EOF_WHILE_READING`，PyPI 与 GHCR 均不可用） |

## 3. 仓库状态（D:\fqpack\freshquant-2026.2.23）

两台机器都有同一仓库（`dao1oad/fqpack-next`）的正式部署副本。

| 项目 | 100 | 116 |
| --- | --- | --- |
| 仓库路径 | `D:\fqpack\freshquant-2026.2.23` | `D:\fqpack\freshquant-2026.2.23` |
| 当前分支 | `main` | detached（部署时固定到目标 SHA） |
| 当前 HEAD | `d3fd7f5f`（落后于 main） | `363d90a8`（= 当前 main） |
| production-state | `c969a7f2`（2026-07-24 部署 api/web） | `363d90a8`（2026-08-07 部署 guardian 等） |
| venv Python | **异常**（见 §5） | Python 3.12.10 正常 |

> 100 的代码与正式部署版本都落后于当前 main；如需使用请先评估是否需要对齐到 `origin/main`。

## 4. 运行面

### 4.1 Supervisor（宿主机 Python 进程）

- 服务名：`fqnext-supervisord`（Windows 服务，状态 Running）
- XML-RPC：`http://127.0.0.1:10011/RPC2`
- 状态查询（正式入口）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File D:\fqpack\freshquant-2026.2.23\script\fqnext_host_runtime_ctl.ps1 -Mode Status
```

100 当前（2026-08-07）：

```text
fqnext_guardian_event           Running
fqnext_realtime_xtdata_consumer Running
fqnext_realtime_xtdata_producer Running
fqnext_tpsl_worker              Running
fqnext_xt_account_sync_worker   Running
fqnext_xt_auto_repay_worker     Running
fqnext_xtdata_adj_refresh_worker Fatal   <-- 需要处理
fqnext_xtquant_broker           Running
```

116 当前：9 个程序全部 `Running`。

### 4.2 Docker 并行环境

- 引擎：Docker 29.3.1（服务 `com.docker.service` 显示 Stopped 但容器实际运行，勿依赖该服务状态）
- Compose 文件：`docker/compose.parallel.yaml`（仓库内）
- 容器（两机相同 10 个，compose 项目 `fqnext_20260223`）：`fq_apiserver`、`fq_webui`、`fq_dagster_webserver`、`fq_dagster_daemon`、`fq_qawebserver`、`fq_mongodb`、`fq_redis`、`fq_runtime_clickhouse`、`fq_runtime_indexer`、`fq_tdxhq`
- 已废弃删除：`ta_backend` / `ta_frontend`（TradingAgents 退役残留，2026-08-08 已从 100/116 删除 `fqnext_20260223-ta_backend-1` 与 `fqnext_20260223-ta_frontend-1`）
- 运维控制台宿主机快照：仓库 supervisor 常驻程序 `fqnext_ops_host_snapshot`（由 `script\fqnext_supervisor_config.py` 生成配置）执行 `script\fqnext_ops_host_snapshot.py --daemon --interval 300`，每 5 分钟循环采集输出 `D:\fqpack\freshquant-2026.2.23\ops-snapshot\host-runtime.json`；`fq_apiserver` 以只读卷挂载 `/freshquant/ops-snapshot`（env `FQ_OPS_SNAPSHOT_HOST_DIR`）。不依赖外部计划任务
- 镜像：`fqnext_rear:2026.2.23`、`fqnext_webui:2026.2.23`

### 4.3 端口（两机相同）

| 端口 | 用途 |
| --- | --- |
| 15000 | API（fq_apiserver） |
| 18080 | Web UI（fq_webui / nginx） |
| 11003 | QAWebServer |
| 10011 | Supervisor XML-RPC |
| 27027 | MongoDB（Docker） |
| 6380 | Redis（Docker） |
| 18123 | ClickHouse |

## 5. 已知环境问题

### 5.1 100 的 venv 损坏（uv trampoline）

- 现象：`D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe` 报
  `error: uv trampoline failed to spawn Python child process ... entity not found (os error 2)`
- 原因：`pyvenv.cfg` 指向 `C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.12.13-...\python.exe`，该文件存在且可直跑（`Python 3.12.13`），但 trampoline 解析失败
- 影响：`fqnext_host_runtime_ctl.ps1` 等依赖 venv 的脚本在 100 上报
  `Unable to resolve a usable Python 3.12 launcher`
- 缓解：supervisor 服务本身仍运行（XML-RPC 可查）；修复需重建 venv
  （`python -m venv --clear .venv` 或用 uv 重建），或配置可用的 Python 3.12 launcher

### 5.2 100 的 `fqnext_xtdata_adj_refresh_worker` Fatal

- 日志：`D:\fqdata\log\fqnext_xtdata_adj_refresh_worker_err.log`
- 错误：`stock QFQ marker is missing`（resolve_active_slot 找不到 stock 快照 marker）
- 与 116 之前不同：116 曾因旧代码不识别 `source_invalid_close` Fatal，已随 #513 部署解决；100 是 marker 缺失，需单独排查 QFQ 构建链路

### 5.3 116 出站 TLS 异常（部署约束）

- 116 的 PyPI / GHCR / HTTPS 出站不可用；**禁止在 116 上执行 pip / uv sync / docker pull 官方源**
- 代码同步必须用 git bundle + scp；镜像同步必须用 `docker save` / `docker load`
- 参考此前成功的部署方式（本仓库 `.codex-tmp-*` 历史记录）：

```powershell
# 101 侧
git bundle create D:\fqpack\runtime\formal-deploy\fqnext-main-<sha>.bundle origin/main
scp -o BatchMode=yes -o IdentitiesOnly=yes -i "$env:USERPROFILE\.ssh\id_fq116" `
  D:\fqpack\runtime\formal-deploy\fqnext-main-<sha>.bundle `
  Administrator@192.168.1.116:C:/Windows/Temp/
docker save fqnext_rear:2026.2.23-<sha> -o D:\fqpack\runtime\formal-deploy\fqnext-rear-<sha>.tar
scp -o BatchMode=yes -o IdentitiesOnly=yes -i "$env:USERPROFILE\.ssh\id_fq116" `
  D:\fqpack\runtime\formal-deploy\fqnext-rear-<sha>.tar `
  Administrator@192.168.1.116:C:/Windows/Temp/

# 116 侧（通过 ssh 执行）
Set-Location 'D:\fqpack\freshquant-2026.2.23'
git fetch C:/Windows/Temp/fqnext-main-<sha>.bundle refs/remotes/origin/main
git checkout --detach FETCH_HEAD
docker load -i C:\Windows\Temp\fqnext-rear-<sha>.tar
$env:FQ_COMPOSE_ENV_FILE='D:\fqpack\config\fqnext.compose.env'
$env:FQPACK_TDX_SYNC_DIR='D:/new_tdx'
$env:FQNEXT_REAR_IMAGE='fqnext_rear:2026.2.23-<sha>'
docker compose -f docker/compose.parallel.yaml up -d --no-deps fq_apiserver
```

## 6. 关键目录与配置

| 路径 | 用途 |
| --- | --- |
| `D:\fqpack\freshquant-2026.2.23` | 仓库（正式部署副本） |
| `D:\fqpack\runtime\formal-deploy` | formal deploy 产物 / production-state.json / runs/ |
| `D:\fqpack\config\fqnext.compose.env` | Docker compose 正式 env_file |
| `D:\fqpack\config\supervisord.fqnext.conf` | Supervisor 正式配置 |
| `D:\fqdata\log` | 宿主机进程日志 |
| `D:\new_tdx` | 通达信同步目录（`FQPACK_TDX_SYNC_DIR`） |
| `D:\fqpack\supervisord\scripts\run_fqnext_supervisord_restart_task.ps1` | 管理员桥接重启脚本 |

## 7. 常用运维命令

```powershell
# API / Web 健康
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:15000/api/runtime/health/summary
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:18080/

# Docker 容器
docker compose -f D:\fqpack\freshquant-2026.2.23\docker\compose.parallel.yaml ps

# 宿主机运行面（在目标机器上执行）
powershell -NoProfile -ExecutionPolicy Bypass -File `
  D:\fqpack\freshquant-2026.2.23\script\fqnext_host_runtime_ctl.ps1 -Mode Status
```
