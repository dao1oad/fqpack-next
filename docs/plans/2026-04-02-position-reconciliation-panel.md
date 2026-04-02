# Position Reconciliation Panel Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 `/position-management` 增加一个严格只读的“对账检查”面板，并把现有“单标的仓位上限”中的对账相关列移出，明确读写边界。

**Architecture:** 后端新增一个只读聚合服务，直接从 broker truth、PM snapshot、entry ledger、slice ledger、compat mirror 和 stock_fills projection 读取并拼装 canonical row；前端新增独立的 `PositionReconciliationPanel` 和共享 reconciliation 状态元数据，并调整 `/position-management` 页面布局，使“基础配置”“单标的仓位上限”“对账检查”“最近决策”四块职责分离。

**Tech Stack:** Python, pytest, Vue 3, Element Plus, node:test, Markdown

---

## 执行前提

- 必须在基于最新 `origin/main` 的干净 worktree 中执行
- 严格遵守 TDD：先写失败测试，再做最小实现
- 新的 reconciliation 功能只允许读，不允许写或触发修复

### Task 1: 锁定后端只读审计行的契约

**Files:**
- Create: `freshquant/tests/test_position_reconciliation_read_service.py`
- Reference: `freshquant/order_management/reconcile/summary.py`
- Reference: `freshquant/order_management/projection/stock_fills_compat.py`

**Step 1: Write the failing test for ALIGNED row**

在 `freshquant/tests/test_position_reconciliation_read_service.py` 中创建基础 fixture，断言同一个 symbol 的：

- broker quantity
- snapshot quantity
- entry quantity
- slice quantity
- compat quantity
- reconciliation state

会被正确聚合成一行 canonical row。

```python
assert row["symbol"] == "600000"
assert row["broker"]["quantity"] == 1200
assert row["snapshot"]["quantity"] == 1200
assert row["entry_ledger"]["quantity"] == 1200
assert row["slice_ledger"]["quantity"] == 1200
assert row["reconciliation"]["state"] == "ALIGNED"
assert row["audit_status"] == "OK"
assert row["mismatch_codes"] == []
```

**Step 2: Run test to verify it fails**

Run:

```powershell
D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pytest freshquant/tests/test_position_reconciliation_read_service.py -q
```

Expected: FAIL，提示 service 模块不存在

**Step 3: Create the minimal read service skeleton**

Create: `freshquant/position_management/reconciliation_read_service.py`

先只实现：

- `PositionReconciliationReadService`
- `list_rows()`
- `get_symbol_detail(symbol)`

返回硬编码最小结构，让测试先能 import 并拿到一行。

**Step 4: Run test to verify structure is wired**

Run:

```powershell
D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pytest freshquant/tests/test_position_reconciliation_read_service.py -q
```

Expected: 仍 FAIL，但失败点变成字段值不对，不再是 import error

**Step 5: Commit**

```bash
git add freshquant/tests/test_position_reconciliation_read_service.py freshquant/position_management/reconciliation_read_service.py
git commit -m "test: add reconciliation read service contract"
```

### Task 2: 实现只读聚合与审计规则

**Files:**
- Modify: `freshquant/position_management/reconciliation_read_service.py`
- Reference: `freshquant/data/astock/holding.py`
- Reference: `freshquant/order_management/entry_adapter.py`
- Reference: `freshquant/order_management/projection/stock_fills.py`
- Reference: `freshquant/order_management/projection/stock_fills_compat.py`

**Step 1: Add failing tests for WARN and ERROR cases**

在 `freshquant/tests/test_position_reconciliation_read_service.py` 中新增用例：

- `broker != entry + OBSERVING => WARN`
- `broker != entry + BROKEN => ERROR`
- `broker != entry + DRIFT => ERROR`
- `entry != slice => ERROR`
- `entry != compat => WARN/ERROR`

```python
assert row["reconciliation"]["state"] == "OBSERVING"
assert row["audit_status"] == "WARN"
assert "broker_vs_entry_quantity_mismatch" in row["mismatch_codes"]
```

**Step 2: Implement canonical loaders**

在 `reconciliation_read_service.py` 中增加内部 loader：

