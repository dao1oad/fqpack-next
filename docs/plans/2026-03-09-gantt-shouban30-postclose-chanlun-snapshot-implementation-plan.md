# Gantt Shouban30 盘后缠论快照 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 `/gantt/shouban30` 的默认 30m 缠论筛选从前端读时现算切换为 Dagster 盘后预计算，并落入现有 `shouban30_plates / shouban30_stocks` 读模型。

**Architecture:** 复用现有 `persist_shouban30_for_date()` 和 `job_gantt_postclose`，在单个交易日内共享 `code6 + as_of_date + 30m` 级别的缠论结果缓存，构建四档窗口快照；HTTP 路由继续沿用 `/api/gantt/shouban30/*`，但返回预计算后的 `chanlun_*` 字段和板块通过数；前端页面删除现算链路，只消费盘后快照。

**Tech Stack:** Python 3.12、Flask、Dagster、MongoDB 读模型、Vue 3、Element Plus、Node test、pytest

---

### Task 1: 为读模型新增缠论快照测试

**Files:**
- Modify: `freshquant/tests/test_gantt_readmodel.py`
- Reference: `freshquant/data/gantt_readmodel.py`

**Step 1: Write the failing test**

增加以下测试：

- 黑名单板块 `其他 / 公告 / ST股 / ST板块` 不进入 `shouban30` 快照
- `persist_shouban30_for_date()` 写入 `chanlun_passed / chanlun_reason / chanlun_higher_multiple / chanlun_segment_multiple / chanlun_bi_gain_percent / chanlun_filter_version`
- `shouban30_plates.stocks_count` 等于通过数，并新增 `candidate_stocks_count / failed_stocks_count`
- 同一交易日四窗口共享缓存时，同一股票只计算一次

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_gantt_readmodel.py -q`

Expected: FAIL，原因是读模型尚未写入新增字段或缓存复用语义不存在。

**Step 3: Commit**

```bash
git add freshquant/tests/test_gantt_readmodel.py
git commit -m "test: define shouban30 postclose chanlun snapshot readmodel behavior"
```

### Task 2: 实现读模型缠论快照构建

**Files:**
- Modify: `freshquant/data/gantt_readmodel.py`
- Test: `freshquant/tests/test_gantt_readmodel.py`

**Step 1: Write minimal implementation**

实现以下内容：

- 新增板块黑名单常量和过滤函数
- 新增默认 30m 缠论结果归一化函数，复用 `get_chanlun_structure(..., period='30m', end_date=as_of_date)`
- 扩展 `_build_shouban30_stock_rows()`，把 `chanlun_*` 落到 stock rows
- 扩展 `build_shouban30_plate_rows()`，把 `stocks_count` 改成通过数并补 `candidate_stocks_count / failed_stocks_count / chanlun_filter_version`
- 扩展 `persist_shouban30_for_date(..., chanlun_result_cache=None)`，按 `code6 + as_of_date + 30m` 懒计算并复用 cache

**Step 2: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_gantt_readmodel.py -q`

Expected: PASS

**Step 3: Commit**

```bash
git add freshquant/data/gantt_readmodel.py freshquant/tests/test_gantt_readmodel.py
git commit -m "feat: persist shouban30 chanlun snapshots postclose"
```

### Task 3: 为 Dagster 共享缓存和 legacy 判定补测试

**Files:**
- Modify: `freshquant/tests/test_gantt_dagster_ops.py`
- Reference: `morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py`

**Step 1: Write the failing test**

增加以下测试：

- `_build_shouban30_snapshots_for_date()` 会把同一个 `chanlun_result_cache` 传给四窗口构建
- legacy snapshot 判定除了 `stock_window_days` 旧 schema，还会识别缺少 `chanlun_filter_version`

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_gantt_dagster_ops.py -q`

Expected: FAIL，原因是当前 Dagster 还没有共享缓存或新的 legacy 判定。

**Step 3: Commit**

```bash
git add freshquant/tests/test_gantt_dagster_ops.py
git commit -m "test: define shouban30 chanlun snapshot dagster orchestration"
```

### Task 4: 实现 Dagster 单日共享缓存与重建语义

**Files:**
- Modify: `morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py`
- Test: `freshquant/tests/test_gantt_dagster_ops.py`

**Step 1: Write minimal implementation**

实现以下内容：

- `_build_shouban30_snapshots_for_date()` 创建单日共享 `chanlun_result_cache`
- 四窗口构建时把 cache 传入 `persist_shouban30_for_date()`
- `_has_legacy_shouban30_snapshot()` 把“缺少 `chanlun_filter_version`”视为 legacy

**Step 2: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_gantt_dagster_ops.py -q`

Expected: PASS

**Step 3: Commit**

```bash
git add morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py freshquant/tests/test_gantt_dagster_ops.py
git commit -m "feat: share chanlun snapshot cache across shouban30 windows"
```

### Task 5: 为 `/api/gantt/shouban30/*` 新语义补路由测试

**Files:**
- Modify: `freshquant/tests/test_gantt_routes.py`
- Reference: `freshquant/rear/gantt/routes.py`

**Step 1: Write the failing test**

增加以下测试：

