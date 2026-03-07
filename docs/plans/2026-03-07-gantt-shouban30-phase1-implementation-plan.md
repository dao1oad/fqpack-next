# Gantt Shouban30 首期页面迁移 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在目标仓库实现 `/gantt/shouban30` 首期页面，只覆盖页面骨架、30天首板列表、板块下标的列表，以及基于历史全量热门理由的标的详情。

**Architecture:** 继续以 `freshquant_gantt` 盘后读模型为单一事实源，扩展 `shouban30_plates / shouban30_stocks` 的 `stock_window_days` 维度，不在页面请求期重算。页面详情直接复用全局 `stock_hot_reason_daily` 及 `/api/gantt/stocks/reasons`，避免为 `shouban30` 再建专门详情集合。

**Tech Stack:** Python 3.12、Flask、MongoDB、Dagster、Vue 3、Element Plus、pytest

---

### Task 1: 锁定 `shouban30` 读模型窗口语义

**Files:**
- Modify: `freshquant/data/gantt_readmodel.py`
- Test: `freshquant/tests/test_gantt_readmodel.py`

**Step 1: Write the failing test**

```python
def test_select_shouban30_plate_rows_distinguishes_stock_window_days():
    rows = [
        {"provider": "xgb", "plate_key": "11", "as_of_date": "2026-03-07", "stock_window_days": 30, "plate_name": "robot"},
        {"provider": "xgb", "plate_key": "11", "as_of_date": "2026-03-07", "stock_window_days": 60, "plate_name": "robot"},
    ]
    items = select_shouban30_plate_rows(
        rows,
        provider="xgb",
        as_of_date="2026-03-07",
        stock_window_days=60,
    )
    assert items == [rows[1]]
```

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest -q freshquant/tests/test_gantt_readmodel.py -k shouban30`

Expected: FAIL because `select_shouban30_plate_rows()` and `select_shouban30_stock_rows()` do not yet filter by `stock_window_days`.

**Step 3: Write minimal implementation**

```python
def select_shouban30_plate_rows(rows, *, provider, as_of_date=None, stock_window_days=None):
    target_window = _to_int(stock_window_days, 30)
    filtered = [
        item for item in rows
        if _to_str(item.get("provider")) == provider
        and _to_int(item.get("stock_window_days"), 30) == target_window
    ]
```

同时对 `select_shouban30_stock_rows()` 做同样扩展。

**Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest -q freshquant/tests/test_gantt_readmodel.py -k shouban30`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/data/gantt_readmodel.py freshquant/tests/test_gantt_readmodel.py
git commit -m "feat: add stock window selection to shouban30 readmodel"
```

### Task 2: 扩展 `persist_shouban30_for_date()` 输出 schema

**Files:**
- Modify: `freshquant/data/gantt_readmodel.py`
- Test: `freshquant/tests/test_gantt_readmodel.py`

**Step 1: Write the failing test**

```python
def test_persist_shouban30_for_date_writes_stock_window_fields(monkeypatch):
    result = persist_shouban30_for_date("2026-03-07")
    assert result["stock_window_days"] == 30
```

再增加断言验证：

- `shouban30_plates` 包含 `stock_window_days`, `stocks_count`, `stock_window_from`, `stock_window_to`
- `shouban30_stocks` 包含 `stock_window_days`, `hit_count_window`, `latest_reason`

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest -q freshquant/tests/test_gantt_readmodel.py -k persist_shouban30`

Expected: FAIL because current schema still是最小字段集。

**Step 3: Write minimal implementation**

```python
def persist_shouban30_for_date(as_of_date: str, *, stock_window_days: int = 30) -> dict[str, Any]:
    start_window = _calc_start_date(date_str, stock_window_days)
```

同时：

- 为 `shouban30_plates` 写入 `stock_window_days` 与 `stocks_count`
- 为 `shouban30_stocks` 写入 `stock_window_days`、`hit_count_window`、`latest_reason`
- 维持 `hit_count_30` 作为 30天首板上下文字段

**Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest -q freshquant/tests/test_gantt_readmodel.py -k persist_shouban30`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/data/gantt_readmodel.py freshquant/tests/test_gantt_readmodel.py
git commit -m "feat: extend shouban30 readmodel with stock window schema"
```

### Task 3: 让盘后任务构建四档 `stock_window_days`

**Files:**
- Modify: `morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py`
- Test: `freshquant/tests/test_gantt_dagster_ops.py`
- Test: `freshquant/tests/test_gantt_dagster_import.py`

**Step 1: Write the failing test**

