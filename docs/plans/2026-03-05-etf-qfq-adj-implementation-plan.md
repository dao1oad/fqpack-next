# ETF `etf_adj`（qfq）实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 新增 `quantaxis.etf_xdxr/etf_adj` 的同步链路，并让 `freshquant/quote/etf.py` 默认返回前复权(qfq) K 线，使 `get_data_v2()` 在股票/ETF 上行为一致（无开关）。

**Architecture:**
使用 TDX/pytdx 拉取 ETF xdxr（`category=1/11`），落库为 `etf_xdxr`；基于 `index_day`（bfq）+ `etf_xdxr` 计算 qfq 因子 `adj` 并写入 `etf_adj`；查询侧按日期 join `etf_adj` 并对 OHLC 乘因子。

**Tech Stack:** `pandas`, `pymongo`, `pytdx`, `dagster`, `pytest`, `loguru`

---

### Task 1: 写纯 pandas 单测（先失败）

**Files:**
- Create: `freshquant/tests/test_etf_adj.py`

**Step 1: 写拆分(category=11)测试（应失败）**

```python
import pandas as pd

from freshquant.data.etf_adj import compute_etf_qfq_adj, apply_qfq_to_bars


def test_compute_etf_qfq_adj_split_category11_makes_prices_continuous():
    day = pd.DataFrame(
        [
            {"date": "2025-08-01", "open": 1.12, "high": 1.15, "low": 1.11, "close": 1.138},
            {"date": "2025-08-04", "open": 0.57, "high": 0.58, "low": 0.56, "close": 0.572},
        ]
    )
    xdxr = pd.DataFrame(
        [
            {"date": "2025-08-04", "category": 11, "suogu": 2.0},
        ]
    )

    adj = compute_etf_qfq_adj(day, xdxr)
    out = apply_qfq_to_bars(day, adj, date_col="date")

    # 事件日前一日价格应被缩放约 0.5，接近事件日价格（连续）
    assert abs(out.loc[out["date"] == "2025-08-01", "close"].iloc[0] - 0.569) < 0.01
    assert abs(out.loc[out["date"] == "2025-08-04", "close"].iloc[0] - 0.572) < 1e-6
```

**Step 2: 写分红(category=1)测试（应失败）**

```python
def test_compute_etf_preclose_dividend_category1_uses_stock_formula():
    day = pd.DataFrame(
        [
            {"date": "2025-12-16", "open": 3.10, "high": 3.11, "low": 3.08, "close": 3.103},
            {"date": "2025-12-17", "open": 3.025, "high": 3.05, "low": 3.00, "close": 3.030},
        ]
    )
    xdxr = pd.DataFrame(
        [
            {"date": "2025-12-17", "category": 1, "fenhong": 0.8, "peigu": 0.0, "peigujia": 0.0, "songzhuangu": 0.0},
        ]
    )

    adj = compute_etf_qfq_adj(day, xdxr)
    out = apply_qfq_to_bars(day, adj, date_col="date")

    # 除息参考价：(prev_close*10 - fenhong) / 10 = prev_close - fenhong/10
    expected_preclose = 3.103 - 0.8 / 10
    # 事件日前一日 qfq 收盘应接近 expected_preclose（连续）
    assert abs(out.loc[out["date"] == "2025-12-16", "close"].iloc[0] - expected_preclose) < 0.02
```

**Step 3: 运行测试（确认失败）**

Run: `pytest freshquant/tests/test_etf_adj.py -q`
Expected: FAIL（`freshquant.data.etf_adj`/函数尚不存在）

---

### Task 2: 实现 `compute_etf_qfq_adj` 与 `apply_qfq_to_bars`

**Files:**
- Create: `freshquant/data/etf_adj.py`
- Modify: `freshquant/data/__init__.py`（如需导出，可选）
- Test: `freshquant/tests/test_etf_adj.py`

**Step 1: 最小实现（使单测通过）**

实现要点：
- 输入 `day_df`：至少包含 `date, open, high, low, close`
- 输入 `xdxr_df`：允许为空；识别 `category==1/11`
- 生成 `preclose`：
  - 默认 `preclose = close.shift(1)`
  - `category==1`：`preclose = (prev_close*10 - fenhong + peigu*peigujia) / (10 + peigu + songzhuangu)`
  - `category==11`：在已有 `preclose` 基础上 `preclose = preclose / suogu`（`suogu!=0`）