- `/api/gantt/shouban30/plates` 返回 `candidate_stocks_count / failed_stocks_count / chanlun_filter_version`
- `/api/gantt/shouban30/stocks` 返回 `chanlun_*`
- 命中 legacy snapshot 时返回 `409` 和 `shouban30 chanlun snapshot not ready`

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_gantt_routes.py -q`

Expected: FAIL，原因是当前路由尚未验证或返回这些字段/错误语义。

**Step 3: Commit**

```bash
git add freshquant/tests/test_gantt_routes.py
git commit -m "test: define shouban30 chanlun snapshot route semantics"
```

### Task 6: 实现路由新语义和 legacy 错误

**Files:**
- Modify: `freshquant/rear/gantt/routes.py`
- Modify: `freshquant/data/gantt_readmodel.py`
- Test: `freshquant/tests/test_gantt_routes.py`

**Step 1: Write minimal implementation**

实现以下内容：

- 在 `query_shouban30_plate_rows()` / `query_shouban30_stock_rows()` 或路由层加入 legacy snapshot 判定
- legacy snapshot 时抛出 `ValueError("shouban30 chanlun snapshot not ready")`
- 路由将该错误映射为 HTTP `409`
- `meta` 里附带 `chanlun_filter_version`

**Step 2: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_gantt_routes.py -q`

Expected: PASS

**Step 3: Commit**

```bash
git add freshquant/rear/gantt/routes.py freshquant/data/gantt_readmodel.py freshquant/tests/test_gantt_routes.py
git commit -m "feat: expose shouban30 postclose chanlun snapshot semantics"
```

### Task 7: 为前端只读快照模式补测试

**Files:**
- Modify: `morningglory/fqwebui/src/views/shouban30Aggregation.test.mjs`
- Modify: `morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs`
- Reference: `morningglory/fqwebui/src/views/GanttShouban30Phase1.vue`

**Step 1: Write the failing test**

增加以下断言：

- 页面不再包含 `getChanlunStructure / loadChanlunStructures / chanlunStructureCache`
- 页面继续显示 `高级段倍数 / 段倍数 / 笔涨幅%`
- 页面统计基于后端返回的 `chanlun_*` 和 `stocks_count`
- 页面在快照未就绪时展示错误，不退回前端现算

**Step 2: Run test to verify it fails**

Run: `node --test src/views/shouban30Aggregation.test.mjs src/views/shouban30ChanlunFilter.test.mjs`

Expected: FAIL，原因是页面当前仍保留现算链路。

**Step 3: Commit**

```bash
git add morningglory/fqwebui/src/views/shouban30Aggregation.test.mjs morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs
git commit -m "test: define shouban30 read-only postclose snapshot page behavior"
```

### Task 8: 替换页面为只读盘后快照模式

**Files:**
- Modify: `morningglory/fqwebui/src/views/GanttShouban30Phase1.vue`
- Modify: `morningglory/fqwebui/src/views/shouban30Aggregation.mjs`
- Modify: `morningglory/fqwebui/src/api/futureApi.js`
- Test: `morningglory/fqwebui/src/views/shouban30Aggregation.test.mjs`
- Test: `morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs`

**Step 1: Write minimal implementation**

实现以下内容：

- 删除 `getChanlunStructure` 相关引用和页面级缓存/并发逻辑
- 板块黑名单不再在页面层过滤，直接消费后端快照
- 左栏显示后端的 `stocks_count`
- 中栏只显示 `chanlun_passed === true` 的标的，并展示三列缠论指标
- 聚合视图按后端返回的 `chanlun_*` 字段聚合
- 命中 `409` 时展示“首板缠论快照未构建完成”

**Step 2: Run test to verify it passes**

Run: `node --test src/views/shouban30Aggregation.test.mjs src/views/shouban30ChanlunFilter.test.mjs`

Expected: PASS

**Step 3: Commit**

```bash
git add morningglory/fqwebui/src/views/GanttShouban30Phase1.vue morningglory/fqwebui/src/views/shouban30Aggregation.mjs morningglory/fqwebui/src/api/futureApi.js morningglory/fqwebui/src/views/shouban30Aggregation.test.mjs morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs
git commit -m "feat: switch shouban30 page to postclose chanlun snapshots"
```

### Task 9: 运行完整验证

**Files:**
- No code changes expected

**Step 1: Run backend verification**

Run:

- `py -3.12 -m pytest freshquant/tests/test_gantt_readmodel.py freshquant/tests/test_gantt_routes.py freshquant/tests/test_gantt_dagster_ops.py -q`
- `py -3.12 -m pytest freshquant/tests/test_chanlun_structure_service.py freshquant/tests/test_stock_data_chanlun_structure_route.py -q`

Expected: PASS

**Step 2: Run frontend verification**

Run:

- `node --test src/views/shouban30Aggregation.test.mjs src/views/shouban30ChanlunFilter.test.mjs`
- `npm run build`

Expected: PASS

**Step 3: Commit**

如果构建产物更新：

```bash
git add morningglory/fqwebui/web
git commit -m "build: refresh shouban30 postclose chanlun snapshot web artifacts"
```

### Task 10: 更新迁移记录与破坏性变更

**Files:**
- Modify: `docs/migration/progress.md`
- Modify: `docs/migration/breaking-changes.md`

**Step 1: Update docs**

补充：

- RFC 0023 从 `Approved` 到 `Done` 的实现说明
- `/api/gantt/shouban30/*` 语义变化和迁移步骤

**Step 2: Commit**

```bash
git add docs/migration/progress.md docs/migration/breaking-changes.md
git commit -m "docs: record shouban30 postclose chanlun snapshot migration"
```