```python
def test_op_run_gantt_postclose_builds_all_stock_window_days():
    assert called_windows == [30, 45, 60, 90]
```

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest -q freshquant/tests/test_gantt_dagster_ops.py -k shouban30`

Expected: FAIL because current op 只会构建单一窗口。

**Step 3: Write minimal implementation**

```python
for stock_window_days in (30, 45, 60, 90):
    gantt_readmodel.persist_shouban30_for_date(trade_date, stock_window_days=stock_window_days)
```

**Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest -q freshquant/tests/test_gantt_dagster_ops.py freshquant/tests/test_gantt_dagster_import.py`

Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py freshquant/tests/test_gantt_dagster_ops.py freshquant/tests/test_gantt_dagster_import.py
git commit -m "feat: build shouban30 readmodel for all stock windows"
```

### Task 4: 扩展 `shouban30` 列表 API

**Files:**
- Modify: `freshquant/rear/gantt/routes.py`
- Test: `freshquant/tests/test_gantt_routes.py`

**Step 1: Write the failing test**

```python
def test_get_shouban30_plates_accepts_stock_window_days(client):
    response = client.get("/api/gantt/shouban30/plates?provider=xgb&stock_window_days=60")
    assert response.status_code == 200
```

补充断言：

- `stock_window_days` 为空时默认 30
- 非 `30/45/60/90` 返回 400
- `stocks` 接口同样支持该参数

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m pytest -q freshquant/tests/test_gantt_routes.py -k shouban30`

Expected: FAIL because current routes 未处理 `stock_window_days`。

**Step 3: Write minimal implementation**

```python
def _resolve_stock_window_days_arg() -> int:
    raw = request.args.get("stock_window_days", "30")
    value = int(raw)
    if value not in {30, 45, 60, 90}:
        raise ValueError("stock_window_days must be one of 30|45|60|90")
    return value
```

并把该参数传入 `query_shouban30_plate_rows()` / `query_shouban30_stock_rows()`。

**Step 4: Run test to verify it passes**

Run: `py -3.12 -m pytest -q freshquant/tests/test_gantt_routes.py -k shouban30`

Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/rear/gantt/routes.py freshquant/tests/test_gantt_routes.py
git commit -m "feat: add stock window query to shouban30 routes"
```

### Task 5: 增加前端 `shouban30` API 封装

**Files:**
- Create: `morningglory/fqwebui/src/api/ganttShouban30.js`
- Test: `morningglory/fqwebui/src/api/__tests__/ganttShouban30.test.js`

**Step 1: Write the failing test**

```javascript
it('passes stock_window_days to shouban30 plate query', async () => {
  await getShouban30Plates({ provider: 'xgb', stockWindowDays: 60 })
  expect(http).toHaveBeenCalledWith(
    expect.objectContaining({
      url: '/api/gantt/shouban30/plates',
      params: expect.objectContaining({ stock_window_days: 60 })
    })
  )
})
```

**Step 2: Run test to verify it fails**

Run: `npm test -- ganttShouban30.test.js`

Expected: FAIL because API module does not exist.

**Step 3: Write minimal implementation**

```javascript
export const getShouban30Plates = ({ provider = 'xgb', stockWindowDays = 30, asOfDate } = {}) => {
  return http({
    url: '/api/gantt/shouban30/plates',
    method: 'get',
    params: {
      provider,
      stock_window_days: stockWindowDays,
      ...(asOfDate ? { as_of_date: asOfDate } : {})
    }
  })
}
```

**Step 4: Run test to verify it passes**

Run: `npm test -- ganttShouban30.test.js`

Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/api/ganttShouban30.js morningglory/fqwebui/src/api/__tests__/ganttShouban30.test.js
git commit -m "feat: add frontend shouban30 api client"
```

### Task 6: 新增 `/gantt/shouban30` 首期页面骨架

**Files:**
- Create: `morningglory/fqwebui/src/views/GanttShouban30Phase1.vue`
- Modify: `morningglory/fqwebui/src/router/index.js`
- Modify: `morningglory/fqwebui/src/views/MyHeader.vue`
- Test: `morningglory/fqwebui/src/views/__tests__/GanttShouban30Phase1.test.js`

**Step 1: Write the failing test**

```javascript
it('renders provider tabs and stock window buttons', () => {
  render(GanttShouban30Phase1)
  expect(screen.getByText('30天首板')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '30日' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '90日' })).toBeInTheDocument()
})
```

**Step 2: Run test to verify it fails**

Run: `npm test -- GanttShouban30Phase1.test.js`

Expected: FAIL because page component and route do not exist.

**Step 3: Write minimal implementation**

```vue
<template>
  <div class="shouban30-phase1-page">
    <header>30天首板</header>
    <section>provider tabs</section>
    <section>30 / 45 / 60 / 90</section>
    <section>板块列表</section>
    <section>标的列表</section>
    <section>标的详情</section>
  </div>
</template>
```

