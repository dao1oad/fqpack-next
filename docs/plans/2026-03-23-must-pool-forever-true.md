# must_pool forever 固定为 true Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 统一 `must_pool` 的写入口为 `forever=true`，并删除前端所有与该字段相关的设置项和展示文案。

**Architecture:** 前端移除 `forever` 的编辑草稿、状态摘要和 API 参数；后端在所有 `must_pool` 写入口内忽略外部传入值并统一写 `true`；自动清理逻辑不再按 `forever` 分支；提供一次性数据修复脚本把历史文档拉齐。

**Tech Stack:** Vue 3, Element Plus, Node test runner, Python service layer, pytest, MongoDB maintenance script.

---

### Task 1: 锁定前端不再展示 forever

**Files:**
- Modify: `D:\fqpack\freshquant-2026.2.23\.worktrees\must-pool-forever-true-20260323\morningglory\fqwebui\src\views\subjectManagement.test.mjs`
- Modify: `D:\fqpack\freshquant-2026.2.23\.worktrees\must-pool-forever-true-20260323\morningglory\fqwebui\src\views\subjectManagementPage.test.mjs`
- Modify: `D:\fqpack\freshquant-2026.2.23\.worktrees\must-pool-forever-true-20260323\morningglory\fqwebui\src\views\js\kline-slim-subject-panel.test.mjs`

**Step 1: Write the failing test**

- 调整断言，要求 dense config 行中不再包含 `forever`
- 调整页面状态断言，要求 `mustPoolDraft` 不再包含 `forever`
- 调整摘要断言，要求不再出现 `永久跟踪 / 普通标的`

**Step 2: Run test to verify it fails**

Run: `node --test src/views/subjectManagement.test.mjs src/views/subjectManagementPage.test.mjs src/views/js/kline-slim-subject-panel.test.mjs`

Expected: FAIL because current UI 仍然暴露 `forever`

**Step 3: Write minimal implementation**

- 删除前端 view-model 中 `forever` 的归一化、草稿字段和状态文案

**Step 4: Run test to verify it passes**

Run: `node --test src/views/subjectManagement.test.mjs src/views/subjectManagementPage.test.mjs src/views/js/kline-slim-subject-panel.test.mjs`

Expected: PASS

### Task 2: 锁定后端统一写入 forever=true

**Files:**
- Modify: `D:\fqpack\freshquant-2026.2.23\.worktrees\must-pool-forever-true-20260323\freshquant\tests\test_subject_management_write_service.py`
- Modify: `D:\fqpack\freshquant-2026.2.23\.worktrees\must-pool-forever-true-20260323\freshquant\tests\test_subject_management_routes.py`
- Modify: `D:\fqpack\freshquant-2026.2.23\.worktrees\must-pool-forever-true-20260323\freshquant\tests\test_subject_management_service.py`

**Step 1: Write the failing test**

- 新增或调整断言，要求 `update_must_pool(...)` 即使收到 `forever=False` 或缺失该键，返回值和落库值也为 `True`
- 如果有 stock route 级测试，锁 `/api/add_to_must_pool_by_code` 不再依赖 query 参数 `forever`

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_subject_management_write_service.py freshquant/tests/test_subject_management_routes.py freshquant/tests/test_subject_management_service.py -q`

Expected: FAIL because current代码仍按入参或草稿写入 `forever`

**Step 3: Write minimal implementation**

- 后端 `must_pool` 写入口统一强制写 `True`

**Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_subject_management_write_service.py freshquant/tests/test_subject_management_routes.py freshquant/tests/test_subject_management_service.py -q`

Expected: PASS

### Task 3: 删除页面设置项并同步 API

