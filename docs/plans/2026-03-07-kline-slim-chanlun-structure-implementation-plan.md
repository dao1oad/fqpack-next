# KlineSlim 缠论结构面板 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 `KlineSlim` 新增“缠论结构”按钮和半透明结构面板，并通过独立的 `fullcalc` 专用接口返回高级段、段、笔及中枢明细。

**Architecture:** 不改现有 `/api/stock_data` 双轨契约，新增独立接口 `GET /api/stock_data_chanlun_structure`。实时模式优先复用 consumer Redis 缓存中的 OHLCV bar，历史模式直接按 `symbol + period + endDate` 取 K 线；两种模式都在接口侧统一执行 `run_fullcalc(df, model_ids=[])`，由独立服务模块提取最后一个高级段、段、笔和中枢明细。前端 `KlineSlim` 手动打开面板、手动刷新，不跟随页面轮询自动刷新。

**Tech Stack:** Python 3.12、Flask、pandas、Redis、fullcalc、本地 pytest、Vue 3、Element Plus、Node test runner

---

### Task 1: 起草 RFC 0018 并登记进度

**Files:**
- Create: `docs/rfcs/0018-kline-slim-chanlun-structure-panel.md`
- Modify: `docs/migration/progress.md`
- Reference: `docs/rfcs/0000-template.md`
- Reference: `docs/plans/2026-03-07-kline-slim-chanlun-structure-design.md`

**Step 1: 复制模板并写出 RFC Draft**

```md
# RFC 0018: KlineSlim 缠论结构面板

Status: Draft

## Goals
- 为 KlineSlim 提供 fullcalc 单一真相源的缠论结构表格
- 同时支持实时模式与历史模式

## Public API
- GET /api/stock_data_chanlun_structure?symbol=<code>&period=<period>&endDate=<optional>
```

- 补齐目标、非目标、范围、模块边界、依赖、Public API、Data/Config、测试与验收、迁移映射。
- 明确本 RFC 会新增对外 HTTP 入口，因此必须先过评审才能编码。

**Step 2: 在 `progress.md` 增加 0017 行**

```md
| 0018 | KlineSlim 缠论结构面板 | Draft | Codex | 2026-03-07 | `D:\fqpack\freshquant\freshquant\data\gantt_shouban30_service.py` / `volume_turnover_screener.py` / `morningglory\fqwebui\src\views\KlineSlim.vue` | 基于 fullcalc 的独立结构接口与 KlineSlim 面板，实时优先复用 consumer 缓存 bar，历史模式现场 fullcalc |
```

**Step 3: 运行文档引用检查**

Run: `rg -n "0017|KlineSlim 缠论结构" docs/rfcs docs/migration/progress.md`

Expected:
- `docs/rfcs/0018-kline-slim-chanlun-structure-panel.md` 被检出
- `docs/migration/progress.md` 中新增 0017 行

**Step 4: Commit**

```bash
git add docs/rfcs/0018-kline-slim-chanlun-structure-panel.md docs/migration/progress.md
git commit -m "docs: 起草 RFC 0018 缠论结构面板"
```

### Task 2: RFC 评审通过后切到 Approved，再进入 Implementing

**Files:**
- Modify: `docs/rfcs/0018-kline-slim-chanlun-structure-panel.md`
- Modify: `docs/migration/progress.md`

**Step 1: 评审通过后把 RFC 状态改为 `Approved`**

```md
Status: Approved
```

**Step 2: 同一提交更新进度表**

```md
| 0018 | KlineSlim 缠论结构面板 | Approved | Codex | 2026-03-07 | ... | RFC 已通过，可开始编码 |
```

**Step 3: 开始编码前立刻切到 `Implementing`**

```md
Status: Implementing
```

```md
| 0018 | KlineSlim 缠论结构面板 | Implementing | Codex | 2026-03-07 | ... | 开始实现后端 fullcalc 结构接口与 KlineSlim 面板 |
```

**Step 4: Commit**

```bash
git add docs/rfcs/0018-kline-slim-chanlun-structure-panel.md docs/migration/progress.md
git commit -m "docs: 更新 RFC 0018 状态为 Implementing"
```

### Task 3: 先用测试锁定后端结构提取服务

