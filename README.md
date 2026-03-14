# freshquant

> Windows PowerShell 5.1 中文显示异常时，先执行：`. .\script\pwsh_utf8.ps1`

## 当前定位

本仓库已进入第二阶段：模块基本齐全，重点转向潜在 bug 修复、当前系统事实收敛、部署可重复、排障可维护。

正式治理已切换为：

- GitHub Issue：任务入口
- GitHub Draft PR：唯一 `Design Review`
- `docs/current/**`：唯一正式文档
- `Done = merge + ci + docs sync + deploy + health check + cleanup`

## 运行环境

- 宿主机统一使用项目根目录 `.venv`
- 解释器版本固定为 `Python 3.12.x`
- 依赖统一由 `uv.lock` 驱动
- Docker 容器内分别创建 `/freshquant/.venv` 与 `/app/.venv`

## 宿主机初始化

```powershell
cd D:\fqpack\freshquant-2026.2.23
.\create_venv.bat
.\install.bat --skip-web
```

常用命令：

```powershell
uv run fqctl --help
uv run pytest freshquant/tests -q
uv run python -m freshquant.rear.api_server --port 5000
```

## Docker 并行部署

```powershell
docker compose -f docker/compose.parallel.yaml up -d --build
```

常用并行端口：

- Web UI：`18080`
- API Server：`15000`
- TDXHQ：`15001`
- Dagster UI：`11003`
- Redis：`6380`
- MongoDB：`27027`

若需要在多个分支间隔离镜像标签，可先覆盖：

```powershell
$env:FQNEXT_REAR_IMAGE="fqnext_rear:<tag>"
$env:FQNEXT_WEBUI_IMAGE="fqnext_webui:<tag>"
$env:FQNEXT_TA_BACKEND_IMAGE="fqnext_ta_backend:<tag>"
$env:FQNEXT_TA_FRONTEND_IMAGE="fqnext_ta_frontend:<tag>"
docker compose -f docker/compose.parallel.yaml up -d --build
```

## Supervisor

宿主机 Supervisor 统一使用：

- `D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe`

配置文件：

- `D:\fqpack\config\supervisord.fqnext.conf`

正式宿主机入口：

- service：`fqnext-supervisord`
- RPC：`http://127.0.0.1:10011/RPC2`
- 管理员桥接任务：`fqnext-supervisord-restart`
- 控制脚本：`powershell -ExecutionPolicy Bypass -File script/fqnext_host_runtime_ctl.ps1 -Mode Status`

兼容人工启动器：

- `D:\fqpack\supervisord\frequant-next.bat`
- 该 `.bat` 仅保留为兼容入口，不再作为 `Global Stewardship` 正式部署入口

## 文档入口

- [文档索引](./docs/index.md)
- [当前总览](./docs/current/overview.md)
- [当前架构](./docs/current/architecture.md)
- [当前运行面](./docs/current/runtime.md)
- [当前部署](./docs/current/deployment.md)
- [当前排障](./docs/current/troubleshooting.md)
