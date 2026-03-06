---
name: docker-parallel-deployment
description: 在宿主机旧 freshquant 已占用端口时，让本仓库通过 Docker 并行启动，并补充 TradingAgents-CN 第三方服务的端口、启动和排障说明。
---

# Docker 并行部署指南（与宿主机 `D:\fqpack\freshquant` 并行）

> 适用场景：宿主机已经在跑 `D:\fqpack\freshquant`，本仓库 `D:\fqpack\freshquant-2026.2.23` 需要通过 Docker 并行运行，且不抢占已有端口。

## 1. 入口

- Compose 文件：`docker/compose.parallel.yaml`
- 项目名固定：`fqnext_20260223`
- 作用：
  - 隔离网络、卷名和容器名
  - 复用当前仓库 Docker 构建链
  - 并行托管 FreshQuant 与 `TradingAgents-CN`

## 2. 端口映射

| 组件 | 宿主机旧项目端口 | 本仓库 Docker 并行端口 | 说明 |
|---|---:|---:|---|
| Web UI (nginx) | 80 | **18080** | FreshQuant 前端入口 |
| API Server | 5000 | **15000** | FreshQuant API |
| TDXHQ | 5001 | **15001** | FreshQuant 行情网关 |
| Dagster UI | 10003 | **11003** | FreshQuant 调度界面 |
| QAWebServer | 通常未占用 | **18010** | QUANTAXIS 入口 |
| Redis | 6379 | **6380** | `fq_redis` |
| MongoDB | 27017 | **27027** | `fq_mongodb` |
| TradingAgents Backend | N/A | **13000** | `ta_backend` |
| TradingAgents Frontend | N/A | **13080** | `ta_frontend` |

## 3. 启动

全量启动：

```powershell
cd D:\fqpack\freshquant-2026.2.23
docker compose -f docker/compose.parallel.yaml up -d --build
```

只启动 TradingAgents-CN 相关服务：

```powershell
docker compose -f docker/compose.parallel.yaml up -d --build fq_mongodb fq_redis ta_backend ta_frontend
```

查看状态：

```powershell
docker compose -f docker/compose.parallel.yaml ps
```

## 4. 访问入口

### 4.1 FreshQuant

- Web UI：`http://127.0.0.1:18080/`
- Dagster UI：`http://127.0.0.1:11003/`
- API：`http://127.0.0.1:15000/`

### 4.2 TradingAgents-CN

- 前端：`http://127.0.0.1:13080/`
- 后端健康检查：`http://127.0.0.1:13000/api/health`

## 5. TradingAgents-CN 运行约束

- 第三方源码目录：`third_party/tradingagents-cn/`
- 共享基础设施：
  - MongoDB：`fq_mongodb`
  - Redis：`fq_redis`
- 逻辑隔离：
  - MongoDB 数据库：`tradingagents_cn`
  - Redis：`db 8`
- 本地挂载目录：
  - `runtime/tradingagents-cn/data`
  - `runtime/tradingagents-cn/logs`

## 6. TradingAgents-CN 环境变量

- `ta_backend` 会读取仓库根目录 `.env`
- 参考模板：`docker/tradingagents/.env.example`
- 至少需要一个可用 LLM Key 才能真正完成分析推理：
  - `DASHSCOPE_API_KEY`
  - `DEEPSEEK_API_KEY`
  - `OPENAI_API_KEY`
- 如需启用 Tushare，再补 `TUSHARE_TOKEN`

## 7. Dagster 自动调度

当前 Compose 默认会启动 `fq_dagster_daemon`。

检查：

```powershell
docker compose -f docker/compose.parallel.yaml exec -T fq_dagster_daemon dagster-daemon liveness-check
```

临时关闭：

```powershell
docker compose -f docker/compose.parallel.yaml stop fq_dagster_daemon
```

## 8. 停止与清理

停止但保留卷：

```powershell
docker compose -f docker/compose.parallel.yaml down
```

停止并删除卷：

```powershell
docker compose -f docker/compose.parallel.yaml down -v
```

## 9. 常用排障

### 9.1 Docker Hub 拉取失败

```powershell
docker pull python:3.12-bookworm
docker pull node:lts-alpine
docker pull nginx:alpine
docker pull redis:7.0.12-alpine3.18
docker pull mongo:8.2.2
```

### 9.2 FreshQuant 前端 `/api/*` 502

```powershell
docker compose -f docker/compose.parallel.yaml ps
docker compose -f docker/compose.parallel.yaml logs --tail 200 fq_webui
docker compose -f docker/compose.parallel.yaml logs --tail 200 fq_apiserver
```

### 9.3 TradingAgents-CN 前端或后端异常

```powershell
docker compose -f docker/compose.parallel.yaml logs --tail 200 ta_frontend
docker compose -f docker/compose.parallel.yaml logs --tail 200 ta_backend
```

重点检查：

- `ta_backend` 是否成功连接 `fq_mongodb` / `fq_redis`
- 根目录 `.env` 是否已配置可用 LLM Key
- `tradingagents_cn` 和 Redis `db 8` 是否已经开始写入