**Files:**
- Create: `freshquant/chanlun_structure_service.py`
- Create: `freshquant/tests/test_chanlun_structure_service.py`

**Step 1: 写失败测试，固定段、笔和中枢归属语义**

```python
def test_build_chanlun_structure_extracts_last_higher_segment_segment_and_bi():
    df = pd.DataFrame(
        {
            "datetime": pd.to_datetime(
                [
                    "2026-03-07 09:30",
                    "2026-03-07 09:35",
                    "2026-03-07 09:40",
                    "2026-03-07 09:45",
                ]
            ),
            "open": [10.0, 10.1, 10.2, 10.15],
            "high": [10.1, 10.3, 10.35, 10.4],
            "low": [9.9, 10.0, 10.1, 10.05],
            "close": [10.05, 10.2, 10.15, 10.3],
            "volume": [1, 1, 1, 1],
            "amount": [1, 1, 1, 1],
        }
    )
    fc_res = {
        "ok": True,
        "bi": [0, -1, 0, 1],
        "duan": [0, -1, 0, 1],
        "duan_high": [0, -1, 0, 1],
        "pivots": [{"start": 1, "end": 3, "zg": 10.28, "zd": 10.14, "gg": 10.4, "dd": 10.0, "direction": 1}],
        "pivots_high": [{"start": 1, "end": 3, "zg": 10.28, "zd": 10.14, "gg": 10.4, "dd": 10.0, "direction": 1}],
    }

    result = build_chanlun_structure_payload(
        symbol="sz000001",
        period="5m",
        end_date=None,
        df=df,
        fc_res=fc_res,
        source="realtime_cache_fullcalc",
    )

    assert result["structure"]["higher_segment"]["direction"] == "up"
    assert result["structure"]["segment"]["pivot_count"] == 1
    assert result["structure"]["bi"]["price_change_pct"] == pytest.approx(4.0, rel=1e-3)
```

```python
def test_rebuild_dataframe_from_cache_payload_keeps_ohlcv_alignment():
    payload = {
        "date": ["2026-03-07 09:30", "2026-03-07 09:35"],
        "open": [10.0, 10.1],
        "high": [10.2, 10.3],
        "low": [9.9, 10.0],
        "close": [10.1, 10.2],
        "volume": [100, 120],
        "amount": [1000.0, 1224.0],
    }

    df = build_dataframe_from_cache_payload(payload)
    assert list(df.columns) == ["datetime", "open", "high", "low", "close", "volume", "amount"]
    assert len(df) == 2
```

**Step 2: 运行测试，确认失败**

Run: `py -m pytest freshquant/tests/test_chanlun_structure_service.py -q`

Expected:
- FAIL，提示 `build_chanlun_structure_payload` 或 `build_dataframe_from_cache_payload` 未定义

**Step 3: 写最小实现**

```python
def build_dataframe_from_cache_payload(payload: dict[str, Any]) -> pd.DataFrame:
    ...


def build_chanlun_structure_payload(*, symbol: str, period: str, end_date: str | None, df: pd.DataFrame, fc_res: dict[str, Any], source: str) -> dict[str, Any]:
    ...
```

- 服务模块至少提供：
  - `build_dataframe_from_cache_payload()`
  - `extract_last_segment_from_signal()`
  - `count_contained_segments()`
  - `select_pivots_in_range()`
  - `build_chanlun_structure_payload()`
  - `get_chanlun_structure()`，统一串联取数、`fullcalc` 和结构提取
- 端点字段必须与设计稿保持一致：
  - `higher_segment`
  - `segment`
  - `bi`
  - `price_change_pct`
  - `contained_duan_count`
  - `contained_bi_count`
  - `pivot_count`

**Step 4: 运行测试，确认通过**

Run: `py -m pytest freshquant/tests/test_chanlun_structure_service.py -q`

Expected:
- PASS

**Step 5: Commit**

```bash
git add freshquant/chanlun_structure_service.py freshquant/tests/test_chanlun_structure_service.py
git commit -m "feat: 提取 fullcalc 缠论结构表格服务"
```

### Task 4: 用路由测试锁定专用接口

