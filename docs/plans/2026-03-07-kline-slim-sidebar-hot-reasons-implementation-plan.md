# KlineSlim 左侧股票池与热门原因历史 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 `KlineSlim` 恢复最小左侧股票池列表，并补齐名称展示、单展开 accordion、非持仓列表删除，以及新的 `stock_hot_reason_daily` hover 热门原因历史。

**Architecture:** 现有后端读模型、接口与空分类语义已经落地，这一轮在不新增后端接口的前提下，继续用 TDD 补前端 sidebar 纯逻辑和页面交互，恢复名称双行展示、默认 `持仓股` 单展开 accordion、以及非持仓列表删除。整个实现保持 RFC 0015 的边界，只补最小工作流，不迁回旧 `KlineSlim` 其它工作台功能。

**Tech Stack:** Python、Flask、MongoDB read model、Dagster、Vue 3、Element Plus、Node test runner、pytest

---

### Task 1: 先用测试锁定 `stock_hot_reason_daily` 的纯函数与持久化语义

**Files:**
- Modify: `freshquant/data/gantt_readmodel.py`
- Modify: `freshquant/tests/test_gantt_readmodel.py`

**Step 1: 写失败测试**

```python
def test_build_stock_hot_reason_rows_joins_plate_reason_and_sorts_time():
    rows = build_stock_hot_reason_rows(
        gantt_stock_rows=[
            {
                "provider": "xgb",
                "trade_date": "2026-03-05",
                "plate_key": "11",
                "plate_name": "robotics",
                "code6": "000001",
                "name": "alpha",
                "stock_reason": "stock reason",
                "time": "09:31",
            }
        ],
        plate_reason_rows=[
            {
                "provider": "xgb",
                "trade_date": "2026-03-05",
                "plate_key": "11",
                "reason_text": "plate reason",
                "source_ref": {"trade_date": "2026-03-05", "plate_id": 11},
            }
        ],
    )
    assert rows[0]["plate_reason"] == "plate reason"
```

**Step 2: 跑测试确认失败**

Run: `py -3 -m pytest freshquant/tests/test_gantt_readmodel.py -k stock_hot_reason -q`
Expected: FAIL，提示 `build_stock_hot_reason_rows` 或 `persist_stock_hot_reason_daily_for_date` 不存在。

**Step 3: 写最小实现**

```python
def build_stock_hot_reason_rows(*, gantt_stock_rows, plate_reason_rows):
    reason_map = {
        (row["provider"], row["trade_date"], row["plate_key"]): row
        for row in plate_reason_rows
    }
    ...


def persist_stock_hot_reason_daily_for_date(trade_date: str) -> int:
    rows = build_stock_hot_reason_rows(...)
    ...
```

- 在 `freshquant/data/gantt_readmodel.py` 中新增：
  - `COL_STOCK_HOT_REASON_DAILY`
  - `build_stock_hot_reason_rows()`
  - `persist_stock_hot_reason_daily_for_date()`
  - `query_stock_hot_reason_rows()`
- 为新集合加索引：
  - `provider + trade_date + plate_key + code6`
  - `code6 + trade_date`

**Step 4: 回跑测试**

Run: `py -3 -m pytest freshquant/tests/test_gantt_readmodel.py -k stock_hot_reason -q`
Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/data/gantt_readmodel.py freshquant/tests/test_gantt_readmodel.py
git commit -m "test: cover stock hot reason readmodel"
```

### Task 2: 接上 `/api/gantt/stocks/reasons` 与 Dagster 盘后 op

**Files:**
- Modify: `freshquant/rear/gantt/routes.py`
- Modify: `freshquant/tests/test_gantt_routes.py`
- Modify: `morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py`
- Modify: `morningglory/fqdagster/src/fqdagster/defs/jobs/gantt.py`
- Modify: `freshquant/tests/test_gantt_dagster_import.py`

**Step 1: 写失败测试**

```python
def test_get_gantt_stock_reasons_returns_desc_items(monkeypatch):
    ...
    response = client.get("/api/gantt/stocks/reasons?code6=000001")
    assert response.status_code == 200
    assert response.get_json()["data"]["items"][0]["provider"] == "xgb"
```

**Step 2: 跑测试确认失败**

Run: `py -3 -m pytest freshquant/tests/test_gantt_routes.py freshquant/tests/test_gantt_dagster_import.py -k "stock_reasons or gantt_dagster_modules_import" -q`
Expected: FAIL，提示路由或 Dagster op 未定义。

**Step 3: 写最小实现**

```python
@gantt_bp.route("/stocks/reasons")
def get_gantt_stock_reasons():
    code6 = _required_arg("code6")
    provider = (_required_arg("provider") or "all").lower()
    ...
    items = svc.query_stock_hot_reason_rows(code6=code6, provider=provider, limit=limit)
    return jsonify({"data": {"items": items}})