- qfq 因子：`adj = (preclose.shift(-1) / close).fillna(1)[::-1].cumprod()`
- `apply_qfq_to_bars`：将 `adj` 按日期 join 到 bars，并对 `open/high/low/close` 乘因子；缺失填 1

**Step 2: 运行测试（确认通过）**

Run: `pytest freshquant/tests/test_etf_adj.py -q`
Expected: PASS

---

### Task 3: 查询链路默认应用 qfq（ETF）

**Files:**
- Modify: `freshquant/quote/etf.py`

**Step 1: 增加 `etf_adj` 读取与应用（先写一个最小路径）**

实现要点：
- 统一 code：使用 `freshquant.util.code.normalize_to_base_code()` 得到 6 位代码
- 从 `DBQuantAxis.etf_adj` 读取 `[start_date, end_date]` 区间的 `adj`
- 在 `queryEtfCandleSticksDay()` / `queryEtfCandleSticksMin()` 组装 DataFrame 后、返回前应用 qfq（保证后续 resample 也在 qfq 基础上做）
- 若 adj 为空：`logger.warning(...)` 并直接返回原始 bars（等价 bfq）

**Step 2: 增加轻量单测（不连 Mongo）**

建议用 `monkeypatch` 把“查询 adj 的函数”替换成固定 DataFrame，验证 OHLC 被乘到。
（如现有测试体系较弱，可先不加；但建议至少覆盖 1 个测试用例。）

---

### Task 4: Dagster：新增 `etf_xdxr` / `etf_adj` 资产（历史补全 + 每日更新）

**Files:**
- Modify: `morningglory/fqdagster/src/fqdagster/defs/assets/market_data.py`
- Create: `freshquant/data/etf_adj_sync.py`（或将同步函数放入 `freshquant/data/etf_adj.py`）

**Step 1: 实现同步函数（先可运行，再优化性能）**

建议接口（示例）：
- `sync_etf_xdxr_all(db=DBQuantAxis) -> dict`
- `sync_etf_adj_all(db=DBQuantAxis) -> dict`

实现要点：
- `etf_xdxr`：使用 `pytdx.TdxHq_API.get_xdxr_info(market, code)` 批量循环（单连接），写入 `quantaxis.etf_xdxr`（按 code 全量覆盖或 upsert）
- `etf_adj`：对每个 code：
  - 从 `index_day` 拉取全历史（bfq）
  - 从 `etf_xdxr` 拉取事件
  - `compute_etf_qfq_adj` 得到因子序列
  - 覆盖写入 `quantaxis.etf_adj`（先 `delete_many({'code': code})` 再 `insert_many`）

**Step 2: 在 Dagster 资产中挂接**

新增资产：
- `etf_xdxr`：`deps=[etf_list]`
- `etf_adj`：`deps=[etf_day, etf_xdxr]`

并确保 `etf_data_job`（从 `etf_list` downstream）会自动包含这两个资产。

---

### Task 5: 手工验证（Docker Dagster + get_data_v2）

**Step 1: 启动并行 Docker（如未启动）**

Run: `docker compose -f docker/compose.parallel.yaml up -d --build`

**Step 2: Dagster 触发一次 ETF 全链路（历史补全首次会较久）**

在 Dagster UI（`http://localhost:11003`）手工 materialize：`etf_list`（downstream），或直接跑 `etf_data_job`。

**Step 3: 验证 Mongo 集合存在且有数据**

Run（容器内/宿主机均可，需能连 Mongo）：

```python
from freshquant.db import DBQuantAxis
print(DBQuantAxis.etf_adj.count_documents({}))
print(DBQuantAxis.etf_xdxr.count_documents({}))
```

**Step 4: 验证 `512000` 拆分点 qfq 连续**

用 `get_data_v2('sh512000','1d')` 或 `queryEtfCandleSticks('sh512000','1d')` 拉取覆盖 `2025-08-01/2025-08-04` 的数据，确认 qfq 后不出现 2x 跳变。

**Step 5: 验证股票与 ETF 的 `get_data_v2()` 均为 qfq**

- `get_data_v2('sh600000','1d')`（股票：现状已 qfq）
- `get_data_v2('sh512000','1d')`（ETF：改造后 qfq）

---

### Task 6: 记录破坏性变更

**Files:**
- Modify: `docs/migration/breaking-changes.md`

**Step 1: 登记变更（引用 RFC 0002）**

说明 “ETF 查询默认从 bfq → qfq” 的影响面、迁移建议与回滚方式。
