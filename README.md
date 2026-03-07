# freshquant

> Windows PowerShell 5.1 中文显示异常时，先执行：`. .\script\pwsh_utf8.ps1`

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

## 扩展构建

`fullcalc` 统一由项目内 Python 3.12 驱动：

```powershell
uv run python script/build_extensions.py --target fullcalc
```

产物位置：

- `morningglory/fqcopilot/python/fullcalc.pyd`

## Docker

FreshQuant 并行部署：

```powershell
docker compose -f docker/compose.parallel.yaml up -d --build
```

若需要在多个 worktree / 分支间隔离镜像标签，可先覆盖：
```powershell
$env:FQNEXT_REAR_IMAGE="fqnext_rear:<tag>"
$env:FQNEXT_WEBUI_IMAGE="fqnext_webui:<tag>"
$env:FQNEXT_TA_BACKEND_IMAGE="fqnext_ta_backend:<tag>"
$env:FQNEXT_TA_FRONTEND_IMAGE="fqnext_ta_frontend:<tag>"
docker compose -f docker/compose.parallel.yaml up -d --build
```

当前镜像约定：

- `docker/Dockerfile.rear` 通过 `uv sync --frozen` 构建 `/freshquant/.venv`
- `third_party/tradingagents-cn/Dockerfile.backend` 通过 `uv sync --frozen` 构建 `/app/.venv`

## Supervisor

宿主机 Supervisor 统一使用：

- `D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe`

配置文件：

- `D:\fqpack\config\supervisord.fqnext.conf`

## 其他

- Docker 并行部署说明：`docs/agent/Docker并行部署指南.md`
- 迁移进度：`docs/migration/progress.md`
- 破坏性变更：`docs/migration/breaking-changes.md`
