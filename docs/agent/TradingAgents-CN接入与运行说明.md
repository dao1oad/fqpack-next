---
name: tradingagents-cn-integration-guide
description: FreshQuant 中以 Docker 方式接入 TradingAgents-CN 的运行说明，包含端口、环境变量、登录、分析请求与排障边界。
---

# TradingAgents-CN 接入与运行说明

## 1. 运行边界

- 第三方源码目录：`third_party/tradingagents-cn/`
- 本阶段只启动：
  - `ta_backend`
  - `ta_frontend`
- 共享基础设施：
  - MongoDB：`fq_mongodb`
  - Redis：`fq_redis`
- 逻辑隔离：
  - MongoDB：`tradingagents_cn`
  - Redis：`db 8`
- 当前接入按本仓库现状使用无鉴权的 `fq_mongodb` / `fq_redis`，因此会在 Compose 中显式覆盖上游镜像自带的 Mongo/Redis 用户名与密码。

## 2. 环境变量来源

- `ta_backend` 通过 `docker/compose.parallel.yaml` 的 `env_file: ../.env` 读取仓库根目录 `.env`
- `docker/tradingagents/.env.example` 仅作为变量参考模板
- 要完成股票分析，至少需要在根目录 `.env` 中配置：
  - `DASHSCOPE_API_KEY` 或 `DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY` 之一
- 如需启用 Tushare 路径，再补：
  - `TUSHARE_TOKEN`

## 3. 启动

在仓库根目录执行：

```powershell
docker compose -f docker/compose.parallel.yaml up -d --build fq_mongodb fq_redis ta_backend ta_frontend
```

查看状态：

```powershell
docker compose -f docker/compose.parallel.yaml ps
```

访问入口：

- 前端：`http://127.0.0.1:13080/`
- 后端健康检查：`http://127.0.0.1:13000/api/health`

## 4. 首次启动行为

- `ta_backend` 会保留上游原生行为，在应用启动后触发一次股票基础信息同步。
- `ta_backend` 启动命令会额外确保默认管理员存在：
  - 用户名：`admin`
  - 密码：`admin123`
- 这是接入层自动化，不改第三方业务代码。

## 5. 登录与单股分析

### 5.1 登录

```powershell
$login = Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:13000/api/auth/login `
  -ContentType 'application/json' `
  -Body '{"username":"admin","password":"admin123"}'

$token = $login.data.access_token
$headers = @{ Authorization = "Bearer $token" }
```

### 5.2 提交单股分析

```powershell
$body = @'
{
  "symbol": "000001"
}
'@

$task = Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:13000/api/analysis/single `
  -Headers $headers `
  -ContentType 'application/json' `
  -Body $body

$taskId = $task.data.task_id
```

说明：

- 目前建议首轮验证先只传 `symbol`，让后端使用其默认参数。
- 如果在 Windows PowerShell 5.1 里直接内联中文 JSON，`A股`、`标准` 这类字段可能会被编码成 `A?`，从而在后端被判定为“不支持的市场类型”。
- 如果确实要显式传中文参数，优先使用 UTF-8 文件、`py` 脚本，或先执行 `. .\script\pwsh_utf8.ps1`。

### 5.3 查询任务状态和结果

```powershell
Invoke-RestMethod `
  -Method Get `
  -Uri "http://127.0.0.1:13000/api/analysis/tasks/$taskId/status" `
  -Headers $headers

Invoke-RestMethod `
  -Method Get `
  -Uri "http://127.0.0.1:13000/api/analysis/tasks/$taskId/result" `
  -Headers $headers
```

## 6. 本地写入位置

- MongoDB：
  - `analysis_tasks`
  - `analysis_reports`
  - `stock_basic_info`
  - `market_quotes`
  - `stock_news`
  - 以及上游相关配置/同步集合
- Redis：
  - 任务进度、状态、通知、缓存
- 本地挂载目录：
  - `runtime/tradingagents-cn/data`
  - `runtime/tradingagents-cn/logs`

## 7. 排障

### 7.1 后端起来但分析失败

优先检查：

- 根目录 `.env` 中是否有可用 LLM Key
- `ta_backend` 日志里是否出现数据源鉴权失败
- `fq_mongodb` 中是否已创建 `tradingagents_cn`
- `fq_redis` 的 `db 8` 是否可写

命令：

```powershell
docker compose -f docker/compose.parallel.yaml logs --tail 200 ta_backend
docker compose -f docker/compose.parallel.yaml logs --tail 200 ta_frontend
```

### 7.2 前端 502 或 WebSocket 不通

- 确认 `ta_backend` 为 `healthy`
- 确认 `ta_frontend` 已加载 `docker/tradingagents/frontend.nginx.conf`
- 当前反代路径：
  - `/api/*`
  - `/api/ws/*`

### 7.3 当前真实验收状态（2026-03-06）

- `000001` 单股任务已经可以完成：
  - 登录
  - 创建任务
  - Mongo 本地数据检查
  - Redis 进度初始化
  - 进入 `agent_analysis` 多智能体分析阶段
- 当前主要阻塞不是本地数据，而是大模型凭证：
  - DashScope 实际返回 `401 invalid_api_key`
  - Mongo `analysis_tasks.last_error` 会记录 `大模型 API Key 无效`
- 这意味着当前接入层、本地缓存读取、按需补数和任务状态写入已经联通；后续若要跑完整分析闭环，需先替换有效的 LLM API Key。