并在路由中注册 `/gantt/shouban30`，在头部导航中增加入口。

**Step 4: Run test to verify it passes**

Run: `npm test -- GanttShouban30Phase1.test.js`

Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/GanttShouban30Phase1.vue morningglory/fqwebui/src/router/index.js morningglory/fqwebui/src/views/MyHeader.vue morningglory/fqwebui/src/views/__tests__/GanttShouban30Phase1.test.js
git commit -m "feat: add shouban30 phase1 page shell"
```

### Task 7: 接入板块列表与标的列表查询

**Files:**
- Modify: `morningglory/fqwebui/src/views/GanttShouban30Phase1.vue`
- Test: `morningglory/fqwebui/src/views/__tests__/GanttShouban30Phase1.test.js`

**Step 1: Write the failing test**

```javascript
it('reloads plate list when stockWindowDays changes', async () => {
  await user.click(screen.getByRole('button', { name: '60日' }))
  expect(getShouban30Plates).toHaveBeenLastCalledWith(
    expect.objectContaining({ stockWindowDays: 60 })
  )
})
```

**Step 2: Run test to verify it fails**

Run: `npm test -- GanttShouban30Phase1.test.js`

Expected: FAIL because page shell does not yet issue API requests.

**Step 3: Write minimal implementation**

```javascript
watch([provider, stockWindowDays], async () => {
  plates.value = await getShouban30Plates(...)
  selectedPlate.value = null
  stocks.value = []
  selectedStock.value = null
})
```

点击板块后调用 `getShouban30Stocks(...)`。

**Step 4: Run test to verify it passes**

Run: `npm test -- GanttShouban30Phase1.test.js`

Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/GanttShouban30Phase1.vue morningglory/fqwebui/src/views/__tests__/GanttShouban30Phase1.test.js
git commit -m "feat: load shouban30 plates and stocks"
```

### Task 8: 接入标的详情历史全量热门理由

**Files:**
- Modify: `morningglory/fqwebui/src/views/GanttShouban30Phase1.vue`
- Modify: `morningglory/fqwebui/src/api/ganttApi.js`
- Test: `morningglory/fqwebui/src/views/__tests__/GanttShouban30Phase1.test.js`

**Step 1: Write the failing test**

```javascript
it('loads global stock hot reasons when a stock is selected', async () => {
  await user.click(screen.getByText('000001'))
  expect(getGanttStockReasons).toHaveBeenCalledWith({
    code6: '000001',
    provider: 'all',
    limit: 0
  })
})
```

**Step 2: Run test to verify it fails**

Run: `npm test -- GanttShouban30Phase1.test.js`

Expected: FAIL because detail panel is not wired.

**Step 3: Write minimal implementation**

```javascript
const loadStockReasons = async (code6) => {
  const payload = await getGanttStockReasons({ code6, provider: 'all', limit: 0 })
  stockReasons.value = payload?.data?.items || []
}
```

**Step 4: Run test to verify it passes**

Run: `npm test -- GanttShouban30Phase1.test.js`

Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/GanttShouban30Phase1.vue morningglory/fqwebui/src/views/__tests__/GanttShouban30Phase1.test.js morningglory/fqwebui/src/api/ganttApi.js
git commit -m "feat: add shouban30 stock detail panel"
```

### Task 9: 端到端验证与治理文档收口

**Files:**
- Modify: `docs/migration/progress.md`
- Modify: `docs/migration/breaking-changes.md`
- Verify: `freshquant/tests/test_gantt_readmodel.py`
- Verify: `freshquant/tests/test_gantt_routes.py`
- Verify: `freshquant/tests/test_gantt_dagster_ops.py`
- Verify: `morningglory/fqwebui`

**Step 1: Run focused backend tests**

Run: `py -3.12 -m pytest -q freshquant/tests/test_gantt_readmodel.py freshquant/tests/test_gantt_routes.py freshquant/tests/test_gantt_dagster_ops.py`

Expected: PASS

**Step 2: Run focused frontend tests**

Run: `npm test -- GanttShouban30Phase1.test.js ganttShouban30.test.js`

Expected: PASS

**Step 3: Run frontend build**

Run: `npm run build`

Expected: PASS with production bundle emitted

**Step 4: Update governance docs**

- `docs/migration/progress.md`
  - 将 RFC 0017 从 `Approved` 更新到 `Done`
- `docs/migration/breaking-changes.md`
  - 记录 `shouban30` 读模型扩展 `stock_window_days`
  - 记录页面不再触发导出/重算

**Step 5: Commit**

```bash
git add docs/migration/progress.md docs/migration/breaking-changes.md
git commit -m "docs: close out shouban30 phase1 migration"
```
