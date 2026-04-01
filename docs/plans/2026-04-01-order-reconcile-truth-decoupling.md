# Order Reconcile Truth Decoupling Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复 external reconcile 中价格漂移、确认与切片排布耦合、partial match 丢失挂接，以及 Guardian 对降级 entry 语义不足的问题。

**Architecture:** 在 reconciliation gap 上区分首次价格与最新价格；把 `AUTO_OPENED` 拆成真值确认和排布物化两阶段；统一解析 reconcile runtime params 并提供稳定 fallback；让 Guardian 和 runtime observability 显式表达降级状态。最终以 `om_position_entries` 先收敛真值，再由 slices 提供运营层语义。

**Tech Stack:** Python 3.12, pytest, Mongo-backed order management repositories, runtime observability

---

### Task 1: 锁定价格冻结与 gap 观测行为

**Files:**
- Modify: `freshquant/tests/test_order_management_reconcile.py`

**Step 1: Write the failing tests**

- 新增测试覆盖：
  - gap 首次创建后写入 `initial_* / latest_* / chosen_*`
  - 后续同一 gap 再次观测时只刷新 `latest_*`
  - `chosen_price_estimate` 默认保持首次发现价

**Step 2: Run test to verify it fails**

Run:
```powershell
D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pytest freshquant/tests/test_order_management_reconcile.py -q
```

Expected: 新测试因缺少字段或现有逻辑漂移而失败。

**Step 3: Write minimal implementation**

- 修改 `freshquant/order_management/reconcile/service.py`
- 在 gap 创建与更新路径引入 `initial_* / latest_* / chosen_*`
- 保持当前 source priority，但默认确认价固定为 `initial_price_estimate`

**Step 4: Run tests to verify it passes**

Run:
```powershell
D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pytest freshquant/tests/test_order_management_reconcile.py -q
```

**Step 5: Commit**

```powershell
git add freshquant/order_management/reconcile/service.py freshquant/tests/test_order_management_reconcile.py
git commit -m "feat: freeze inferred reconcile price snapshot"
```

### Task 2: 实现 `AUTO_OPENED` 两阶段确认

**Files:**
- Modify: `freshquant/order_management/reconcile/service.py`
- Modify: `freshquant/tests/test_order_management_reconcile.py`
- Modify: `freshquant/tests/test_order_reconcile_runtime_observability.py`

**Step 1: Write the failing tests**

- `grid_interval` 失败时：
  - gap 仍变成 `AUTO_OPENED`
  - entry 已落库
  - `arrange_status=DEGRADED`
- `lot_amount` 失败时行为同上
- 运行观测包含 `arrange_status / arrange_error_*`

**Step 2: Run tests to verify they fail**

Run:
```powershell
D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pytest freshquant/tests/test_order_management_reconcile.py freshquant/tests/test_order_reconcile_runtime_observability.py -q
```

**Step 3: Write minimal implementation**

- 把 `_confirm_open_gap()` 拆成：
  - 真值 entry 落库
  - arrangement 物化
- entry 新增降级字段
- arrangement 失败时保留 entry 并写降级元数据

**Step 4: Run tests to verify they pass**

Run:
```powershell
D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pytest freshquant/tests/test_order_management_reconcile.py freshquant/tests/test_order_reconcile_runtime_observability.py -q
```

**Step 5: Commit**

```powershell
git add freshquant/order_management/reconcile/service.py freshquant/tests/test_order_management_reconcile.py freshquant/tests/test_order_reconcile_runtime_observability.py
git commit -m "feat: decouple reconcile confirmation from arrangement"
```

### Task 3: 统一 reconcile runtime params 解析

**Files:**
- Modify: `freshquant/order_management/reconcile/service.py`
- Modify: `freshquant/order_management/ingest/xt_reports.py`
- Modify: `freshquant/tests/test_order_management_reconcile.py`
- Modify: `freshquant/tests/test_order_management_xt_ingest.py`

**Step 1: Write the failing tests**

- `resolve_reconcile_runtime_params()` 返回 grid/lot 值、来源、degraded 标记
- 任一解析失败时：
  - fallback 到 `1.03 / 3000`
  - 原始异常信息被保留到结果中

**Step 2: Run tests to verify they fail**

Run:
```powershell
D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pytest freshquant/tests/test_order_management_reconcile.py freshquant/tests/test_order_management_xt_ingest.py -q
```

**Step 3: Write minimal implementation**

- 引入统一 helper
- reconcile 和 xt ingest 共用这一层解析
- 去掉只保留包装错误、不保留上下文的旧行为

**Step 4: Run tests to verify they pass**

Run:
```powershell
D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pytest freshquant/tests/test_order_management_reconcile.py freshquant/tests/test_order_management_xt_ingest.py -q
```

**Step 5: Commit**

```powershell
git add freshquant/order_management/reconcile/service.py freshquant/order_management/ingest/xt_reports.py freshquant/tests/test_order_management_reconcile.py freshquant/tests/test_order_management_xt_ingest.py
git commit -m "refactor: unify reconcile runtime parameter resolution"
```

### Task 4: 补 Guardian 降级语义

