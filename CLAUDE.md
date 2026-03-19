# FreshQuant

> Windows PowerShell 5.1 查看中文文档乱码时，先执行：`. .\script\pwsh_utf8.ps1`

## 项目定位

`D:\fqpack\freshquant-2026.2.23` 是目标架构仓库。当前阶段的重点是：

- 修复潜在 bug
- 收敛当前系统事实
- 保持部署、健康检查和 cleanup 可重复

## 正式真值

- GitHub Issue：任务入口
- GitHub Draft PR：唯一 `Design Review`
- GitHub PR + CI：代码交付真值
- Deploy + Health Check + Cleanup：运行交付真值

## 文档入口

开始任务前，优先阅读：

- `docs/index.md`
- `docs/current/overview.md`
- `docs/current/architecture.md`
- `docs/current/runtime.md`
- `docs/current/deployment.md`
- `docs/current/troubleshooting.md`

## 常用命令

```powershell
uv run fqctl --help
uv run pytest freshquant/tests -q
uv run python -m freshquant.rear.api_server --port 5000
uv run python -m freshquant.market_data.xtdata.market_producer
uv run python -m freshquant.xt_account_sync.worker --once
uv run python -m freshquant.tpsl.tick_listener
docker compose -f docker/compose.parallel.yaml up -d --build
```

## 当前架构概览

- `freshquant/market_data/xtdata/`：XTData 实时行情链路
- `freshquant/strategy/`：Guardian 策略
- `freshquant/order_management/`：订单受理、主账本、投影、对账
- `freshquant/position_management/`：仓位状态与提交门禁
- `freshquant/tpsl/`：独立止盈止损
- `freshquant/rear/`：Flask API
- `freshquant/data/`：股票池、持仓、Gantt / Shouban30 读模型
- `morningglory/fqwebui/`：Vue 3 前端
- `morningglory/fqdagster/`：Dagster
- `third_party/tradingagents-cn/`：TradingAgents-CN

## 运行与部署

- Docker 并行部署：`docs/current/deployment.md`
- 当前运行面：`docs/current/runtime.md`
- 配置模板：`deployment/examples/`

## 约束

- 默认使用简体中文
- 当前事实变化时同步更新 `docs/current/**`
- 禁止在本地 `main` 直接开发
- 代码更新后必须重部署对应模块
