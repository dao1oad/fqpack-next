# 当前部署

## Docker 并行部署

```powershell
docker compose -f docker/compose.parallel.yaml up -d --build
```

## 模块部署矩阵

- `freshquant/rear/**`：重部署 API
- `freshquant/order_management/**`：重部署后端/API，必要时重启相关 worker
- `freshquant/position_management/**`：重启 `position_management.worker`
- `freshquant/tpsl/**`：重启 `tpsl.tick_listener`
- `freshquant/market_data/**`：重启 producer / consumer / reference-data worker
- `morningglory/fqwebui/**`：重构建并部署 Web UI
- `morningglory/fqdagster/**`：重部署 Dagster
- `third_party/tradingagents-cn/**`：重部署 `ta_backend` / `ta_frontend`
- `runtime/symphony/**`：同步宿主机并重启 orchestrator

## 健康检查

- API 服务端口可访问，关键路由返回正常
- Web 页面可打开，关键页面不空白
- Dagster UI 或作业可加载
- TradingAgents health 接口正常
- Symphony 状态接口正常
- 相关 worker 未启动即退

## Done 规则

任务只有在以下全部完成后才算结束：

- merge
- ci
- docs sync
- deploy
- health check
- cleanup
