# Quality Stock 21-Board Fallback Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将宿主机本地 TDX `infoharbor_block.dat` 提升为 `stock_block` 的正式 fallback 数据源，使 `quality_stock_universe` 在远端 block 源失效时也能稳定恢复到完整 `21/21` 优质板块。

**Architecture:** 保持现有 `stock_block -> quality_stock_universe -> shouban30` 日更链路不变，只在 `stock_block` 的安全刷新 helper 中新增本机 TDX `infoharbor_block.dat` 解析来源，并在 `quality_stock_universe` 增加板块名标准化。这样既能恢复 `21/21`，又不会让 `quality_stock_universe` 脱离 `stock_block` 单独维护。

**Tech Stack:** Python 3.12, pytest, Dagster asset helper, PyMongo-style fake collections, local TDX text parsing

---

### Task 1: 先写失败测试，锁住 `infoharbor_block` fallback 与别名标准化

**Files:**
- Modify: `freshquant/tests/test_market_data_assets.py`
- Modify: `freshquant/tests/test_quality_stock_universe.py`

**Step 1: Write the failing test**

在 `freshquant/tests/test_market_data_assets.py` 新增：

- `test_parse_tdx_infoharbor_block_text_parses_quality_blocks`
- `test_refresh_stock_block_uses_local_infoharbor_when_remote_sources_fail`

在 `freshquant/tests/test_quality_stock_universe.py` 新增：

- `test_refresh_quality_stock_universe_normalizes_infoharbor_aliases`

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_market_data_assets.py freshquant/tests/test_quality_stock_universe.py -q`

Expected:

- 因缺少 `infoharbor` 解析 helper 和别名标准化而失败

### Task 2: 实现本机 TDX `infoharbor_block.dat` 解析

**Files:**
- Modify: `morningglory/fqdagster/src/fqdagster/defs/assets/market_data.py`

**Step 1: Write minimal implementation**

新增内部 helper：

- `_parse_tdx_infoharbor_block_text`
- `_iter_tdx_infoharbor_codes`
- `_load_local_tdx_infoharbor_docs`

实现要求：

- 按 `gbk` 解码 `infoharbor_block.dat`
- 识别 `#FG_` / `#ZS_` 等块头
- 解析后续 `0#000001` / `1#600000` 形式代码
- 生成 `{"code": "...", "blockname": "...", "source": "tdx_infoharbor"}` 文档
- 在 `_refresh_stock_block_collection` 之前把该来源并入 `docs_by_source`

**Step 2: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_market_data_assets.py::test_parse_tdx_infoharbor_block_text_parses_quality_blocks -q`

Expected: PASS

### Task 3: 实现 `quality_stock_universe` 板块名标准化

**Files:**
- Modify: `freshquant/data/quality_stock_universe.py`

**Step 1: Write minimal implementation**

新增轻量 helper：

- `_canonicalize_quality_block_name`

规则：

- `中证央企 -> “中证央企”`
- 其他板块名保持原样

并在 `refresh_quality_stock_universe()` 归并 `block_lookup` 前使用。

**Step 2: Run test to verify it passes**

Run: `py -3.12 -m pytest freshquant/tests/test_quality_stock_universe.py::test_refresh_quality_stock_universe_normalizes_infoharbor_aliases -q`

Expected: PASS

### Task 4: 跑关联回归

**Files:**
- Test: `freshquant/tests/test_market_data_assets.py`
- Test: `freshquant/tests/test_quality_stock_universe.py`
- Test: `freshquant/tests/test_gantt_dagster_ops.py`
- Test: `freshquant/tests/test_gantt_readmodel.py`
- Test: `freshquant/tests/test_gantt_routes.py`

**Step 1: Run backend verification**

Run: `py -3.12 -m pytest freshquant/tests/test_market_data_assets.py freshquant/tests/test_quality_stock_universe.py freshquant/tests/test_gantt_dagster_ops.py freshquant/tests/test_gantt_readmodel.py freshquant/tests/test_gantt_routes.py -q`

Expected: PASS

### Task 5: 运行态验证 21 个板块恢复

**Files:**
- No file changes

**Step 1: Validate local source coverage**

验证：

- `infoharbor_block.dat` 可解析
- `QUALITY_STOCK_BLOCK_NAMES` 全部命中

**Step 2: Validate runtime chain**

在容器环境验证：

- `stock_block` 刷新后非空
- `quality_stock_universe` 含完整 `21` 个目标板块
- `shouban30` 重建后 `is_quality_subject` 非零

### Task 6: 更新迁移记录

**Files:**
- Modify: `docs/migration/progress.md`

**Step 1: Update migration note**

在 RFC 0027 备注中追加：

- `infoharbor_block.dat` 已成为 `stock_block` 正式 fallback
- `quality_stock_universe` 已恢复到 `21/21`
- 当前运行态验证结果

### Task 7: Final verification

**Step 1: Re-run focused backend tests**

Run: `py -3.12 -m pytest freshquant/tests/test_market_data_assets.py freshquant/tests/test_quality_stock_universe.py freshquant/tests/test_gantt_dagster_ops.py freshquant/tests/test_gantt_readmodel.py freshquant/tests/test_gantt_routes.py -q`

Expected: PASS