**Files:**
- Modify: `freshquant/rear/stock/routes.py`
- Create: `freshquant/tests/test_stock_data_chanlun_structure_route.py`

**Step 1: 写失败测试**

```python
def test_stock_data_chanlun_structure_route_calls_service(monkeypatch):
    called = {}

    def fake_service(symbol, period, end_date):
        called["args"] = (symbol, period, end_date)
        return {"ok": True, "symbol": symbol, "period": period}

    monkeypatch.setattr(stock_routes, "get_chanlun_structure", fake_service)
    stock_routes.request.args = {"symbol": "sz000001", "period": "5m"}

    response = stock_routes.stock_data_chanlun_structure()

    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert called["args"] == ("sz000001", "5m", None)
```

**Step 2: 运行测试，确认失败**

Run: `py -m pytest freshquant/tests/test_stock_data_chanlun_structure_route.py -q`

Expected:
- FAIL，提示 `stock_data_chanlun_structure` 路由未定义

**Step 3: 写最小实现**

```python
from freshquant.chanlun_structure_service import get_chanlun_structure


@stock_bp.route("/stock_data_chanlun_structure")
def stock_data_chanlun_structure():
    symbol = request.args.get("symbol")
    period = request.args.get("period")
    end_date = request.args.get("endDate")
    result = get_chanlun_structure(symbol, period, end_date)
    return Response(json.dumps(result, cls=FqJsonEncoder), mimetype="application/json")
```

- 路由不复用 `/api/stock_data`
- 参数语义保持最小集：`symbol`、`period`、`endDate`

**Step 4: 运行测试，确认通过**

Run: `py -m pytest freshquant/tests/test_stock_data_chanlun_structure_route.py -q`

Expected:
- PASS

**Step 5: Commit**

```bash
git add freshquant/rear/stock/routes.py freshquant/tests/test_stock_data_chanlun_structure_route.py
git commit -m "feat: 新增缠论结构专用接口"
```

### Task 5: 先补前端 API 与模板可见性测试

**Files:**
- Modify: `morningglory/fqwebui/src/api/futureApi.js`
- Modify: `morningglory/fqwebui/src/views/KlineSlim.vue`
- Create: `morningglory/fqwebui/tests/kline-slim-chanlun-structure.test.mjs`

**Step 1: 写失败测试**

```javascript
import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'

test('futureApi exposes stockChanlunStructure request helper', async () => {
  const content = await readFile(new URL('../src/api/futureApi.js', import.meta.url), 'utf8')
  assert.match(content, /stockChanlunStructure/)
  assert.match(content, /\\/api\\/stock_data_chanlun_structure/)
})

test('KlineSlim renders chanlun structure controls and sections', async () => {
  const content = await readFile(new URL('../src/views/KlineSlim.vue', import.meta.url), 'utf8')
  assert.match(content, /缠论结构/)
  assert.match(content, /高级段/)
  assert.match(content, /刷新/)
  assert.match(content, /关闭/)
})
```

**Step 2: 运行测试，确认失败**

Run: `node --test tests/kline-slim-chanlun-structure.test.mjs`

Expected:
- FAIL，提示 `stockChanlunStructure` 或相关模板文案不存在

**Step 3: 写最小实现**

```javascript
stockChanlunStructure(data) {
  let url = `/api/stock_data_chanlun_structure?period=${data.period}&symbol=${data.symbol}`
  if (data.endDate) {
    url += `&endDate=${data.endDate}`
  }
  return axios({ url, method: 'get' })
}
```

- 在 `KlineSlim.vue` 先补齐：
  - 工具栏按钮 `缠论结构`
  - 面板标题 `缠论结构`
  - 区块标题 `高级段 / 段 / 笔`
  - 面板头部按钮 `刷新 / 关闭`

**Step 4: 运行测试，确认通过**

Run: `node --test tests/kline-slim-chanlun-structure.test.mjs`

