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

- `ta_backend` 启动时会把 `third_party/tradingagents-cn/.env` 挂载到容器内 `/app/.env`
- `third_party/tradingagents-cn/app/core/config.py` 会在进程启动时显式 `load_dotenv()`，确保：
  - `Pydantic Settings`
  - `TradingAgents` 内核
  - `DeepSeek/Tushare` 这类直接读取 `os.getenv()` 的模块
  使用同一份配置
- 仓库根目录 `.env` 只保留 FreshQuant 基础设施变量，不再承载 TradingAgents-CN 的模型和数据源密钥
- `docker/tradingagents/.env.example` 仅作为变量参考模板
- 要完成股票分析，至少需要在 `third_party/tradingagents-cn/.env` 中配置：
  - `DEEPSEEK_API_KEY`
  - `DEEPSEEK_BASE_URL=https://api.deepseek.com`
  - `DEEPSEEK_ENABLED=true`
  - `TUSHARE_TOKEN`
  - `TUSHARE_ENABLED=true`
  - `DEFAULT_CHINA_DATA_SOURCE=tushare`

补充说明：

- 这次已经把本地 `third_party/tradingagents-cn/.env` 的重复键清理掉，保留首个定义并统一了上述默认值。
- 如果 `DEEPSEEK_API_KEY` 或 `TUSHARE_TOKEN` 仍是 `your_*` 占位值，容器能启动，但真实分析一定失败。

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
- 默认 A 股数据源优先级会初始化为：
  - `Tushare`
  - `AKShare`
  - `BaoStock`
- 默认分析模型会初始化为：
  - `quick_analysis_model=deepseek-chat`
  - `deep_analysis_model=deepseek-reasoner`

说明：

- 本地接入层已经正式注册 `deepseek-reasoner`，并将其加入 `TradingAgents-CN` 的默认模型目录、能力声明与 provider 映射。
- `deepseek-reasoner` 只作为深度分析模型使用；快速分析仍固定为 `deepseek-chat`，避免首轮分析阶段被重推理模型拖慢。
- 如果 `deepseek-reasoner` 在工具调用链路出现兼容性异常，后端只会把 `deep_analysis_model` 自动回退到 `deepseek-chat`，任务继续执行。

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

- `third_party/tradingagents-cn/.env` 中是否有可用 `DEEPSEEK_API_KEY`
- `third_party/tradingagents-cn/.env` 中是否有可用 `TUSHARE_TOKEN`
- `ta_backend` 日志里是否出现模型或数据源鉴权失败
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

### 7.3 当前真实验收状态（2026-03-07）

- 验收标的：`002682`
- 最近一次完整跑通任务：`c4ffec0d-5878-4cdd-8c45-35cdc36db6e0`
- 任务完成时间：`2026-03-07 01:36:04`（Asia/Shanghai）
- 最终建议：`卖出`
- 置信度：`0.85`
- 关键模型证据：
  - `analysis_tasks.result.performance_metrics.llm_config.deep_think_model=deepseek-reasoner`
  - `analysis_tasks.result.performance_metrics.llm_config.quick_think_model=deepseek-chat`
  - `analysis_tasks.result.detailed_analysis.model_info=ChatDeepSeek:deepseek-reasoner`
- 已确认打通的链路：
  - 登录
  - 创建任务
  - `/app/.env` 挂载并加载到进程环境
  - `Tushare > AKShare > BaoStock` 默认优先级生效
  - `quick_analysis_model=deepseek-chat`
  - `deep_analysis_model=deepseek-reasoner`
  - Mongo 本地数据检查
  - Redis 进度初始化
  - 多智能体分析全流程完成
  - `deepseek-reasoner` 深度模型能力校验通过
  - 最终结果落到 Mongo
- 当前已确认修复：
  - `ta_backend` 运行容器实际挂载工作树 `third_party/tradingagents-cn/.env`
  - `your_*` 占位密钥不会再覆盖真实 `TUSHARE_TOKEN` / `DEEPSEEK_API_KEY`
  - `memory` 模块在缺少有效 embedding provider 时会直接禁用，不再触发 `DashScope InvalidApiKey`
  - `deepseek-reasoner` 已写入活动配置和 DeepSeek 模型目录，启动时自动补齐
  - 本次真实任务日志中未出现 `deepseek-reasoner -> deepseek-chat` 回退
  - 本轮真实任务执行期间，后端日志未再出现 `DashScope API错误` / `InvalidApiKey`