- `_load_broker_positions()`
- `_load_pm_snapshots()`
- `_load_entry_positions()`
- `_load_slice_positions()`
- `_load_compat_positions()`
- `_load_stock_fills_projection_positions()`

注意：

- 直接读集合或本地投影函数
- 不允许通过 HTTP 请求当前 API
- 不允许调用任何 sync / reconcile / repair 入口

**Step 3: Implement audit rules**

在 service 中实现：

- `R1 broker_snapshot_consistency`
- `R2 ledger_internal_consistency`
- `R3 compat_projection_consistency`
- `R4 broker_vs_ledger_consistency`

并输出：

- `audit_status`
- `mismatch_codes`

**Step 4: Run targeted tests**

Run:

```powershell
D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pytest freshquant/tests/test_position_reconciliation_read_service.py -q
```

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/position_management/reconciliation_read_service.py freshquant/tests/test_position_reconciliation_read_service.py
git commit -m "feat: add read-only position reconciliation audit"
```

### Task 3: 暴露只读 API

**Files:**
- Modify: `freshquant/rear/position_management/routes.py`
- Modify: `freshquant/tests/test_position_management_routes.py`

**Step 1: Write the failing route tests**

在 `freshquant/tests/test_position_management_routes.py` 中新增：

- `/api/position-management/reconciliation`
- `/api/position-management/reconciliation/<symbol>`

断言：

- `200`
- 返回 `summary`
- 返回 `rows`
- symbol detail 返回单个 row

**Step 2: Run route tests to verify failure**

Run:

```powershell
D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pytest freshquant/tests/test_position_management_routes.py -q
```

Expected: FAIL，提示新路由不存在

**Step 3: Implement the routes**

在 `freshquant/rear/position_management/routes.py` 中新增两个 GET 路由，直接调用 `PositionReconciliationReadService`。

不要：

- 捕获并吞掉异常
- 在 route 内写任何业务逻辑

**Step 4: Run route tests again**

Run:

```powershell
D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pytest freshquant/tests/test_position_management_routes.py -q
```

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/rear/position_management/routes.py freshquant/tests/test_position_management_routes.py
git commit -m "feat: expose position reconciliation routes"
```

### Task 4: 锁定前端 reconciliation 状态元数据与 view-model

**Files:**
- Create: `morningglory/fqwebui/src/views/reconciliationStateMeta.mjs`
- Create: `morningglory/fqwebui/src/views/positionReconciliation.mjs`
- Create: `morningglory/fqwebui/src/views/positionReconciliation.test.mjs`

**Step 1: Write failing node tests**

在 `positionReconciliation.test.mjs` 中先锁定：

- `ALIGNED / OBSERVING / AUTO_RECONCILED / BROKEN / DRIFT` 的 label
- `OK/WARN/ERROR` 的排序
- state/severity/query 三种过滤

```javascript
assert.equal(getReconciliationStateMeta('BROKEN').label, '异常')
assert.equal(rows[0].audit_status, 'ERROR')
assert.equal(filteredRows.length, 1)
```

**Step 2: Run the node test to verify it fails**

Run:

```powershell
node --test morningglory/fqwebui/src/views/positionReconciliation.test.mjs
```

Expected: FAIL，提示模块不存在

**Step 3: Implement the shared state meta and view-model**

在 `reconciliationStateMeta.mjs` 中统一定义：

- `label`
- `chipVariant`
- `severity`

在 `positionReconciliation.mjs` 中实现：

- DTO 归一化
- 排序
- 筛选
- 主表 label 拼装
- detail evidence 拼装

**Step 4: Run the node test again**

Run:

