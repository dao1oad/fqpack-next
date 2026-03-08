# XTData 默认模式改为 guardian_1m Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让 `monitor.xtdata.mode` 在缺省时默认执行 `guardian_1m`，并保持显式 `clx_15_30` 兼容。

**Architecture:** 在 XTData 现有模块中增加统一的 mode 标准化 helper，由 Producer、Consumer、Guardian 与初始化脚本共同复用；通过单测锁定“缺省回退 guardian_1m、显式配置保持原值”的行为。

**Tech Stack:** Python 3.12、pytest、Mongo 参数初始化逻辑

---

### Task 1: 为 XTData mode 缺省语义写失败测试

**Files:**
- Create: `freshquant/tests/test_xtdata_mode_defaults.py`

**Step 1: Write the failing test**

```python
def test_normalize_xtdata_mode_defaults_to_guardian():
    assert normalize_xtdata_mode(None) == "guardian_1m"
```

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest freshquant/tests/test_xtdata_mode_defaults.py -q`
Expected: FAIL because helper does not exist yet

### Task 2: 实现统一 XTData mode helper

**Files:**
- Modify: `freshquant/market_data/xtdata/pools.py`
- Modify: `freshquant/market_data/xtdata/market_producer.py`
- Modify: `freshquant/market_data/xtdata/strategy_consumer.py`
- Modify: `freshquant/signal/astock/job/monitor_stock_zh_a_min.py`

**Step 1: Add helper**

- 定义 `DEFAULT_XTDATA_MODE = "guardian_1m"`
- 定义 `normalize_xtdata_mode(...)`

**Step 2: Replace hard-coded defaults**

- Producer / Consumer / Guardian 统一改为调用 helper

**Step 3: Run tests**

Run: `py -3.12 -m pytest freshquant/tests/test_xtdata_mode_defaults.py -q`
Expected: PASS

### Task 3: 更新初始化默认值

**Files:**
- Modify: `freshquant/preset/params.py`
- Update: `freshquant/tests/test_xtdata_mode_defaults.py`

**Step 1: Add failing test for preset default**

- 验证 `init_param_dict(quiet=True)` 在 mode 缺失时写入 `guardian_1m`

**Step 2: Implement minimal change**

- 将 `xtdata_mode` 初始化默认值改为共享默认常量

**Step 3: Run focused tests**

Run: `py -3.12 -m pytest freshquant/tests/test_xtdata_mode_defaults.py -q`
Expected: PASS

### Task 4: 更新治理文档

**Files:**
- Create: `docs/rfcs/0021-xtdata-default-guardian-mode.md`
- Update: `docs/migration/progress.md`
- Update: `docs/migration/breaking-changes.md`

**Step 1: Record the new default semantics**

- 写清楚仅影响缺省 mode，不覆盖显式配置

### Task 5: 完整验证

**Files:**
- Verify runtime without touching unrelated modules

**Step 1: Run tests**

Run: `py -3.12 -m pytest freshquant/tests/test_xtdata_mode_defaults.py freshquant/tests/test_xtdata_market_producer_tpsl_union.py -q`
Expected: PASS

**Step 2: Optional host verification**

- 重启宿主机 `fqnext_realtime_xtdata_producer` / `fqnext_realtime_xtdata_consumer`
- 检查 log 中 `prewarm codes` 是否从 0 变为持仓数量
