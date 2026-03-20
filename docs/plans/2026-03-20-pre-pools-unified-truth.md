# Pre-Pools 单码单记录统一真值 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 `stock_pre_pools` 收敛为“同池同 `code` 只保留一条”的正式真值，并让 `/kline-slim`、`/gantt/shouban30`、`/daily-screening` 三个页面统一展示去重后的同一池子，同时清楚展示来源和分类。

**Architecture:** 后端新增 shared pre-pool 聚合/写入服务，以 `memberships` 保留精确来源-分类写入真值，以顶层单条记录作为页面与工作区统一读口径。现有 `daily_screening`、`shouban30`、旧 `stock_service` 路径全部改为走 shared service，再把三个前端页面对齐到统一返回结构。实现顺序严格按 TDD 进行，先补共享服务和迁移测试，再改写写入链、路由和前端。

**Tech Stack:** Python 3.12、Flask、MongoDB、pytest、Vue 3、Element Plus、Node test

---

### Task 1: 落地设计与计划文档

**Files:**
- Create: `docs/plans/2026-03-20-pre-pools-unified-truth-design.md`
- Create: `docs/plans/2026-03-20-pre-pools-unified-truth.md`

**Step 1: 写设计文档**

记录：
- 单码单记录真值
- `sources/categories/memberships` 语义
- 删除整条记录语义
- 三页统一读口径

**Step 2: 写实施计划**

把后端服务、写入链、路由、前端和迁移拆成独立任务。

**Step 3: 提交文档**

Run: `git add docs/plans/2026-03-20-pre-pools-unified-truth-design.md docs/plans/2026-03-20-pre-pools-unified-truth.md`

**Step 4: Commit**

```bash
git commit -m "docs: add pre-pools unified truth design"
```

### Task 2: 为 shared pre-pool service 补失败测试

**Files:**
- Create: `freshquant/pre_pool_service.py`
- Create: `freshquant/tests/test_pre_pool_service.py`

**Step 1: 写失败测试**

在 `freshquant/tests/test_pre_pool_service.py` 覆盖：

```python
def test_upsert_pre_pool_creates_single_row_for_new_code():
    ...

def test_upsert_pre_pool_merges_new_membership_into_existing_code():
    ...

def test_upsert_pre_pool_is_idempotent_for_same_source_and_category():
    ...

def test_delete_pre_pool_removes_entire_code_record():
    ...

def test_list_pre_pool_returns_unique_codes_with_sources_and_categories():
    ...
```

**Step 2: 运行测试确认失败**

Run: `py -3.12 -m pytest freshquant/tests/test_pre_pool_service.py -q`

Expected: FAIL，因为 shared service 尚未实现

**Step 3: 写最小实现**

在 `freshquant/pre_pool_service.py` 中实现：

```python
class PrePoolService:
    def upsert_code(self, *, code, name, symbol, source, category, added_at=None, expire_at=None, extra=None, workspace_order=None):
        ...

    def list_codes(self):
        ...

    def delete_code(self, code):
        ...
```

实现要点：
- 顶层只有一条记录
- `memberships` 精确保留 `(source, category)`
- `sources/categories` 去重汇总
- `workspace_order` 可写可读

**Step 4: 运行测试确认通过**

Run: `py -3.12 -m pytest freshquant/tests/test_pre_pool_service.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/pre_pool_service.py freshquant/tests/test_pre_pool_service.py
git commit -m "feat: add shared pre-pool service"
```

### Task 3: 收敛 daily-screening 写入与读取

**Files:**
- Modify: `freshquant/daily_screening/service.py`
- Modify: `freshquant/tests/test_daily_screening_service.py`
- Modify: `freshquant/tests/test_daily_screening_routes.py`

**Step 1: 写失败测试**

在现有测试中增加断言：

```python
def test_daily_screening_add_to_pre_pool_merges_same_code_memberships():
    ...

def test_daily_screening_list_pre_pools_returns_unique_code_rows():
    ...
```

**Step 2: 运行测试确认失败**

Run: `py -3.12 -m pytest freshquant/tests/test_daily_screening_service.py freshquant/tests/test_daily_screening_routes.py -q`

Expected: FAIL，因为当前仍按明细行返回

**Step 3: 写最小实现**

在 `freshquant/daily_screening/service.py` 中：
- 把 `save_pre_pools` 写入改到 shared `PrePoolService`
- `list_pre_pools()` 改为返回聚合后的单码结果
- `remark/category` 输入改为筛 memberships，不再直接查 Mongo 明细

**Step 4: 运行测试确认通过**

Run: `py -3.12 -m pytest freshquant/tests/test_daily_screening_service.py freshquant/tests/test_daily_screening_routes.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/daily_screening/service.py freshquant/tests/test_daily_screening_service.py freshquant/tests/test_daily_screening_routes.py
git commit -m "feat: unify daily screening pre-pool writes"
```

### Task 4: 收敛 shouban30 工作区到 shared pre-pool 真值