```powershell
node --test morningglory/fqwebui/src/views/positionReconciliation.test.mjs
```

Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/reconciliationStateMeta.mjs morningglory/fqwebui/src/views/positionReconciliation.mjs morningglory/fqwebui/src/views/positionReconciliation.test.mjs
git commit -m "feat: add reconciliation view model"
```

### Task 5: 新增独立对账组件并接入页面

**Files:**
- Create: `morningglory/fqwebui/src/components/position-management/PositionReconciliationPanel.vue`
- Modify: `morningglory/fqwebui/src/api/positionManagementApi.js`
- Modify: `morningglory/fqwebui/src/views/PositionManagement.vue`
- Modify: `morningglory/fqwebui/src/views/positionManagement.test.mjs`

**Step 1: Extend the page test with failing assertions**

在 `positionManagement.test.mjs` 中新增断言：

- 页面新增“对账检查”独立面板
- “单标的仓位上限”不再出现 `券商仓位 / 账本仓位 / 对账状态 / 一致性`

```javascript
assert.match(source, /对账检查/)
assert.doesNotMatch(source, /<span>券商仓位<\/span>\s*<span>账本仓位<\/span>\s*<span>对账状态<\/span>/)
```

**Step 2: Run the page test to verify it fails**

Run:

```powershell
node --test morningglory/fqwebui/src/views/positionManagement.test.mjs
```

Expected: FAIL，说明旧列仍存在

**Step 3: Implement the panel and integrate the page**

实现：

- `PositionReconciliationPanel.vue`
- `positionManagementApi.getReconciliation()`
- `PositionManagement.vue` 中新增加载逻辑和 panel 布局

并同步把“单标的上限”表收缩为：

- `标的`
- `单标的上限设置`
- `当前来源`
- `门禁`
- `操作`

**Step 4: Run the page test again**

Run:

```powershell
node --test morningglory/fqwebui/src/views/positionManagement.test.mjs morningglory/fqwebui/src/views/positionReconciliation.test.mjs
```

Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/components/position-management/PositionReconciliationPanel.vue morningglory/fqwebui/src/api/positionManagementApi.js morningglory/fqwebui/src/views/PositionManagement.vue morningglory/fqwebui/src/views/positionManagement.test.mjs morningglory/fqwebui/src/views/positionReconciliation.test.mjs
git commit -m "feat: add position reconciliation panel"
```

### Task 6: 同步文档并做最终回归

**Files:**
- Modify: `docs/current/modules/position-management.md`
- Modify: `docs/current/reference/frontend-workbench-style.md`
- Verify only: `freshquant/tests/test_position_reconciliation_read_service.py`
- Verify only: `freshquant/tests/test_position_management_routes.py`
- Verify only: `morningglory/fqwebui/src/views/positionManagement.test.mjs`
- Verify only: `morningglory/fqwebui/src/views/positionReconciliation.test.mjs`

**Step 1: Update the docs**

把当前事实同步到文档：

- `/position-management` 有独立“对账检查”面板
- 单标的上限表只负责 override 编辑
- 对账检查只读，不负责修复

**Step 2: Run the backend targeted suites**

Run:

```powershell
D:\fqpack\freshquant-2026.2.23\.venv\Scripts\python.exe -m pytest freshquant/tests/test_position_reconciliation_read_service.py freshquant/tests/test_position_management_routes.py freshquant/tests/test_position_management_dashboard.py -q
```

Expected: PASS

**Step 3: Run the frontend targeted suites**

Run:

```powershell
node --test morningglory/fqwebui/src/views/positionManagement.test.mjs morningglory/fqwebui/src/views/positionReconciliation.test.mjs
```

Expected: PASS

**Step 4: Run the frontend build**

Run:

```powershell
cd morningglory/fqwebui
npm run build
```

Expected: build 成功

**Step 5: Commit**

```bash
git add docs/current/modules/position-management.md docs/current/reference/frontend-workbench-style.md
git commit -m "docs: describe position reconciliation panel"
```

### Task 7: 最终检查与交付整理

**Files:**
- Verify only: all touched files

**Step 1: Inspect final diff**

Run:

```powershell
git diff --stat origin/main...HEAD
```

Expected: 只包含本任务的后端只读服务、路由、前端组件、页面布局、测试和文档

**Step 2: Inspect git status**

Run:

```powershell
git status --short
```

Expected: 工作区干净

**Step 3: Prepare merge summary**

整理最终交付说明，明确：

- 新增只读对账检查面板
- 旧单标的上限表移出对账列
- 后端只读审计规则与状态语义
- 测试和构建结果