**Files:**
- Modify: `D:\fqpack\freshquant-2026.2.23\.worktrees\must-pool-forever-true-20260323\morningglory\fqwebui\src\components\StockPools.vue`
- Modify: `D:\fqpack\freshquant-2026.2.23\.worktrees\must-pool-forever-true-20260323\morningglory\fqwebui\src\api\stockApi.js`
- Modify: `D:\fqpack\freshquant-2026.2.23\.worktrees\must-pool-forever-true-20260323\morningglory\fqwebui\src\views\KlineSlim.vue`
- Modify: `D:\fqpack\freshquant-2026.2.23\.worktrees\must-pool-forever-true-20260323\morningglory\fqwebui\src\views\SubjectManagement.vue`
- Modify: `D:\fqpack\freshquant-2026.2.23\.worktrees\must-pool-forever-true-20260323\morningglory\fqwebui\src\views\subjectManagement.mjs`
- Modify: `D:\fqpack\freshquant-2026.2.23\.worktrees\must-pool-forever-true-20260323\morningglory\fqwebui\src\views\subjectManagementPage.mjs`
- Modify: `D:\fqpack\freshquant-2026.2.23\.worktrees\must-pool-forever-true-20260323\morningglory\fqwebui\src\views\js\kline-slim-subject-panel.mjs`
- Modify: `D:\fqpack\freshquant-2026.2.23\.worktrees\must-pool-forever-true-20260323\morningglory\fqwebui\src\views\js\kline-slim.js`

**Step 1: Write the failing test**

- 如果需要，补充组件 / view-model 级断言，锁 `saveMustPool` payload 不再包含 `forever`

**Step 2: Run test to verify it fails**

Run: `node --test src/views/subjectManagement.test.mjs src/views/subjectManagementPage.test.mjs src/views/js/kline-slim-subject-panel.test.mjs`

Expected: FAIL because payload 和 UI 仍带有 `forever`

**Step 3: Write minimal implementation**

- 删掉页面开关、摘要和草稿字段
- `stockApi.addToStockMustPoolsByCode(...)` 去掉 `forever` 参数

**Step 4: Run test to verify it passes**

Run: `node --test src/views/subjectManagement.test.mjs src/views/subjectManagementPage.test.mjs src/views/js/kline-slim-subject-panel.test.mjs`

Expected: PASS

### Task 4: 清理后端旧语义并补数据修复脚本

**Files:**
- Modify: `D:\fqpack\freshquant-2026.2.23\.worktrees\must-pool-forever-true-20260323\freshquant\pool\general.py`
- Modify: `D:\fqpack\freshquant-2026.2.23\.worktrees\must-pool-forever-true-20260323\freshquant\rear\stock\routes.py`
- Modify: `D:\fqpack\freshquant-2026.2.23\.worktrees\must-pool-forever-true-20260323\freshquant\stock_service.py`
- Modify: `D:\fqpack\freshquant-2026.2.23\.worktrees\must-pool-forever-true-20260323\freshquant\subject_management\write_service.py`
- Create: `D:\fqpack\freshquant-2026.2.23\.worktrees\must-pool-forever-true-20260323\script\maintenance\backfill_must_pool_forever_true.py`

**Step 1: Write the failing test**

- 补一个清理逻辑测试或服务层测试，锁 `cleanMustPool()` 不再按 `forever=False` 过滤

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_subject_management_write_service.py freshquant/tests/test_subject_management_routes.py freshquant/tests/test_subject_management_service.py -q`

Expected: FAIL or coverage gap exposed

**Step 3: Write minimal implementation**

- 更新清理逻辑
- 增加回填脚本，统一把 `must_pool.forever` 设为 `true`

**Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_subject_management_write_service.py freshquant/tests/test_subject_management_routes.py freshquant/tests/test_subject_management_service.py -q`

Expected: PASS

### Task 5: 文档、构建和交付

**Files:**
- Modify: `D:\fqpack\freshquant-2026.2.23\.worktrees\must-pool-forever-true-20260323\docs\current\reference\stock-pools-and-positions.md`
- Modify: `D:\fqpack\freshquant-2026.2.23\.worktrees\must-pool-forever-true-20260323\docs\current\modules\kline-webui.md`

**Step 1: Run verification**

Run:

- `node --test src/views/subjectManagement.test.mjs src/views/subjectManagementPage.test.mjs src/views/js/kline-slim-subject-panel.test.mjs`
- `py -3.12 -m pytest freshquant/tests/test_subject_management_write_service.py freshquant/tests/test_subject_management_routes.py freshquant/tests/test_subject_management_service.py -q`
- `npm run build`

Expected: 全部通过

**Step 2: Commit**

```bash
git add docs/current docs/plans freshquant morningglory/fqwebui script/maintenance
git commit -m "refactor: retire must-pool forever setting"
```