**Files:**
- Modify: `freshquant/shouban30_pool_service.py`
- Modify: `freshquant/tests/test_shouban30_pool_service.py`
- Modify: `freshquant/tests/test_gantt_routes.py`

**Step 1: 写失败测试**

补测试覆盖：

```python
def test_append_pre_pool_keeps_single_row_and_adds_membership():
    ...

def test_list_pre_pool_returns_unified_rows_not_category_subset_duplicates():
    ...

def test_delete_pre_pool_item_deletes_entire_code_record():
    ...
```

**Step 2: 运行测试确认失败**

Run: `py -3.12 -m pytest freshquant/tests/test_shouban30_pool_service.py freshquant/tests/test_gantt_routes.py -q`

Expected: FAIL，因为当前逻辑仍按 `category=三十涨停Pro预选` 明细集合工作

**Step 3: 写最小实现**

在 `freshquant/shouban30_pool_service.py` 中：
- append/replace 改走 shared `PrePoolService`
- `workspace_order` 从统一顶层字段维护
- `list_pre_pool()` 返回 shared service 的统一结果
- 删除按 `code` 删除整条记录

**Step 4: 运行测试确认通过**

Run: `py -3.12 -m pytest freshquant/tests/test_shouban30_pool_service.py freshquant/tests/test_gantt_routes.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/shouban30_pool_service.py freshquant/tests/test_shouban30_pool_service.py freshquant/tests/test_gantt_routes.py
git commit -m "feat: unify shouban30 pre-pool workspace"
```

### Task 5: 收敛旧 stock API 到统一读口径

**Files:**
- Modify: `freshquant/stock_service.py`
- Modify: `freshquant/rear/stock/routes.py`
- Modify: `freshquant/tests/test_stock_pool_service.py`

**Step 1: 写失败测试**

增加断言：

```python
def test_get_stock_pre_pools_list_returns_unique_codes():
    ...

def test_get_stock_pre_pools_list_exposes_sources_and_categories():
    ...

def test_delete_from_stock_pre_pools_by_code_deletes_whole_row():
    ...
```

**Step 2: 运行测试确认失败**

Run: `py -3.12 -m pytest freshquant/tests/test_stock_pool_service.py -q`

Expected: FAIL，因为旧服务仍直接 `find({}).sort(...)`

**Step 3: 写最小实现**

在 `freshquant/stock_service.py` 中：
- `get_stock_pre_pools_list()` 改调 shared `PrePoolService`
- 删除接口改为 shared `delete_code()`
- 兼容输出 `primary_source/primary_category`，同时返回 `sources/categories`

**Step 4: 运行测试确认通过**

Run: `py -3.12 -m pytest freshquant/tests/test_stock_pool_service.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/stock_service.py freshquant/rear/stock/routes.py freshquant/tests/test_stock_pool_service.py
git commit -m "feat: unify legacy stock pre-pool api"
```

### Task 6: 增加旧数据收敛入口

**Files:**
- Create: `script/migrate_pre_pools_unified_truth.py`
- Modify: `freshquant/tests/test_pre_pool_service.py`
- Modify: `docs/current/storage.md`

**Step 1: 写失败测试**

在 `freshquant/tests/test_pre_pool_service.py` 增加迁移覆盖：

```python
def test_migrate_legacy_pre_pool_rows_merges_same_code():
    ...
```

**Step 2: 运行测试确认失败**

Run: `py -3.12 -m pytest freshquant/tests/test_pre_pool_service.py -q`

Expected: FAIL，因为迁移 helper 尚未存在

**Step 3: 写最小实现**

在 `script/migrate_pre_pools_unified_truth.py` 中实现：
- 读取旧 `stock_pre_pools`
- 按 `code` 聚合
- 推导 `memberships`
- 回写新结构

**Step 4: 运行测试确认通过**

Run: `py -3.12 -m pytest freshquant/tests/test_pre_pool_service.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add script/migrate_pre_pools_unified_truth.py freshquant/tests/test_pre_pool_service.py docs/current/storage.md
git commit -m "feat: add pre-pool truth migration"
```

### Task 7: 统一三个前端页面展示与计数

**Files:**
- Modify: `morningglory/fqwebui/src/views/js/kline-slim.js`
- Modify: `morningglory/fqwebui/src/views/js/kline-slim-sidebar.mjs`
- Modify: `morningglory/fqwebui/src/views/KlineSlim.vue`
- Modify: `morningglory/fqwebui/src/views/DailyScreening.vue`
- Modify: `morningglory/fqwebui/src/views/GanttShouban30Phase1.vue`
- Modify: `morningglory/fqwebui/src/api/stockApi.js`
- Modify: `morningglory/fqwebui/src/api/ganttShouban30.js`
- Modify: `morningglory/fqwebui/src/views/DailyScreening.test.mjs`
- Create: `morningglory/fqwebui/src/views/KlineSlim.test.mjs`
- Modify: `morningglory/fqwebui/src/views/shouban30PoolWorkspace.test.mjs`

**Step 1: 写失败测试**

补前端测试覆盖：

