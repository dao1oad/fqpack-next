---
name: docker-parallel-deployment
description: 在宿主机 old freshquant 已占用端口的情况下，让本仓库用 Docker 并行启动（Web UI/Redis/MongoDB/API/TDXHQ/QAWebServer），并给出端口映射、验证与排障步骤。
---

# Docker 并行部署指南（与宿主机 `D:\\fqpack\\freshquant` 并行）

> 适用场景：宿主机已经在跑 `D:\\fqpack\\freshquant`（占用 80/5000/5001/6379/27017 等端口），需要让本仓库 `D:\\fqpack\\freshquant-2026.2.23` **同时运行**，且互不抢端口。

## 1. 入口与文件

- Docker Compose：`docker/compose.parallel.yaml`
- 关键说明：
  - Compose 已固定 `name: fqnext_20260223`，避免容器/网络/卷名称与其它项目混淆
  - 后端镜像基于 `docker/Dockerfile.rear`；前端镜像基于 `docker/Dockerfile.web`

## 2. 端口映射（避免冲突）

| 组件 | 宿主机旧项目端口（已占用） | 本仓库 Docker 并行端口 | 说明 |
|---|---:|---:|---|
| Web UI (nginx) | 80 | **18080** | 访问入口 |
| API Server (Flask+gevent) | 5000 | **15000** | 也可直连调试 |
| TDXHQ 网关 (Tornado) | 5001 | **15001** | 行情网关 |
| Dagster UI (dagster-webserver) | 10003 | **11003** | 任务编排界面（仅 webserver） |
| QUANTAXIS QAWebServer |（通常未占用）| **18010** | Web UI 反代 `/api/qa/*` 依赖 |
| Redis | 6379 | **6380** | 队列/缓存 |
| MongoDB | 27017 | **27027** | 业务数据 |

## 3. 启动（首次会 build，较慢）

在仓库根目录执行：

```powershell
cd D:\fqpack\freshquant-2026.2.23
docker compose -f docker/compose.parallel.yaml up -d --build
```

查看容器状态：

```powershell
docker compose -f docker/compose.parallel.yaml ps
```

## 4. 访问与最小验证

- Web UI：`http://127.0.0.1:18080/`
- Dagster UI：`http://127.0.0.1:11003/`
- API（直连）：`http://127.0.0.1:15000/api/get_stock_pools_list?page=1`
- API（经 Web UI 反代）：`http://127.0.0.1:18080/api/get_stock_pools_list?page=1`
- TDXHQ（示例）：`http://127.0.0.1:15001/get_security_count?market=0`

## 4.1 Dagster 自动调度（daemon）

本 Compose 默认会启动 `dagster-daemon`（用于 schedules/sensors 的自动调度）。你可用以下命令确认：

```powershell
docker compose -f docker/compose.parallel.yaml exec -T fq_dagster_daemon dagster-daemon liveness-check
```

如果只想临时关闭自动调度：

```powershell
docker compose -f docker/compose.parallel.yaml stop fq_dagster_daemon
```

## 5. 停止 / 清理

停止（保留 Mongo/Redis 数据卷）：

```powershell
docker compose -f docker/compose.parallel.yaml down
```

停止并删除数据卷（会清空 Docker 内 Mongo/Redis 数据，请谨慎）：

```powershell
docker compose -f docker/compose.parallel.yaml down -v
```

## 6. 常用排障

### 6.1 `auth.docker.io/token` 偶发拉取失败

这是 Docker Hub 认证/网络偶发问题。可先手工拉取基础镜像后再 `up --build`：

```powershell
docker pull python:3.12-bookworm
docker pull node:lts-alpine
docker pull nginx:alpine
docker pull redis:7.0.12-alpine3.18
docker pull mongo:8.2.2
```

### 6.2 Web UI `/api/*` 502

优先确认 API 容器是否在运行：

```powershell
docker compose -f docker/compose.parallel.yaml ps
docker compose -f docker/compose.parallel.yaml logs --tail 200 fq_webui
docker compose -f docker/compose.parallel.yaml logs --tail 200 fq_apiserver
```

（本仓库的 `morningglory/fqwebui/nginx.conf` 已做 Docker DNS 动态解析处理；若仍出现 502，多半是后端未就绪或启动报错。）