Expected:
- PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/api/futureApi.js morningglory/fqwebui/src/views/KlineSlim.vue morningglory/fqwebui/tests/kline-slim-chanlun-structure.test.mjs
git commit -m "test: 锁定 KlineSlim 缠论结构面板骨架"
```

### Task 6: 完成 KlineSlim 面板状态、加载和错误处理

**Files:**
- Modify: `morningglory/fqwebui/src/views/js/kline-slim.js`
- Modify: `morningglory/fqwebui/src/views/KlineSlim.vue`
- Modify: `morningglory/fqwebui/tests/kline-slim-chanlun-structure.test.mjs`

**Step 1: 写失败测试，锁定状态字段和错误态文案**

```javascript
test('KlineSlim script tracks chanlun structure panel state', async () => {
  const content = await readFile(new URL('../src/views/js/kline-slim.js', import.meta.url), 'utf8')
  assert.match(content, /showChanlunStructurePanel/)
  assert.match(content, /chanlunStructureLoading/)
  assert.match(content, /loadChanlunStructure/)
})

test('KlineSlim template keeps retry and empty state copy', async () => {
  const content = await readFile(new URL('../src/views/KlineSlim.vue', import.meta.url), 'utf8')
  assert.match(content, /重试/)
  assert.match(content, /暂无已完成高级段/)
})
```

**Step 2: 运行测试，确认失败**

Run: `node --test tests/kline-slim-chanlun-structure.test.mjs`

Expected:
- FAIL，提示新状态字段或文案不存在

**Step 3: 写最小实现**

```javascript
data() {
  return {
    ...,
    showChanlunStructurePanel: false,
    chanlunStructureLoading: false,
    chanlunStructureError: '',
    chanlunStructureData: null,
    chanlunStructureLastSuccess: null
  }
}
```

```javascript
async loadChanlunStructure({ force = false } = {}) {
  ...
}
```

- 行为要求：
  - 点击工具栏 `缠论结构` 按钮时打开面板并首次加载
  - 面板已打开时不自动刷新
  - 头部 `刷新` 按钮手动重载
  - 头部 `关闭` 按钮关闭面板
  - 首次失败显示错误态和 `重试`
  - 已有成功结果后刷新失败，保留旧数据并显示错误提示

**Step 4: 运行测试，确认通过**

Run: `node --test tests/kline-slim-chanlun-structure.test.mjs`

Expected:
- PASS

**Step 5: Commit**

```bash
git add morningglory/fqwebui/src/views/js/kline-slim.js morningglory/fqwebui/src/views/KlineSlim.vue morningglory/fqwebui/tests/kline-slim-chanlun-structure.test.mjs
git commit -m "feat: 接入 KlineSlim 缠论结构面板"
```

### Task 7: 做聚合验证并同步 RFC / 进度说明

**Files:**
- Modify: `docs/rfcs/0018-kline-slim-chanlun-structure-panel.md`
- Modify: `docs/migration/progress.md`

**Step 1: 跑后端测试**

Run: `py -m pytest freshquant/tests/test_chanlun_structure_service.py freshquant/tests/test_stock_data_chanlun_structure_route.py -q`

Expected:
- PASS

**Step 2: 跑前端测试**

Run: `node --test tests/kline-slim-chanlun-structure.test.mjs`

Workdir: `morningglory/fqwebui`

Expected:
- PASS

**Step 3: 更新 RFC 与进度备注**

```md
Status: Review
```

```md
| 0018 | KlineSlim 缠论结构面板 | Review | Codex | 2026-03-07 | ... | 已完成后端 fullcalc 结构接口与 KlineSlim 面板实现，待 review / 合并 |
```

如果功能在后续合并到 `main`，再单独把状态切到 `Done` 并补最终完成说明。

**Step 4: Commit**

```bash
git add docs/rfcs/0018-kline-slim-chanlun-structure-panel.md docs/migration/progress.md
git commit -m "docs: 更新 RFC 0018 实现进度"
```

### Task 8: 合并前总体验证

**Files:**
- No file changes

**Step 1: 查看工作区状态**

Run: `git status --short`

Expected:
- 空输出

**Step 2: 查看最近提交**

Run: `git log --oneline -5`

Expected:
- 包含本计划里的文档、后端、前端提交

**Step 3: 准备 PR 说明**

```md
1. 新增 `/api/stock_data_chanlun_structure`，统一基于 fullcalc 输出高级段/段/笔结构表格
2. KlineSlim 新增手动打开的“缠论结构”半透明面板
3. RFC 0018 与 progress 已同步更新
```
