# Guardian 持仓代码刷新 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复 Guardian 对外部新持仓代码的识别与持仓代码缓存失效问题，让 holding codes 同时参考 `xt_positions` 与订单域持仓投影，并在订单域持仓变化后及时刷新。

**Architecture:** 在 `holding.py` 内把 holding codes 改成 “`xt_positions` + 订单域持仓投影” 的并集读取，并继续保留版本化缓存；为该缓存增加短 TTL 兜底。随后在 XT 成交入账与外部订单对账确认路径补齐 `mark_stock_holdings_projection_updated()`，并用单元测试锁定行为。

**Tech Stack:** Python 3.12, pytest, Mongo adapter helpers, memoized cache helpers

---

### Task 1: 修复 holding codes 数据源与缓存

**Files:**
- Modify: `freshquant/data/astock/holding.py`
- Test: `freshquant/tests/test_order_management_holding_adapter.py`

**Step 1: Write the failing test**

```python
def test_get_stock_holding_codes_merges_xt_positions_and_projection(monkeypatch):
    _, holding_module, _ = _reload_modules(monkeypatch)
    monkeypatch.setattr(
        holding_module,
        "get_stock_positions",
        lambda: [{"symbol": "sz000001"}],
    )
    fake_collection = type(
        "FakeCollection",
        (),
        {"find": lambda self, *args, **kwargs: [{"stock_code": "600000.SH"}]},
    )()
    monkeypatch.setattr(
        holding_module,
        "DBfreshquant",
        {"xt_positions": fake_collection},
    )
    assert holding_module.get_stock_holding_codes() == ["000001", "600000"]
```

**Step 2: Run test to verify it fails**

Run: `py -m pytest -q freshquant/tests/test_order_management_holding_adapter.py -k holding_codes`
Expected: FAIL because current implementation only returns order management positions.

**Step 3: Write minimal implementation**

```python
@redis_cache.memoize(expiration=15)
def _get_stock_holding_codes_cached(_version):
    codes = set(_iter_projection_codes())
    codes.update(_iter_xt_position_codes())
    return sorted(codes)
```

**Step 4: Run test to verify it passes**

Run: `py -m pytest -q freshquant/tests/test_order_management_holding_adapter.py -k holding_codes`
Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/data/astock/holding.py freshquant/tests/test_order_management_holding_adapter.py
git commit -m "fix: 修复 Guardian 持仓代码读取"
```

### Task 2: 补齐订单域持仓变化后的缓存失效

**Files:**
- Modify: `freshquant/order_management/ingest/xt_reports.py`
- Modify: `freshquant/order_management/reconcile/service.py`
- Test: `freshquant/tests/test_order_management_reconcile.py`
- Test: `freshquant/tests/test_order_management_xt_ingest.py`

**Step 1: Write the failing test**

```python
def test_ingest_trade_report_marks_holding_projection_updated(monkeypatch):
    called = []
    monkeypatch.setattr(
        "freshquant.order_management.ingest.xt_reports.mark_stock_holdings_projection_updated",
        lambda: called.append(True),
    )
    ...
    assert called == [True]
```

```python
def test_confirm_expired_candidates_marks_holding_projection_updated(monkeypatch):
    called = []
    monkeypatch.setattr(
        "freshquant.order_management.reconcile.service.mark_stock_holdings_projection_updated",
        lambda: called.append(True),
    )
    ...
    assert called == [True]
```

**Step 2: Run tests to verify they fail**

Run: `py -m pytest -q freshquant/tests/test_order_management_xt_ingest.py freshquant/tests/test_order_management_reconcile.py`
Expected: FAIL because these paths do not invalidate holding codes yet.

**Step 3: Write minimal implementation**

```python
result = self.ingest_service.ingest_trade_report(...)
mark_stock_holdings_projection_updated()
return result
```

```python
result = self.ingest_service.ingest_trade_report(...)
mark_stock_holdings_projection_updated()
updated_candidate = self.repository.update_external_candidate(...)
```

**Step 4: Run tests to verify they pass**

Run: `py -m pytest -q freshquant/tests/test_order_management_xt_ingest.py freshquant/tests/test_order_management_reconcile.py`
Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/order_management/ingest/xt_reports.py freshquant/order_management/reconcile/service.py freshquant/tests/test_order_management_xt_ingest.py freshquant/tests/test_order_management_reconcile.py
git commit -m "fix: 补齐持仓代码缓存失效链路"
```

### Task 3: 同步迁移记录并做全量验证

**Files:**
- Modify: `docs/migration/progress.md`
- Modify: `docs/migration/breaking-changes.md`

**Step 1: Update migration docs**

```markdown
2026-03-07：RFC 0007 追加修复 holding codes 读取口径与缓存失效链路。
```

**Step 2: Run focused verification**

Run: `py -m pytest -q freshquant/tests/test_order_management_holding_adapter.py freshquant/tests/test_order_management_xt_ingest.py freshquant/tests/test_order_management_reconcile.py`
Expected: PASS

**Step 3: Run full verification**

Run: `py -m pytest -q freshquant/tests`
Expected: PASS

**Step 4: Commit**

```bash
git add docs/migration/progress.md docs/migration/breaking-changes.md
git commit -m "docs: 更新 RFC0007 持仓代码修复进度"
```
