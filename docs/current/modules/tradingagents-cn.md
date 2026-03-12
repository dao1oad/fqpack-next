# TradingAgents-CN

## 职责

TradingAgents-CN 是并行接入的独立分析子系统，当前通过 Docker 并行环境对外提供分析后端和前端，不参与 FreshQuant 主交易链的订单、仓位和 TPSL 决策。

## 入口

- Docker 服务
  - `ta_backend`
  - `ta_frontend`
- 并行端口
  - backend：`13000`
  - frontend：`13080`

## 依赖

- Mongo
  - 数据库 `tradingagents_cn`
- Redis
  - `db=8`
- 根 `.env` / `FQ_COMPOSE_ENV_FILE`
- Docker 并行环境

## 数据流

`ta_frontend -> ta_backend -> analysis workflow / cache / session -> Mongo + Redis`

它只共享基础设施，不共享 FreshQuant 的订单账本和策略状态机。

## 存储

- Mongo database：`tradingagents_cn`
- Redis database：`8`
- 宿主机挂载目录：
  - `runtime/tradingagents-cn/data`
  - `runtime/tradingagents-cn/logs`

## 配置

compose 中的关键环境变量：

- `CONFIG_SOT=file`
- `MONGODB_URL=mongodb://fq_mongodb:27017/tradingagents_cn`
- `REDIS_URL=redis://fq_redis:6379/8`
- `TRADINGAGENTS_DATA_DIR=/app/data`
- `TRADINGAGENTS_LOG_DIR=/app/logs`

当前集成约束：

- 配置真相源是部署环境和 compose，不把上游长文档直接当成本仓正式文档。
- 不在 FreshQuant 主库中复用 TradingAgents 的业务集合。

## 部署/运行

```powershell
docker compose -f docker/compose.parallel.yaml up -d --build ta_backend ta_frontend
```

健康检查：

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:13000/api/health
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:13080/health
```

## 排障点

### backend 启不来

- 检查 Mongo/Redis 是否健康
- 检查 `.env` 是否包含所需 secret

### 前端能开但分析请求卡住

- 检查 backend `/api/health`
- 检查 `runtime/tradingagents-cn/logs`
- 检查 Redis `db=8`

### 与 FreshQuant 主系统串库

- 检查 Mongo URL 是否仍指向 `tradingagents_cn`
- 检查 Redis DB 是否误改成主链使用的库
