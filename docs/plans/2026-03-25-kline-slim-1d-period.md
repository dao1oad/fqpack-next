# Kline Slim 1D Period Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 `kline-slim` 增加 `1d` 周期，并让它接入现有 `realtimeCache` 读路径而不改变分钟级 miss 行为。

**Architecture:** 前端仅扩展周期枚举和相关展示配置；后端复用 `/api/stock_data -> to_backend_period -> get_redis_cache_key -> get_data_v2` 现有链路，把 `1d` 纳入支持读取 Redis 的周期集合，同时保留 `endDate` 绕过规则和 fallback 逻辑。文档同步到 `docs/current`，确保用户能理解 `1d` 的使用和缓存边界。

**Tech Stack:** Vue, Node test runner, Flask route module, pytest, Redis-backed memoize, PowerShell, git/GitHub

---

### Task 1: 前端周期枚举接入 `1d`

**Files:**
- Modify: `morningglory/fqwebui/src/views/js/kline-slim-chanlun-periods.mjs`
- Test: `morningglory/fqwebui/src/views/klineSlim.test.mjs`

**Step 1: Write the failing test**

在 `morningglory/fqwebui/src/views/klineSlim.test.mjs` 增加最小测试，断言 `1d` 会出现在支持周期列表中，并且 `normalizeChanlunPeriod('1d')` 返回 `1d`。

**Step 2: Run test to verify it fails**

Run: `node --test src/views/klineSlim.test.mjs`
Expected: FAIL，原因是当前 `1d` 不在支持周期中。

**Step 3: Write minimal implementation**

在 `morningglory/fqwebui/src/views/js/kline-slim-chanlun-periods.mjs`：
- 把 `1d` 加入 `SUPPORTED_CHANLUN_PERIODS`
- 补齐 `PERIOD_STYLE_MAP`
- 补齐 `PERIOD_WIDTH_FACTOR`
- 补齐 `PERIOD_DURATION_MS`

**Step 4: Run test to verify it passes**

Run: `node --test src/views/klineSlim.test.mjs`
Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/js/kline-slim-chanlun-periods.mjs morningglory/fqwebui/src/views/klineSlim.test.mjs
git commit -m "test: add 1d kline slim frontend coverage"
```

### Task 2: 后端允许 `1d` 走 `realtimeCache` 读取路径

**Files:**
- Modify: `freshquant/util/period.py`
- Modify: `freshquant/tests/test_stock_data_route_cache.py`

**Step 1: Write the failing test**

在 `freshquant/tests/test_stock_data_route_cache.py` 新增测试：
- `period=1d` 且 `realtimeCache=1` 时，命中 Redis 直接返回缓存
- `period=1d` 且 miss Redis 时，fallback 到 `get_data_v2()`
- `period=1d` 且携带 `endDate` 时跳过 Redis

**Step 2: Run test to verify it fails**

Run: `pytest freshquant/tests/test_stock_data_route_cache.py -q`
Expected: FAIL，原因是 `1d` 当前不在 `is_supported_realtime_period()` 内。

**Step 3: Write minimal implementation**

在 `freshquant/util/period.py`：
- 让 `is_supported_realtime_period()` 包含 `1d`

保持 `get_redis_cache_key()` 和 `to_backend_period()` 现有语义不变。

**Step 4: Run test to verify it passes**

Run: `pytest freshquant/tests/test_stock_data_route_cache.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/util/period.py freshquant/tests/test_stock_data_route_cache.py
git commit -m "feat: allow 1d realtime cache reads"
```

### Task 3: 验证 `/api/stock_data` 现有 fallback 行为未被破坏

**Files:**
- Modify: `freshquant/tests/test_stock_data_route_cache.py`

**Step 1: Write the failing/guard test**

补一条分钟周期守卫测试，断言分钟级 miss 后仍然 fallback 到 `get_data_v2()`，而不是产生新的写回行为。

**Step 2: Run test to verify it fails if behavior regresses**

Run: `pytest freshquant/tests/test_stock_data_route_cache.py -q`
Expected: 当前应保持 PASS；该测试用于防回归，不要求先红。

**Step 3: Write minimal implementation**

如果现有测试已经覆盖，无需额外实现；只保留测试说明和必要命名优化。

**Step 4: Run test to verify it passes**

Run: `pytest freshquant/tests/test_stock_data_route_cache.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/tests/test_stock_data_route_cache.py
git commit -m "test: guard stock data fallback cache behavior"
```

### Task 4: 同步当前文档

**Files:**
- Modify: `docs/current/modules/kline-webui.md`

**Step 1: Write the failing check**

人工核对 `docs/current/modules/kline-webui.md` 是否仍然写着最大周期到 `30m` 或未说明 `1d` 的缓存边界。

**Step 2: Run check to verify docs gap exists**

Run: `Select-String -Path docs/current/modules/kline-webui.md -Pattern "30m|1d|realtimeCache"`
Expected: 能看出现有文档未覆盖本次行为。

**Step 3: Write minimal implementation**

更新文档，说明：
- `kline-slim` 支持 `1d`
- `1d` 复用现有 `realtimeCache` 读取路径
- `endDate` 历史请求仍然绕过 Redis

**Step 4: Run check to verify docs updated**

Run: `Select-String -Path docs/current/modules/kline-webui.md -Pattern "1d|realtimeCache"`
Expected: PASS

**Step 5: Commit**

```bash
git add docs/current/modules/kline-webui.md
git commit -m "docs: document kline slim 1d period"
```

### Task 5: 完整验证、PR、合并、部署

**Files:**
- Modify: none

**Step 1: Run targeted tests**

Run: `pytest freshquant/tests/test_stock_data_route_cache.py -q`
Run: `node --test src/views/klineSlim.test.mjs`

**Step 2: Run broader verification**

Run: `node --test src/views/js/subject-price-guides.test.mjs src/views/js/kline-slim-price-panel.test.mjs src/views/js/kline-slim-chart-price-guides.test.mjs src/views/js/kline-slim-chart-controller.test.mjs src/views/klineSlim.test.mjs`
Run: `npm run build`

**Step 3: Review diff**

Run: `git status --short`
Run: `git diff --stat origin/main...HEAD`

**Step 4: Land the change**

创建 PR，等待 CI，合并到远端 `main`，然后把本地 `main` 同步到最新远端提交。

**Step 5: Deploy and cleanup**

Run: `powershell -ExecutionPolicy Bypass -File script/ci/run_production_deploy.ps1 -CanonicalRoot D:\fqpack\freshquant-2026.2.23 -MirrorRoot D:\fqpack\freshquant-2026.2.23\.worktrees\main-deploy-production -MirrorBranch deploy-production-main`

完成后执行健康检查、清理 feature branch/worktree。