```

```python
@op
def op_build_stock_hot_reason_daily(context, trade_date: str) -> str:
    count = persist_stock_hot_reason_daily_for_date(trade_date)
    context.log.info("built stock_hot_reason_daily rows=%s trade_date=%s", count, trade_date)
    return trade_date
```

- 在 `job_gantt_postclose()` 中插入：
  - `trade_date = op_build_stock_hot_reason_daily(trade_date)`
  - 再接 `op_build_shouban30_daily(trade_date)`

**Step 4: 回跑测试**

Run: `py -3 -m pytest freshquant/tests/test_gantt_routes.py freshquant/tests/test_gantt_dagster_import.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/rear/gantt/routes.py freshquant/tests/test_gantt_routes.py morningglory/fqdagster/src/fqdagster/defs/ops/gantt.py morningglory/fqdagster/src/fqdagster/defs/jobs/gantt.py freshquant/tests/test_gantt_dagster_import.py
git commit -m "feat: expose stock hot reason history"
```

### Task 3: 修正 `stock_pre_pools` 空分类语义并补后端测试

**Files:**
- Modify: `freshquant/stock_service.py`
- Create: `freshquant/tests/test_stock_pool_service.py`
- Modify: `freshquant/rear/stock/routes.py`

**Step 1: 写失败测试**

```python
def test_get_stock_pre_pools_list_without_category_returns_all(monkeypatch):
    ...
    result = stock_service.get_stock_pre_pools_list(page=1, category="")
    assert [row["code"] for row in result] == ["000002", "000001"]
```

**Step 2: 跑测试确认失败**

Run: `py -3 -m pytest freshquant/tests/test_stock_pool_service.py -q`
Expected: FAIL，当前实现会只查 `category=""`。

**Step 3: 写最小实现**

```python
def get_stock_pre_pools_list(page=1, category=""):
    query = {}
    if str(category or "").strip():
        query["category"] = str(category).strip()
    data = list(DBfreshquant["stock_pre_pools"].find(query).sort("datetime", pymongo.DESCENDING))
    ...
```

- 同步清理 `freshquant/rear/stock/routes.py` 中重复读取 `category` 的代码，确保空值正确透传。

**Step 4: 回跑测试**

Run: `py -3 -m pytest freshquant/tests/test_stock_pool_service.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add freshquant/stock_service.py freshquant/tests/test_stock_pool_service.py freshquant/rear/stock/routes.py
git commit -m "fix: merge stock pre pools when category omitted"
```

### Task 4: 先用测试锁定 sidebar 的名称展示、accordion 与删除元数据

**Files:**
- Create: `morningglory/fqwebui/src/views/js/kline-slim-sidebar.mjs`
- Create: `morningglory/fqwebui/tests/kline-slim-sidebar.test.mjs`
- Modify: `morningglory/fqwebui/src/api/ganttApi.js`

**Step 1: 写失败测试**

```javascript
test('buildSidebarSections keeps fixed order and default expanded holding section', () => {
  const sections = buildSidebarSections({
    holdings: [{ symbol: 'sh600000', code: '600000', name: 'alpha' }],
    mustPools: [{ symbol: 'sz000001', code: '000001', name: 'beta' }],
    stockPools: [],
    prePools: [{ symbol: 'sz000002', code: '000002', name: 'gamma' }]
  })
  assert.deepEqual(sections.map(item => item.key), ['holding', 'must_pool', 'stock_pools', 'stock_pre_pools'])
  assert.equal(sections[0].expanded, true)
  assert.equal(sections[1].deletable, true)
})
```

**Step 2: 跑测试确认失败**

Run: `node --test tests/kline-slim-sidebar.test.mjs`
Expected: FAIL，提示 helper 未定义。

**Step 3: 写最小实现**

```javascript
export const buildSidebarSections = ({ holdings = [], mustPools = [], stockPools = [], prePools = [] } = {}) => [
  { key: 'holding', label: '持仓股', items: holdings, expanded: true, deletable: false },
  { key: 'must_pool', label: 'must_pool', items: mustPools, expanded: false, deletable: true },
  { key: 'stock_pools', label: 'stock_pools', items: stockPools, expanded: false, deletable: true },
  { key: 'stock_pre_pools', label: 'stock_pre_pools', items: prePools, expanded: false, deletable: true }
]
```

```javascript
export const getGanttStockReasons = ({ code6, provider = 'all', limit = 0 } = {}) => {
  return http({
    url: '/api/gantt/stocks/reasons',
    method: 'get',
    params: { code6, provider, limit }
  })
}
```

- helper 中至少覆盖：
  - 固定分组顺序
  - 标的代码标准化
  - 默认展开分组与单展开切换
  - 列表项是否可删除的元数据
  - hover 结果字段标准化
  - 空态/失败态文案

**Step 4: 回跑测试**

Run: `node --test tests/kline-slim-sidebar.test.mjs`
Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/js/kline-slim-sidebar.mjs morningglory/fqwebui/tests/kline-slim-sidebar.test.mjs morningglory/fqwebui/src/api/ganttApi.js
git commit -m "test: cover kline slim sidebar helpers"
```

