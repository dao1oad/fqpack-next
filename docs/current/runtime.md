# 当前运行面

## 宿主机与 Docker 分层

### Windows 宿主机承担

- XTQuant / XTData 连接。
- Guardian monitor。
- Position management worker。
- TPSL tick listener。
- Symphony 正式单实例 orchestrator。
- 需要直接访问券商、终端、`TDX_HOME` 或 Windows 本地目录的组件。

### Docker 并行环境承担

- MongoDB：`27027 -> 27017`
- Redis：`6380 -> 6379`
- API Server：`15000 -> 5000`
- TDXHQ：`15001 -> 5001`
- Dagster Webserver：`11003 -> 10003`
- QAWebServer：`18010 -> 8010`
- Web UI：`18080 -> 80`
- TradingAgents backend：`13000 -> 8000`
- TradingAgents frontend：`13080 -> 80`

对应编排文件是 `docker/compose.parallel.yaml`。

## 当前正式服务

- Symphony 正式服务名：`fq-symphony-orchestrator`
- Symphony 状态接口：`http://127.0.0.1:40123/api/v1/state`
- Symphony 工作区根目录：`D:/fqpack/runtime/symphony-service/workspaces`
- Symphony 运行模板：`runtime/symphony/WORKFLOW.freshquant.md`
- 运行日志根目录：`logs/runtime`，可被 `FQ_RUNTIME_LOG_DIR` 覆盖

## 最小可用运行面

当目标是调试主交易链时，至少需要：

- MongoDB
- Redis
- API Server
- XTData producer
- XTData consumer
- Guardian monitor
- Position worker
- Order submit / broker / XT 回报 ingest
- TPSL worker（如果验证退出逻辑）

当目标是调试前端展示时，至少还需要：

- Web UI
- Gantt/Shouban30 对应读模型数据
- Runtime Observability 原始日志目录

## 并行环境的默认口径

- 宿主机 `.env` 示例：`deployment/examples/envs.fqnext.example`
- Docker API 使用 `FQ_COMPOSE_ENV_FILE` 指向主工作树 `.env`
- Web UI 默认访问并行 API `http://127.0.0.1:15000`
- TradingAgents 使用独立 Mongo 库 `tradingagents_cn` 与 Redis `db=8`

## 运行依赖

- XTData producer 依赖 `XTQUANT_PORT`，默认 `58610`
- XTData producer / consumer / TPSL / Order Management 共享 Redis
- Guardian、Position worker、Order Management、TPSL 共享 Mongo 基础库与运行时事件日志
- Shouban30 的 `.blk` 同步依赖宿主机 `TDX_HOME`

## 常见运行模式

### 只调 API / 页面

```powershell
docker compose -f docker/compose.parallel.yaml up -d --build fq_mongodb fq_redis fq_apiserver fq_webui
```

### 调实时交易链

```powershell
python -m freshquant.market_data.xtdata.market_producer
python -m freshquant.market_data.xtdata.strategy_consumer --prewarm
python -m freshquant.signal.astock.job.monitor_stock_zh_a_min --mode event
python -m freshquant.position_management.worker --interval 3
python -m freshquant.tpsl.tick_listener
```

### 调 Symphony 正式服务

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:40123/api/v1/state
```

## 当前阶段的运行风险

- Docker 里的 Mongo/Redis 与宿主机 broker/xtdata 之间必须通过宿主机端口对齐，否则交易链会出现“页面正常、worker 无数据”。
- Guardian event 模式要求 `monitor.xtdata.mode=guardian_1m`；模式不对时进程会启动但不会真正处理 bar 更新。
- Runtime Observability 采用旁路写盘，日志队列满时允许丢事件；排障时要同时对照业务集合，而不是只看 runtime 页面。
