# Stock Block Safe Refresh Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复目标仓库 `stock_block` 刷新在失败时清空板块库的问题，为 `quality_stock_universe` 和 `shouban30` 的 `优质标的` 恢复稳定上游。

**Architecture:** 保持 Dagster asset `stock_block` 的对外形态不变，只在 [`morningglory/fqdagster/src/fqdagster/defs/assets/market_data.py`](D:/fqpack/freshquant-2026.2.23/morningglory/fqdagster/src/fqdagster/defs/assets/market_data.py) 内增加安全刷新 helper。helper 负责按来源收集 block 文档、只替换成功来源、在全源失败时保留旧数据。`quality_stock_universe` 和 `shouban30` 链路不改，只做运行态验证。

**Tech Stack:** Python 3.12, pytest, Dagster asset stubs, PyMongo-style fake collections

---

### Task 1: 先写失败测试，锁住安全刷新语义

**Files:**
- Create: `freshquant/tests/test_market_data_assets.py`

**Step 1: Write the failing test**

新增测试：

- `test_refresh_stock_block_keeps_existing_docs_when_all_sources_fail`
  - 准备一个已有旧文档的 fake collection
  - `tdx/tushare` 都返回异常或空结果
  - 断言 helper 不删除旧文档
- `test_refresh_stock_block_replaces_only_successful_sources`
  - 初始 collection 同时有 `tdx` 和 `tushare` 旧文档
  - 新一轮只有 `tdx` 成功
  - 断言：
    - `tdx` 被替换成新文档
    - `tushare` 旧文档保留
    - 新文档带 `source=tdx`

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_market_data_assets.py -q`

Expected:

- 因 helper 尚未实现而失败

### Task 2: 在目标仓库 asset 文件中实现最小安全 helper

**Files:**
- Modify: `morningglory/fqdagster/src/fqdagster/defs/assets/market_data.py`

**Step 1: Write minimal implementation**

在 asset 文件中增加内部函数：

- `_load_stock_block_docs_by_source(...)`
- `_refresh_stock_block_collection(...)`
- `_save_stock_block_safe(context)`

实现要求：

- 远端来源固定为 `tdx`、`tushare`
- 全源失败或全空时只 warning，不删库
- 成功来源按 `source` 定向删旧写新
- 维持 `code` 索引
- `stock_block` asset 改为调用 `_save_stock_block_safe(context)`

**Step 2: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_market_data_assets.py -q`

Expected: PASS

### Task 3: 跑关联回归测试

**Files:**
- Test: `freshquant/tests/test_quality_stock_universe.py`
- Test: `freshquant/tests/test_gantt_dagster_ops.py`
- Test: `freshquant/tests/test_gantt_readmodel.py`
- Test: `freshquant/tests/test_gantt_routes.py`

**Step 1: Run backend verification**

Run: `py -3.12 -m pytest freshquant/tests/test_market_data_assets.py freshquant/tests/test_quality_stock_universe.py freshquant/tests/test_gantt_dagster_ops.py freshquant/tests/test_gantt_readmodel.py freshquant/tests/test_gantt_routes.py -q`

Expected: PASS

### Task 4: 用真实并行环境验证优质标的上游状态

**Files:**
- No file changes

**Step 1: Check current source state**

查：

- `quantaxis.stock_block`
- `freshquant.quality_stock_universe`

记录刷新前数量。

**Step 2: Attempt refresh**

优先调用当前运行环境里的刷新入口：

- `stock_block` asset 对应 Python 函数
- 或等价的 block refresh helper

再执行：

- `refresh_quality_stock_universe()`

**Step 3: Verify result**

记录：

- `stock_block` 是否恢复非空
- `quality_stock_universe` 是否恢复非空
- 若恢复，再抽样核对 `QUALITY_STOCK_BLOCK_NAMES` 命中情况

### Task 5: 更新迁移记录并收尾

**Files:**
- Modify: `docs/migration/progress.md`

**Step 1: Update migration note**

在 RFC 0027 备注中追加：

- 迁移 `stock_block` 安全刷新语义
- 说明它修复的是 `优质标的` 上游板块库被清空的问题
- 记录本轮刷新验证结果

**Step 2: Final verification**

Run: `py -3.12 -m pytest freshquant/tests/test_market_data_assets.py freshquant/tests/test_quality_stock_universe.py freshquant/tests/test_gantt_dagster_ops.py freshquant/tests/test_gantt_readmodel.py freshquant/tests/test_gantt_routes.py -q`

Expected: PASS