### Task 5: 把 sidebar / hover / 删除交互接到 `KlineSlim` 页面

**Files:**
- Modify: `morningglory/fqwebui/src/views/KlineSlim.vue`
- Modify: `morningglory/fqwebui/src/views/js/kline-slim.js`
- Modify: `morningglory/fqwebui/src/api/stockApi.js`

**Step 1: 先补页面交互测试或检查清单**

```text
- 左侧四组列表存在且顺序固定
- 默认只展开持仓股
- 同时只能展开一个列表
- 每条列表项显示名称和代码
- 非持仓列表存在删除按钮
- 点击列表项后主图区切换 symbol
- 点击删除不会触发切图
- 删除后刷新对应列表
- hover 时只对首个 code6 发起一次 reasons 请求
- 空态显示“暂无热门记录”
```

**Step 2: 写最小实现**

- `stockApi.js` 继续复用：
  - `getHoldingPositionList()`
  - `getStockMustPoolsList()`
  - `getStockPoolsList()`
  - `getStockPrePoolsList()`
- `kline-slim.js` 新增：
  - 4 组列表加载状态
  - 统一 `sidebarSections`
  - `expandedSidebarKey` 与 accordion 切换
  - 点击切换 symbol
  - 删除动作与按列表刷新
  - `reasonCache / reasonLoading / reasonError`
  - hover 懒加载 `getGanttStockReasons`
- `KlineSlim.vue` 新增：
  - 左侧列表布局
  - 分组 header 折叠/展开按钮
  - 列表项名称 + 代码双行布局
  - 非持仓删除按钮与确认框
  - hover 弹层
  - 当前项高亮与空态展示

**Step 3: 跑前端测试**

Run: `node --test tests/kline-slim-default-symbol.test.mjs tests/kline-slim-sidebar.test.mjs`
Expected: PASS

**Step 4: 跑构建验证**

Run: `npm run build`
Workdir: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui`
Expected: PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/KlineSlim.vue morningglory/fqwebui/src/views/js/kline-slim.js morningglory/fqwebui/src/api/stockApi.js
git commit -m "feat: restore kline slim sidebar and hover reasons"
```

### Task 6: 全链路回归、文档更新与合并前验收

**Files:**
- Modify: `docs/migration/progress.md`
- Modify: `docs/migration/breaking-changes.md`
- Verify only: `docs/rfcs/0015-kline-slim-sidebar-hot-reasons.md`

**Step 1: 后端回归**

Run: `py -3 -m pytest freshquant/tests/test_gantt_readmodel.py freshquant/tests/test_gantt_routes.py freshquant/tests/test_gantt_dagster_import.py freshquant/tests/test_stock_pool_service.py -q`
Expected: PASS

**Step 2: 前端回归**

Run:
- `node --test tests/kline-slim-default-symbol.test.mjs tests/kline-slim-sidebar.test.mjs`
- `npm run build`

Workdir: `D:\fqpack\freshquant-2026.2.23\morningglory\fqwebui`

Expected: PASS

**Step 3: Dagster 导入 smoke**

Run: `py -3 -m pytest freshquant/tests/test_gantt_dagster_import.py -q`
Expected: PASS

**Step 4: 文档与进度同步**

- `docs/migration/progress.md`：状态改为 `Implementing` 或 `Done`
- `docs/migration/breaking-changes.md`：登记 `get_stock_pre_pools_list` 空分类语义变化

**Step 5: Commit**

```bash
git add docs/migration/progress.md docs/migration/breaking-changes.md
git commit -m "docs: record kline slim sidebar migration status"
```
