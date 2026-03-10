# Shouban30 Extra Filter Snapshot Repair Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复 `/gantt/shouban30` 三个额外筛选因旧快照和质量名单读取 bug 导致始终为空的问题。

**Architecture:** 保持现有页面和 API 不变，只修两处后端基础设施：一是扩展 Dagster 对最新 `shouban30` 快照的 legacy 判定，让缺失 RFC 0027 字段的旧 `stocks` 快照会被重建；二是修复 `quality_stock_universe` 在真实 PyMongo `Collection` 下的布尔判断异常。随后用真实 `2026-03-09` 数据重建一次快照，验证字段分布。

**Tech Stack:** Python 3.12, pytest, Flask, Dagster, PyMongo, MongoDB, Node.js test runner

---

### Task 1: 写出失败测试并锁定回归口径

**Files:**
- Modify: `freshquant/tests/test_quality_stock_universe.py`
- Modify: `freshquant/tests/test_gantt_dagster_ops.py`

**Step 1: Write the failing test**

在 `test_quality_stock_universe.py` 增加一条测试：

- 显式传入一个 collection-like 对象给 `load_quality_stock_lookup()`
- 断言函数返回 lookup，不触发 `Collection.__bool__` 风格异常

在 `test_gantt_dagster_ops.py` 增加两条测试：

- `shouban30_plates` 四档窗口齐全、`chanlun_filter_version` 存在，但 `shouban30_stocks` 缺失 `is_credit_subject / near_long_term_ma_passed / is_quality_subject / *_snapshot_ready` 字段时，`_has_legacy_shouban30_snapshot()` 返回 `True`
- 同样数据在 `stocks` 文档补齐字段后，返回 `False`

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_quality_stock_universe.py freshquant/tests/test_gantt_dagster_ops.py -q`

Expected:

- 新增测试失败
- 失败原因分别是 `Collection` 布尔判断异常或 legacy 判定仍返回旧结果

**Step 3: Commit**

先不提交，进入实现。

### Task 2: 最小修复 quality_stock_universe 读取

**Files:**
- Modify: `freshquant/data/quality_stock_universe.py`

**Step 1: Write minimal implementation**

把默认 collection 选择改成显式空值判断：

- `if target_collection is None: target_collection = DBfreshquant[...]`

避免对 PyMongo `Collection` 做布尔判断。

**Step 2: Run test to verify targeted behavior**

Run: `py -3.12 -m pytest freshquant/tests/test_quality_stock_universe.py -q`

Expected: PASS

### Task 3: 扩展 shouban30 legacy 判定

**Files:**
- Modify: `morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py`
- Test: `freshquant/tests/test_gantt_dagster_ops.py`

**Step 1: Write minimal implementation**

在 `_has_legacy_shouban30_snapshot()` 中：

- 继续读取 `shouban30_plates`
- 再读取同日 `shouban30_stocks`
- 若 `stocks` 为空，返回 `True`
- 若任一 `stocks` 文档缺失关键字段，返回 `True`
- 否则维持原逻辑

关键字段：

- `is_credit_subject`
- `credit_subject_snapshot_ready`
- `near_long_term_ma_passed`
- `is_quality_subject`
- `quality_subject_snapshot_ready`

字段判断使用“键存在”而不是“值为真”。

**Step 2: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_gantt_dagster_ops.py -q`

Expected: PASS

### Task 4: 跑关联回归测试

**Files:**
- Test: `freshquant/tests/test_quality_stock_universe.py`
- Test: `freshquant/tests/test_gantt_dagster_ops.py`
- Test: `freshquant/tests/test_gantt_readmodel.py`
- Test: `freshquant/tests/test_gantt_routes.py`

**Step 1: Run backend verification**

Run: `py -3.12 -m pytest freshquant/tests/test_quality_stock_universe.py freshquant/tests/test_gantt_dagster_ops.py freshquant/tests/test_gantt_readmodel.py freshquant/tests/test_gantt_routes.py -q`

Expected: PASS

**Step 2: Run frontend safety verification**

Run: `node --test morningglory/fqwebui/src/views/shouban30Aggregation.test.mjs morningglory/fqwebui/src/views/shouban30ChanlunFilter.test.mjs morningglory/fqwebui/src/views/shouban30StockFilters.test.mjs`

Expected: PASS

### Task 5: 用真实并行环境重建最新 shouban30 快照

**Files:**
- No file changes

**Step 1: Rebuild latest snapshots**

在并行 Docker 环境中执行最小重建，目标日期固定为 `2026-03-09`：

- 调用 `persist_shouban30_for_date('2026-03-09', stock_window_days=30|45|60|90)` 或现有 Dagster helper

优先使用容器内 Python 运行，保证依赖完整。

**Step 2: Verify database state**

查 `freshquant_gantt.shouban30_stocks`：

- 三类新增字段已存在
- `credit_subject_snapshot_ready` 应为 `true`
- `is_credit_subject` 应有非零命中
- `quality_subject_snapshot_ready` 预期可能仍为 `false`
- `near_long_term_ma_passed` 需要记录真实命中数

**Step 3: Verify API state**

Run:

- `GET http://127.0.0.1:15000/api/gantt/shouban30/stocks?...`

Expected:

- 返回 item 包含新增字段
- 页面不再因字段缺失导致三按钮一开即空

### Task 6: 更新迁移记录并收尾

**Files:**
- Modify: `docs/migration/progress.md`

**Step 1: Update migration note**

在 RFC 0027 备注中追加本次修复说明：

- 修复 `quality_stock_universe` PyMongo `Collection` 读取异常
- 修复 latest snapshot legacy 判定漏检 `shouban30_stocks` 额外筛选字段
- 记录 `2026-03-09` 重建后的真实字段分布

**Step 2: Run focused verification**

Run: `py -3.12 -m pytest freshquant/tests/test_quality_stock_universe.py freshquant/tests/test_gantt_dagster_ops.py freshquant/tests/test_gantt_readmodel.py freshquant/tests/test_gantt_routes.py -q`

Expected: PASS

**Step 3: Commit**

```bash
git add docs/plans/2026-03-10-shouban30-extra-filter-snapshot-repair-design.md docs/plans/2026-03-10-shouban30-extra-filter-snapshot-repair.md docs/migration/progress.md freshquant/data/quality_stock_universe.py morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py freshquant/tests/test_quality_stock_universe.py freshquant/tests/test_gantt_dagster_ops.py
git commit -m "fix: 修复 shouban30 额外筛选快照重建"
```
