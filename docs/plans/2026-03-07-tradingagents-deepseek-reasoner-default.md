# TradingAgents-CN DeepSeek Reasoner Default Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 FreshQuant 接入的 `TradingAgents-CN` 中正式支持 `deepseek-reasoner`，将其设为默认 `deep_analysis_model`，并用 `002682` 完成真实任务验收。

**Architecture:** 方案采用“模型注册 + 能力声明 + provider 映射 + 运行态配置迁移 + 精准回退”五层同步改造。默认快速模型保持 `deepseek-chat`，默认深度模型切到 `deepseek-reasoner`；若深度思考模型在工具调用链失败，则仅回退深度模型到 `deepseek-chat` 继续任务。

**Tech Stack:** Python 3.12, FastAPI, MongoDB, Redis, Docker Compose, pytest

---

### Task 1: 写失败测试覆盖 `deepseek-reasoner` 默认配置

**Files:**
- Modify: `third_party/tradingagents-cn/tests/test_tushare_deepseek_defaults.py`
- Test: `third_party/tradingagents-cn/tests/test_tushare_deepseek_defaults.py`

**Step 1: Write the failing test**

新增断言：

- `AnalysisParameters().deep_analysis_model == "deepseek-reasoner"`
- `_create_default_config().system_settings["deep_analysis_model"] == "deepseek-reasoner"`
- 默认目录中包含 `deepseek-reasoner`
- provider 映射能把 `deepseek-reasoner` 识别为 `deepseek`

**Step 2: Run test to verify it fails**

Run:

```powershell
py -m pytest third_party/tradingagents-cn/tests/test_tushare_deepseek_defaults.py -q
```

Expected:

- 失败点明确落在 `deepseek-reasoner` 尚未注册或默认值仍是 `deepseek-chat`

**Step 3: Write minimal implementation**

最小补齐：

- `app/constants/model_capabilities.py`
- `app/services/config_service.py`
- `app/services/simple_analysis_service.py`

**Step 4: Run test to verify it passes**

Run:

```powershell
py -m pytest third_party/tradingagents-cn/tests/test_tushare_deepseek_defaults.py -q
```

Expected:

- 新增断言通过

### Task 2: 写失败测试覆盖工具调用失败时的深度模型回退

**Files:**
- Modify: `third_party/tradingagents-cn/tests/test_tushare_deepseek_defaults.py`
- Modify: `third_party/tradingagents-cn/app/services/simple_analysis_service.py`
- Test: `third_party/tradingagents-cn/tests/test_tushare_deepseek_defaults.py`

**Step 1: Write the failing test**

新增一个纯函数级测试：

- 输入 `deep_model="deepseek-reasoner"` 和包含 `tool_calls` / `unsupported tools` 的异常消息
- 断言返回应回退到 `deepseek-chat`
- 对非工具调用异常断言不回退

**Step 2: Run test to verify it fails**

Run:

```powershell
py -m pytest third_party/tradingagents-cn/tests/test_tushare_deepseek_defaults.py -q
```

Expected:

- 因缺少回退判定/回退函数而失败

**Step 3: Write minimal implementation**

在 `simple_analysis_service.py` 中新增：

- 深度模型工具调用异常识别函数
- 深度模型回退函数
- 在分析执行阶段调用该逻辑

**Step 4: Run test to verify it passes**

Run:

```powershell
py -m pytest third_party/tradingagents-cn/tests/test_tushare_deepseek_defaults.py -q
```

Expected:

- 回退测试通过

### Task 3: 实现运行态配置迁移

**Files:**
- Create or Modify: `docker/tradingagents/*` repo 侧 bootstrap 脚本
- Modify: `docker/compose.parallel.yaml`
- Modify: `docs/agent/TradingAgents-CN接入与运行说明.md`

**Step 1: Write the failing verification**

先通过当前 API/数据库读取，确认运行态仍是旧值：

```powershell
$login = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:13000/api/auth/login' -ContentType 'application/json' -Body '{"username":"admin","password":"admin123"}'
$token = $login.data.access_token
$headers = @{ Authorization = "Bearer $token" }
Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:13000/api/config/settings' -Headers $headers
```

Expected:

- `deep_analysis_model` 仍不是 `deepseek-reasoner`

**Step 2: Write minimal implementation**

实现一个 repo 侧 bootstrap：

- 保证 admin 用户存在
- 保证活动配置深度模型默认为 `deepseek-reasoner`
- 保证需要的模型目录/能力数据可用

**Step 3: Rebuild and run**

Run:

```powershell
docker compose -f docker/compose.parallel.yaml up -d --build ta_backend ta_frontend
```

**Step 4: Verify runtime settings**

再次读取 `/api/config/settings`

Expected:

- `quick_analysis_model=deepseek-chat`
- `deep_analysis_model=deepseek-reasoner`

### Task 4: 跑 `002682` 真实分析任务验收

**Files:**
- Modify: `docs/agent/TradingAgents-CN接入与运行说明.md`
- Modify: `docs/migration/progress.md`

**Step 1: Submit real analysis**

Run:

```powershell
$login = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:13000/api/auth/login' -ContentType 'application/json' -Body '{"username":"admin","password":"admin123"}'
$token = $login.data.access_token
$headers = @{ Authorization = "Bearer $token" }
$body = '{"symbol":"002682"}'
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:13000/api/analysis/single' -Headers $headers -ContentType 'application/json' -Body $body
```

**Step 2: Poll until completion**

持续轮询：

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:13000/api/analysis/tasks/<task_id>/status" -Headers $headers
```

Expected:

- 最终状态为 `completed`

**Step 3: Verify result and actual model usage**

Run:

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:13000/api/analysis/tasks/<task_id>/result" -Headers $headers
```

Expected:

- 任务完成
- 结果落库
- 能证明深度模型使用了 `deepseek-reasoner`，或者出现回退时能证明“先尝试 reasoner，再回退到 chat 完成”

**Step 4: Commit**

```powershell
git add docker/compose.parallel.yaml docker/tradingagents docs/agent/TradingAgents-CN接入与运行说明.md docs/migration/progress.md docs/plans/2026-03-07-tradingagents-deepseek-reasoner-default-design.md docs/plans/2026-03-07-tradingagents-deepseek-reasoner-default.md third_party/tradingagents-cn/app/constants/model_capabilities.py third_party/tradingagents-cn/app/core/unified_config.py third_party/tradingagents-cn/app/services/config_service.py third_party/tradingagents-cn/app/services/simple_analysis_service.py third_party/tradingagents-cn/tests/test_tushare_deepseek_defaults.py
git commit -m "feat: default tradingagents deep analysis to deepseek reasoner"
```
