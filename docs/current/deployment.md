# 当前部署

## 部署原则

- 代码改动后，受影响模块必须重新部署；只合并不部署不算完成。
- Docker 并行环境用于承载通用服务与前端；宿主机负责需要直连券商、XTData 或 Windows 资源的进程。
- 部署动作结束后必须做健康检查；健康检查通过后才进入 cleanup。
- 当前 Done 判定固定为：`merge + ci + docs sync + deploy + health check + cleanup`。

## 常用部署命令

### 全量并行环境

```powershell
docker compose -f docker/compose.parallel.yaml up -d --build
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

### 宿主机同步 Python 依赖

```powershell
.\install.bat --skip-web
```

- `install.bat` 会先清理 `morningglory/fqchan01/python/build`，再在 `uv sync --frozen` 阶段对本地原生包 `fqchan01` 强制执行 `refresh + reinstall`，避免宿主机继续复用损坏的 `fqchan01` 源码构建产物或缓存。
- 如果部署目标包含 Guardian / Chanlun 相关宿主机链路，重装后应额外执行 `python -c "import fqchan01; print('IMPORT_OK')"` 做一次本地导入确认。

## 模块部署矩阵

| 变更路径 | 需要部署的模块 | 最低动作 |
| --- | --- | --- |
| `freshquant/rear/**` | API Server | 重建 `fq_apiserver` 容器或重启 API 进程 |
| `freshquant/order_management/**` | 订单管理、API、broker/ingest 相关宿主机进程 | 重建 API；若涉及 submit/ingest/gateway，同步重启宿主机交易链进程 |
| `freshquant/position_management/**` | 仓位管理 | 重启 `python -m freshquant.position_management.worker --interval 3` |
| `freshquant/tpsl/**` | TPSL | 重启 `python -m freshquant.tpsl.tick_listener` |
| `freshquant/market_data/**` | XTData producer / consumer | 重启 producer、consumer；必要时重新 prewarm |
| `freshquant/strategy/**` 或 `freshquant/signal/**` | Guardian | 重启 `python -m freshquant.signal.astock.job.monitor_stock_zh_a_min --mode event` |
| `sunflower/QUANTAXIS/**` | QAWebServer 与依赖 QUANTAXIS 的宿主机策略链路 | 重建 `fq_qawebserver`；同步重启受影响宿主机 Guardian / strategy 进程 |
| `freshquant/data/gantt*` / `freshquant/shouban30_pool_service.py` | Gantt/Shouban30 读模型与 API | 重建 API；必要时重跑 Dagster 任务 |
| `morningglory/fqwebui/**` | Web UI | 重建 `fq_webui` |
| `morningglory/fqdagster/**` / `morningglory/fqdagsterconfig/**` | Dagster | 重启 `fq_dagster_webserver` 与 `fq_dagster_daemon` |
| `third_party/tradingagents-cn/**` | TradingAgents-CN | 重建 `ta_backend` 与 `ta_frontend` |
| `runtime/symphony/**` | 正式 orchestrator | `sync_freshquant_symphony_service.ps1` + `reinstall_freshquant_symphony_service.ps1` 或激活脚本 |

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

### Docker 组件状态

```powershell
docker compose -f docker/compose.parallel.yaml ps
```

## 部署后必须确认的事实

- API 蓝图能返回，不是只监听端口。
- Web UI 页面不是空白页，关键页面 `/gantt`、`/gantt/shouban30`、`/position-management`、`/tpsl`、`/runtime-observability` 能打开。
- XTData 相关修改后，producer/consumer 日志持续产出，Redis 队列不持续堆积。
- 如果改了运行观测或 XTData runtime 埋点，确认 `/runtime-observability` 页面能看到 `xt_producer` / `xt_consumer` 的 5 分钟 heartbeat 与关键指标，而不是只看到启动事件。
- TPSL / Position worker 修改后，进程没有“启动即退”。
- Symphony 修改后，Issue 领取、Design Review、cleanup 闭环仍然可用。

## Cleanup 要求

- 删除已合并远端 feature branch。
- 删除当前 issue 的 Symphony workspace 或本次临时 worktree。
- 清理临时脚本、临时 compose override、过期 artifacts。
- 不清理 Mongo、Redis、`.venv`、正式日志目录或在线服务。
