# FreshQuant

> Windows PowerShell 5.1 查看中文文档乱码时，先执行：`. .\script\pwsh_utf8.ps1`

## 项目定位

`D:\fqpack\freshquant-2026.2.23` 是目标架构仓库，不是旧仓 `D:\fqpack\freshquant` 的镜像。当前仓库已经落地：

- XTData producer / consumer
- ETF `qfq`
- 订单管理 / 仓位管理 / TPSL
- Gantt / Shouban30 读模型与页面
- KlineSlim
- TradingAgents-CN 并行部署与配置治理

开始任务前，优先阅读：

- `docs/agent/index.md`
- `docs/agent/项目目标与代码现状调研.md`
- `docs/migration/progress.md`
- `docs/migration/breaking-changes.md`

## 运行环境

- 宿主机统一使用项目根目录 `.venv`
- 解释器版本固定为 `Python 3.12.x`
- 依赖统一由 `uv.lock` 驱动
- Docker 容器内分别构建：
  - `/freshquant/.venv`
  - `/app/.venv`（TradingAgents-CN）

## 常用命令

```powershell
uv run fqctl --help
uv run pytest freshquant/tests -q
uv run python -m freshquant.rear.api_server --port 5000
uv run python -m freshquant.gateway.tdxhq --port 5001
uv run python -m freshquant.market_data.xtdata.market_producer
uv run python -m freshquant.position_management.worker --once
uv run python -m freshquant.tpsl.tick_listener
docker compose -f docker/compose.parallel.yaml up -d --build
```

## 当前架构概览

### 1. 主包 `freshquant/`

当前重点子域：

- `market_data/xtdata/`：XTData 实时行情事件链路
- `order_management/`：订单受理、主账本、投影、对账
- `position_management/`：融资账户仓位状态与策略门禁
- `tpsl/`：独立止盈止损模块
- `rear/`：Flask API（`stock/future/general/gantt/order/tpsl`）
- `gateway/`：TDXHQ Tornado 网关
- `data/`：股票池、持仓、Gantt/Shouban30 读模型
- `strategy/`：Guardian 等策略入口

### 2. 子项目 `morningglory/`

- `fqwebui`：Vue 3 前端
- `fqdagster`：Dagster 工作流
- `fqxtrade`：XT / MiniQMT broker 与 puppet
- `fqcopilot`：fullcalc 等辅助能力
- `fqchan01..06`：缠论算法包

### 3. 第三方 `third_party/`

- `tradingagents-cn/`：独立 FastAPI backend + Vue frontend

## 数据流

FreshQuant 主链路：

```text
行情源/XTData/TDX -> Redis/Mongo -> Strategy/Order Management -> Broker/MiniQMT
```

TradingAgents-CN 独立链路：

```text
ta_frontend -> ta_backend -> tradingagents_cn(Mongo) / Redis db 8
```

## 配置管理

FreshQuant 当前配置来源：

- `freshquant/config.py` 的 Dynaconf
- 仓库根 `.env`
- Mongo `freshquant.params`

当前重点配置层：

- `order_management.*`
- `position_management.*`
- `mongodb.gantt_db`
- `xtquant.*`

TradingAgents-CN 当前按 RFC `0016` 收敛为：

- 根 `.env` 单一真相源
- Compose `env_file` 注入
- 启动期同步 Mongo 配置镜像
- 运行期环境变量优先

## 技术栈

| 类别 | 当前实现 |
|------|----------|
| Python 运行面 | Python 3.12 + uv |
| Web | Flask、Tornado、Vue 3 |
| 工作流 / 后台任务 | Dagster、Huey |
| 数据 | MongoDB、Redis |
| 交易 | XT / MiniQMT |
| 第三方分析 | TradingAgents-CN（FastAPI） |
| 测试 | pytest |

## 运行与部署

- Docker 并行部署：`docs/agent/Docker并行部署指南.md`
- 宿主机 XT/XTData 对齐 Docker Mongo：见 RFC `0010`
- TradingAgents-CN 运行说明：`docs/agent/TradingAgents-CN接入与运行说明.md`

## 约束

- 默认使用简体中文
- 先看 RFC / progress / breaking changes，再改代码
- 禁止在本地 `main` 直接开发，必须使用 `git worktree + feature branch`