**Files:**
- Modify: `freshquant/data/astock/holding.py`
- Modify: `freshquant/strategy/guardian.py`
- Modify: `freshquant/tests/test_guardian_strategy.py`
- Modify: `freshquant/tests/test_guardian_runtime_observability.py`

**Step 1: Write the failing tests**

- entry 已存在但没有 slices 时：
  - Guardian 不再记为“无持仓”
  - reason code 明确为 `no_arranged_fills` 或 `arrangement_degraded`
- degraded arrangement 不误导为持仓缺失

**Step 2: Run tests to verify they fail**

Run:
```powershell
D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pytest freshquant/tests/test_guardian_strategy.py freshquant/tests/test_guardian_runtime_observability.py -q
```

**Step 3: Write minimal implementation**

- 在 holding adapter 暴露 entry/slice 降级状态
- 调整 Guardian 日志与 decision branch

**Step 4: Run tests to verify they pass**

Run:
```powershell
D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pytest freshquant/tests/test_guardian_strategy.py freshquant/tests/test_guardian_runtime_observability.py -q
```

**Step 5: Commit**

```powershell
git add freshquant/data/astock/holding.py freshquant/strategy/guardian.py freshquant/tests/test_guardian_strategy.py freshquant/tests/test_guardian_runtime_observability.py
git commit -m "feat: expose degraded reconcile arrangement to guardian"
```

### Task 5: 实现 external trade partial match

**Files:**
- Modify: `freshquant/order_management/reconcile/service.py`
- Modify: `freshquant/tests/test_order_management_reconcile.py`

**Step 1: Write the failing tests**

- 内部单 `600`、外部回报 `300` 时可部分匹配
- 剩余未解释数量仍保留为 residual delta
- 不再直接 externalize 整笔

**Step 2: Run tests to verify they fail**

Run:
```powershell
D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pytest freshquant/tests/test_order_management_reconcile.py -q
```

**Step 3: Write minimal implementation**

- 扩展 `_match_inflight_internal_order()` 与 gap 更新逻辑
- 新增 partial match 元数据

**Step 4: Run tests to verify they pass**

Run:
```powershell
D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pytest freshquant/tests/test_order_management_reconcile.py -q
```

**Step 5: Commit**

```powershell
git add freshquant/order_management/reconcile/service.py freshquant/tests/test_order_management_reconcile.py
git commit -m "feat: support partial external trade reconciliation"
```

### Task 6: 同步正式文档与回归验证

**Files:**
- Modify: `docs/current/modules/order-management.md`
- Modify: `docs/current/runtime.md`

**Step 1: Update docs**

- 写清：
  - frozen inferred price
  - two-stage `AUTO_OPENED`
  - degraded arrangement
  - runtime params fallback
  - Guardian 对 degraded entry 的语义

**Step 2: Run focused regression**

Run:
```powershell
D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pytest freshquant/tests/test_order_management_reconcile.py freshquant/tests/test_order_reconcile_runtime_observability.py freshquant/tests/test_order_management_xt_ingest.py freshquant/tests/test_guardian_strategy.py freshquant/tests/test_guardian_runtime_observability.py -q
```

**Step 3: Run broader regression**

Run:
```powershell
D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pytest freshquant/tests/test_xt_account_sync_worker.py freshquant/tests/test_order_ledger_v2_rebuild.py freshquant/tests/test_order_management_reconcile.py freshquant/tests/test_order_reconcile_runtime_observability.py freshquant/tests/test_order_management_execution_bridge.py freshquant/tests/test_order_management_credit_runtime_resolution.py freshquant/tests/test_order_management_xt_ingest.py freshquant/tests/test_guardian_strategy.py freshquant/tests/test_guardian_runtime_observability.py -q
```

**Step 4: Commit**

```powershell
git add docs/current/modules/order-management.md docs/current/runtime.md
git commit -m "docs: describe reconciled truth decoupling behavior"
```

### Task 7: 交付、合并与部署

**Files:**
- No code changes required beyond previous tasks

**Step 1: Run local preflight**

Run:
```powershell
powershell -ExecutionPolicy Bypass -File script/fq_local_preflight.ps1 -Mode Ensure
```

**Step 2: Push branch and open PR**

Run:
```powershell
git push -u origin codex/order-reconcile-truth-decoupling
powershell -ExecutionPolicy Bypass -File script/fq_open_pr.ps1 -- --fill
```

**Step 3: Merge after CI green**

- 等待 `docs-current-guard / pre-commit / pytest` 全绿
- 处理 review comments
- 合并远程 `main`

**Step 4: Formal deploy**

- 基于最新远程 `main` 已合并 SHA 执行正式 deploy
- 受影响面：
  - `api`
  - `order_management`
  - `position_management`
  - Guardian host runtime

**Step 5: Health checks**

- `/api/runtime/components`
- `/api/runtime/health/summary`
- runtime verify artifacts
- `script/fqnext_host_runtime_ctl.ps1 -Mode Status`

**Step 6: Cleanup**

- 清理 feature branch
- 清理临时 worktree
- 保留正式 deploy artifacts