```js
test('kline slim sidebar uses deduped pre-pool count')
test('daily screening workspace renders sources and categories')
test('shouban30 workspace renders sources and categories')
```

**Step 2: 运行测试确认失败**

Run: `node --test morningglory/fqwebui/src/views/DailyScreening.test.mjs morningglory/fqwebui/src/views/KlineSlim.test.mjs morningglory/fqwebui/src/views/shouban30PoolWorkspace.test.mjs`

Expected: FAIL，因为前端尚未接入 `sources/categories`

**Step 3: 写最小实现**

前端改动要求：
- `/kline-slim` 侧边栏读统一返回结构
- `section.items.length` 代表去重后的股票数
- `/daily-screening` 和 `/gantt/shouban30` 工作区都显示 `sources/categories`
- 三个页面都不再假设 `category` 只有单值

**Step 4: 运行测试确认通过**

Run: `node --test morningglory/fqwebui/src/views/DailyScreening.test.mjs morningglory/fqwebui/src/views/KlineSlim.test.mjs morningglory/fqwebui/src/views/shouban30PoolWorkspace.test.mjs`

Expected: PASS

**Step 5: 前端构建验证**

Run: `npm run build`

Workdir: `morningglory/fqwebui`

Expected: PASS

**Step 6: Commit**

```bash
git add morningglory/fqwebui/src/views/js/kline-slim.js morningglory/fqwebui/src/views/js/kline-slim-sidebar.mjs morningglory/fqwebui/src/views/KlineSlim.vue morningglory/fqwebui/src/views/DailyScreening.vue morningglory/fqwebui/src/views/GanttShouban30Phase1.vue morningglory/fqwebui/src/api/stockApi.js morningglory/fqwebui/src/api/ganttShouban30.js morningglory/fqwebui/src/views/DailyScreening.test.mjs morningglory/fqwebui/src/views/KlineSlim.test.mjs morningglory/fqwebui/src/views/shouban30PoolWorkspace.test.mjs
git commit -m "feat: unify pre-pool ui across workspaces"
```

### Task 8: 更新正式文档

**Files:**
- Modify: `docs/current/modules/daily-screening.md`
- Modify: `docs/current/modules/shouban30-screening.md`
- Modify: `docs/current/reference/stock-pools-and-positions.md`
- Modify: `docs/current/interfaces.md`

**Step 1: 写文档变更**

补充：
- `stock_pre_pools` 现为单码单记录真值
- `sources/categories/memberships` 语义
- 三页统一读口径
- 删除按 `code` 删整条记录

**Step 2: 核对文档与实现一致**

逐条核对：
- 页面数量口径
- 共享接口
- 写入与删除语义

**Step 3: Commit**

```bash
git add docs/current/modules/daily-screening.md docs/current/modules/shouban30-screening.md docs/current/reference/stock-pools-and-positions.md docs/current/interfaces.md
git commit -m "docs: document unified pre-pool truth"
```

### Task 9: 全量验证与部署

**Files:**
- No file changes required

**Step 1: 运行后端测试**

Run:

```bash
py -3.12 -m pytest freshquant/tests/test_pre_pool_service.py freshquant/tests/test_daily_screening_service.py freshquant/tests/test_daily_screening_routes.py freshquant/tests/test_shouban30_pool_service.py freshquant/tests/test_gantt_routes.py freshquant/tests/test_stock_pool_service.py -q
```

Expected: PASS

**Step 2: 运行前端测试**

Run:

```bash
node --test morningglory/fqwebui/src/views/DailyScreening.test.mjs morningglory/fqwebui/src/views/KlineSlim.test.mjs morningglory/fqwebui/src/views/shouban30PoolWorkspace.test.mjs
```

Expected: PASS

**Step 3: 运行前端构建**

Run: `npm run build`

Workdir: `morningglory/fqwebui`

Expected: PASS

**Step 4: 执行数据收敛**

Run: `py -3.12 script/migrate_pre_pools_unified_truth.py`

Expected: 旧 `stock_pre_pools` 收敛为单码单记录

**Step 5: 部署受影响模块**

Run: `docker compose -f docker/compose.parallel.yaml up -d --build`

Expected: API 与 Web UI 更新完成

**Step 6: 健康检查**

Run:

```bash
Invoke-WebRequest http://127.0.0.1:15000/api/get_stock_pre_pools_list?page=1&size=1000 -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:15000/api/gantt/shouban30/pre-pool -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:15000/api/daily-screening/pre-pools?limit=200 -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:18080 -UseBasicParsing
```

Expected:
- 接口 `200`
- 三条 `pre_pool` 接口返回相同数量
- Web UI 可打开

**Step 7: 手工验收**

在浏览器中确认：
- `/kline-slim`
- `/gantt/shouban30`
- `/daily-screening`

三页 `pre_pools` 数量一致，且每行都能看到来源和分类。

**Step 8: Git 收口**

```bash
git status --short
git push origin codex/pre-pools-diff-20260320
```

**Step 9: 通过 PR 合并到 remote main**

使用非交互 git / gh 流程创建或更新 PR，等待检查通过后合并，不直接推送 `main`。
