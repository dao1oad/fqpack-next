---
name: docker-parallel-deployment
description: 当宿主机旧仓 `D:\fqpack\freshquant` 已占用默认端口时，使用本仓 Docker 并行启动 FreshQuant 与 TradingAgents-CN。
---

# Docker 并行部署指南

适用场景：宿主机已经运行旧仓 `D:\fqpack\freshquant`，当前仓 `D:\fqpack\freshquant-2026.2.23` 需要通过 Docker 并行运行且不抢占既有端口。

## 入口

- Compose 文件：`docker/compose.parallel.yaml`
- 项目名：`fqnext_20260223`

## 当前镜像约定

- `docker/Dockerfile.rear`
  - 基础镜像：`python:3.12-bookworm`
  - 依赖安装：`uv sync --frozen`
  - 运行环境：`/freshquant/.venv`
- `third_party/tradingagents-cn/Dockerfile.backend`
  - 基础镜像：`python:3.12-bookworm`
  - 依赖安装：`uv sync --frozen`
  - 运行环境：`/app/.venv`

因此 Compose 里的 Python 进程均显式调用容器内 `.venv`：

- FreshQuant：`/freshquant/.venv/bin/python`
- TradingAgents-CN：`/app/.venv/bin/python`

## 端口映射

| 组件 | 并行端口 |
|---|---:|
| FreshQuant Web UI | `18080` |
| FreshQuant API | `15000` |
| FreshQuant TDXHQ | `15001` |
| Dagster UI | `11003` |
| QAWebServer | `18010` |
| Redis | `6380` |
| MongoDB | `27027` |
| TradingAgents Backend | `13000` |
| TradingAgents Frontend | `13080` |

## 启动

全量启动：

```powershell
cd D:\fqpack\freshquant-2026.2.23
docker compose -f docker/compose.parallel.yaml up -d --build
```

如需在多个 worktree / 分支间隔离镜像标签，可先覆盖：
```powershell
$env:FQNEXT_REAR_IMAGE="fqnext_rear:<tag>"
$env:FQNEXT_WEBUI_IMAGE="fqnext_webui:<tag>"
$env:FQNEXT_TA_BACKEND_IMAGE="fqnext_ta_backend:<tag>"
$env:FQNEXT_TA_FRONTEND_IMAGE="fqnext_ta_frontend:<tag>"
docker compose -f docker/compose.parallel.yaml up -d --build
```

只启动 TradingAgents-CN：

```powershell
docker compose -f docker/compose.parallel.yaml up -d --build fq_mongodb fq_redis ta_backend ta_frontend
```

查看状态：

```powershell
docker compose -f docker/compose.parallel.yaml ps
```

## 访问入口

- FreshQuant Web UI：`http://127.0.0.1:18080/`
- FreshQuant API：`http://127.0.0.1:15000/`
- FreshQuant Dagster：`http://127.0.0.1:11003/`
- TradingAgents Frontend：`http://127.0.0.1:13080/`
- TradingAgents Backend Health：`http://127.0.0.1:13000/api/health`

## TradingAgents-CN 运行约定

- 第三方源码目录：`third_party/tradingagents-cn/`
- MongoDB 数据库：`tradingagents_cn`
- Redis DB：`8`
- 挂载目录：
  - `runtime/tradingagents-cn/data`
  - `runtime/tradingagents-cn/logs`

## 环境变量

- Compose 默认读取仓库根目录 `.env`
- TradingAgents 参考模板：`docker/tradingagents/.env.example`
- 若 `.env` 未显式配置 `JWT_SECRET`，并行 Compose 会为 `ta_backend` 注入开发默认值 `change-me-in-production`，仅用于本地开发/验收，生产环境仍应显式覆盖
- 至少应配置一个可用的大模型 Key，例如：
  - `DASHSCOPE_API_KEY`
  - `DEEPSEEK_API_KEY`
  - `OPENAI_API_KEY`

## 常见排障

### Docker Hub 拉取失败

```powershell
docker pull python:3.12-bookworm
docker pull node:lts-alpine
docker pull nginx:alpine
docker pull redis:7.0.12-alpine3.18
docker pull mongo:8.2.2
```

### FreshQuant 服务异常

```powershell
docker compose -f docker/compose.parallel.yaml logs --tail 200 fq_apiserver
docker compose -f docker/compose.parallel.yaml logs --tail 200 fq_tdxhq
docker compose -f docker/compose.parallel.yaml logs --tail 200 fq_dagster_webserver
```

### TradingAgents-CN 异常

```powershell
docker compose -f docker/compose.parallel.yaml logs --tail 200 ta_backend
docker compose -f docker/compose.parallel.yaml logs --tail 200 ta_frontend
```

重点检查：

- `ta_backend` 是否成功连接 `fq_mongodb` 与 `fq_redis`
- 根目录 `.env` 是否已配置可用 LLM Key
- `tradingagents_cn` 与 Redis `db 8` 是否已开始写入

## 停止

保留卷：

```powershell
docker compose -f docker/compose.parallel.yaml down
```

连卷一起删除：

```powershell
docker compose -f docker/compose.parallel.yaml down -v
```

### 9.5 宿主机 `broker / xtdata producer / consumer` 读错 Mongo

现象：

- Docker `127.0.0.1:27027/freshquant` 中看不到 `params`
- 宿主机 `127.0.0.1:27017/freshquant` 中却有 `params / xt_positions / xt_trades`
- Docker 内 API 与宿主机 MiniQMT 链路看到的是两套数据

根因：

- Docker 内服务连接 `fq_mongodb:27017`
- 宿主机进程如果没有显式配置 `FRESHQUANT_MONGODB__PORT=27027`，会回落到默认 `27017`

处理步骤：

1. 在宿主机 `envs.conf` 中显式设置：

```text
FRESHQUANT_MONGODB__HOST=127.0.0.1
FRESHQUANT_MONGODB__PORT=27027
FRESHQUANT_REDIS__HOST=127.0.0.1
FRESHQUANT_REDIS__PORT=6380
```

2. 首次使用 Docker `freshquant` 库时，先初始化：

```powershell
$env:FRESHQUANT_MONGODB__HOST="127.0.0.1"
$env:FRESHQUANT_MONGODB__PORT="27027"
python -m freshquant.initialize --quiet
```

3. 若宿主机旧库已有参数，按 `code` 同步 `freshquant.params` 到 Docker：

```powershell
@'
from pymongo import MongoClient

src = MongoClient("mongodb://127.0.0.1:27017")["freshquant"]["params"]
dst = MongoClient("mongodb://127.0.0.1:27027")["freshquant"]["params"]

for doc in src.find({}, {"_id": 0}):
    dst.update_one({"code": doc["code"]}, {"$set": doc}, upsert=True)
'@ | python -
```

4. 重启宿主机 `broker / producer / consumer`

补充说明：

- MiniQMT / XTData 仍必须运行在 Windows 宿主机，不建议尝试将 `broker` 放入 Linux 容器。
- Docker 并行模式下，如需让宿主机 `broker / producer / consumer` 与容器内 API 共用同一队列，Redis 应连接宿主机映射端口 `6380`，而不是旧宿主机 Redis `6379`。
- 推荐直接使用仓库内模板：
  - `docs/配置文件模板/envs.fqnext.example`
  - `docs/配置文件模板/supervisord.fqnext.example.conf`
