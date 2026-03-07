# TradingAgents-CN Env SOT Sync Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 `ta_backend` 的 DeepSeek/Tushare 配置收敛到仓库根 `.env`，并在启动时自动同步到 Mongo 与运行时链路。

**Architecture:** 通过新增启动期 `.env -> Mongo` 同步服务，把根 `.env` 中的 DeepSeek/Tushare 值写入 `llm_providers` 与激活 `system_configs`，再统一 `config_bridge` / Tushare 读取优先级为 `.env > DB > fallback`，同时移除镜像内 `.env.docker` 运行期干扰。

**Tech Stack:** FastAPI lifespan、Motor/PyMongo、Pydantic models、Docker Compose、pytest

---

### Task 1: 写启动同步回归测试

**Files:**
- Create: `third_party/tradingagents-cn/tests/test_env_config_sync_service.py`
- Read: `third_party/tradingagents-cn/app/models/config.py`

**Step 1: Write the failing test**

写两个最小测试：

- `test_apply_env_runtime_config_updates_deepseek_and_tushare`
- `test_apply_env_runtime_config_adds_missing_defaults`

断言：

- DeepSeek 厂家级、模型级配置被根 `.env` 值覆盖
- Tushare 数据源级配置被根 `.env` 值覆盖
- 缺失时自动补齐 `deepseek-chat` / `deepseek-reasoner` / `Tushare`

**Step 2: Run test to verify it fails**

Run: `pytest third_party/tradingagents-cn/tests/test_env_config_sync_service.py -q`

Expected: FAIL，因为同步服务尚不存在。

**Step 3: Write minimal implementation**

新增 `app/services/env_config_sync_service.py`，先实现纯函数和最小同步入口。

**Step 4: Run test to verify it passes**

Run: `pytest third_party/tradingagents-cn/tests/test_env_config_sync_service.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add third_party/tradingagents-cn/tests/test_env_config_sync_service.py third_party/tradingagents-cn/app/services/env_config_sync_service.py
git commit -m "feat: add env runtime config sync service"
```

### Task 2: 写优先级回归测试

**Files:**
- Create: `third_party/tradingagents-cn/tests/test_tushare_env_priority.py`
- Modify: `third_party/tradingagents-cn/app/core/config_bridge.py`
- Modify: `third_party/tradingagents-cn/tradingagents/dataflows/providers/china/tushare.py`
- Modify: `third_party/tradingagents-cn/tradingagents/dataflows/data_source_manager.py`

**Step 1: Write the failing test**

新增测试：

- `test_bridge_config_keeps_env_tushare_token_over_database`
- `test_tushare_provider_prefers_env_token_over_database`

断言：

- `bridge_config_to_env()` 不会再用 DB 旧值覆盖 `TUSHARE_TOKEN`
- `TushareProvider` 优先使用环境变量 Token

**Step 2: Run test to verify it fails**

Run: `pytest third_party/tradingagents-cn/tests/test_tushare_env_priority.py -q`

Expected: FAIL，当前实现仍然是 DB 优先。

**Step 3: Write minimal implementation**

将 Tushare 相关桥接和消费优先级统一改为 `.env > DB > fallback`。

**Step 4: Run test to verify it passes**

Run: `pytest third_party/tradingagents-cn/tests/test_tushare_env_priority.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add third_party/tradingagents-cn/tests/test_tushare_env_priority.py third_party/tradingagents-cn/app/core/config_bridge.py third_party/tradingagents-cn/tradingagents/dataflows/providers/china/tushare.py third_party/tradingagents-cn/tradingagents/dataflows/data_source_manager.py
git commit -m "fix: prefer env token for tushare runtime"
```

### Task 3: 接入启动流程与 Docker

**Files:**
- Modify: `third_party/tradingagents-cn/app/main.py`
- Modify: `third_party/tradingagents-cn/Dockerfile.backend`
- Modify: `.env`

**Step 1: Write the failing integration expectation**

记录手工验证点：

- 容器内 `DEEPSEEK_API_KEY` / `TUSHARE_TOKEN` 非空
- `llm_providers.deepseek` 和激活 `system_configs` 已被修正

**Step 2: Implement**

- 在 `lifespan` 中调用启动同步服务
- 删除 `COPY .env.docker ./.env`
- 把当前有效的 DeepSeek/Tushare 值写入根 `.env`

**Step 3: Rebuild and verify**

Run: `docker compose -f docker/compose.parallel.yaml up -d --build ta_backend`

Run: `docker exec fqnext_20260223-ta_backend-1 sh -lc "printenv DEEPSEEK_API_KEY | wc -c; printenv TUSHARE_TOKEN | wc -c"`

Expected: 两个长度都大于 1

**Step 4: Verify Mongo mirror**

Run: `py -m ...` 查询 `tradingagents_cn.llm_providers` / `system_configs`

Expected: DeepSeek/Tushare 与根 `.env` 一致

**Step 5: Commit**

```bash
git add third_party/tradingagents-cn/app/main.py third_party/tradingagents-cn/Dockerfile.backend .env
git commit -m "fix: sync root env credentials into ta backend runtime"
```

### Task 4: 全链路验证与文档收尾

**Files:**
- Modify: `docs/migration/progress.md`
- Modify: `docs/migration/breaking-changes.md`
- Modify: `docs/rfcs/0016-tradingagents-env-sot-sync.md`

**Step 1: Run regression tests**

Run: `pytest third_party/tradingagents-cn/tests/test_env_config_sync_service.py third_party/tradingagents-cn/tests/test_tushare_env_priority.py third_party/tradingagents-cn/tests/test_task_center_api_key_fallback.py -q`

Expected: PASS

**Step 2: Run runtime verification**

Run:

- `docker exec fqnext_20260223-ta_backend-1 curl -fsS http://localhost:8000/api/health`
- 最小 DeepSeek 初始化验证
- 最小 Tushare 连接验证

**Step 3: Update docs**

- RFC 状态改为 `Done`
- `progress.md` 追加 0014
- `breaking-changes.md` 登记单一真相源语义

**Step 4: Final verification**

Run: `git diff --stat`

Expected: 仅包含本任务相关改动

**Step 5: Commit**

```bash
git add docs/rfcs/0016-tradingagents-env-sot-sync.md docs/migration/progress.md docs/migration/breaking-changes.md
git commit -m "docs: record tradingagents env source-of-truth sync"
```
