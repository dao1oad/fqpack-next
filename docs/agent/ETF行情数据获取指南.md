---
name: etf-market-data-fetching
description: ETF行情数据获取参考指南。包含ETF日线/分钟线数据获取方法，以及与A股数据获取的区别说明。适用于需要获取ETF历史行情数据进行技术分析、信号计算的场景。
---

# ETF 行情数据获取指南

## 概述

ETF 在 FreshQuant 中被当作指数处理，使用 `QA_fetch_index_*` 系列函数获取数据，与 A 股使用 `QA_fetch_stock_*` 系列不同。

## 核心函数

### 1. 获取 ETF 日线数据

**函数**：`queryEtfCandleSticksDay`

**来源**：`freshquant.quote.etf`

```python
from freshquant.quote.etf import queryEtfCandleSticksDay
from datetime import datetime

data = queryEtfCandleSticksDay(
    code="sh510050",          # ETF 代码（需带市场前缀）
    start=datetime(2023, 1, 1),  # 起始日期（可选）
    end=datetime.now()        # 结束日期（可选）
)
# 返回：DataFrame 或 None，索引为 datetime
```

### 2. 获取 ETF 分钟线数据

**函数**：`queryEtfCandleSticksMin`

**来源**：`freshquant.quote.etf`

```python
from freshquant.quote.etf import queryEtfCandleSticksMin

data = queryEtfCandleSticksMin(
    code="510050",            # ETF 代码（纯代码）
    frequence="30min",        # 频率：1min, 5min, 15min, 30min, 60min
    start=datetime.now() - timedelta(days=7),
    end=datetime.now()
)
```

### 3. 通用查询函数（推荐）

**函数**：`queryEtfCandleSticks`

**来源**：`freshquant.quote.etf`

```python
from freshquant.quote.etf import queryEtfCandleSticks

# 自动根据 period 选择对应的数据源
data = queryEtfCandleSticks(
    code="sh510050",
    period="1d",              # 1m, 3m, 5m, 15m, 30m, 60m, 120m, 1d, 1w
    endDate="2024-01-15"      # 结束日期（可选）
)
```

**支持频率**：

| period | 说明 | 底层调用 |
|--------|------|----------|
| `1d` | 日线 | `queryEtfCandleSticksDay` |
| `1w` | 周线 | 日线 + `QA_data_day_resample` |
| `1m`, `5m`, `15m`, `30m`, `60m` | 分钟线 | `queryEtfCandleSticksMin` |
| `3m` | 3分钟 | 1分钟 + 重采样 |
| `120m` | 120分钟 | 60分钟 + 重采样 |

## 返回数据结构

与 A 股相同，返回 DataFrame 包含以下字段：

| 列名 | 说明 |
|------|------|
| datetime | 日期时间（索引） |
| open | 开盘价 |
| high | 最高价 |
| low | 最低价 |
| close | 收盘价 |
| volume | 成交量 |
| amount | 成交额 |
| time_stamp | 时间戳 |

**价格精度差异**：
- A 股：2 位小数
- ETF：3 位小数

## ETF vs A 股数据获取对比

| 特性 | A 股 | ETF |
|------|------|-----|
| 日线函数 | `fq_data_stock_fetch_day` | `queryEtfCandleSticksDay` |
| 分钟线函数 | `fq_data_stock_fetch_min` | `queryEtfCandleSticksMin` |
| QUANTAXIS 函数 | `QA_fetch_stock_day_adv` | `QA_fetch_index_day_adv` |
| 实时数据集合 | `stock_realtime` | `index_realtime` |
| 价格精度 | 2 位小数 | 3 位小数 |
| 代码格式 | `000001` / `sz000001` | `sh510050` / `510050` |

## ETF 代码格式

| 格式 | 说明 | 示例 |
|------|------|------|
| `sh510050` | 市场前缀 + 代码（推荐） | 沪市 ETF |
| `sz159915` | 市场前缀 + 代码（推荐） | 深市 ETF |
| `510050` | 纯代码（6位） | 50ETF |
| `159915` | 纯代码（6位） | 创业板ETF |

**市场前缀**：
- `sh` - 上海证券交易所
- `sz` - 深圳证券交易所

## 完整示例

### 获取 ETF 日线数据

```python
from datetime import datetime, timedelta
from freshquant.quote.etf import queryEtfCandleSticksDay

async def fetch_etf_day_data(code: str = "sh510050") -> pd.DataFrame:
    """获取指定 ETF 的日线数据"""
    try:
        start = datetime.now() - timedelta(days=500)
        end = datetime.now()

        data = queryEtfCandleSticksDay(code=code, start=start, end=end)

        if data is not None and len(data) > 0:
            return data
        return None
    except Exception as e:
        print(f"Error fetching ETF data: {e}")
        return None
```

### 获取 ETF 30分钟数据

```python
from datetime import datetime, timedelta
from freshquant.quote.etf import queryEtfCandleSticksMin

async def fetch_etf_min30_data(code: str = "510050") -> pd.DataFrame:
    """获取指定 ETF 的30分钟数据"""
    try:
        start = datetime.now() - timedelta(days=60)
        end = datetime.now()

        data = queryEtfCandleSticksMin(
            code=code,
            frequence="30min",
            start=start,
            end=end
        )

        if data is not None and len(data) > 0:
            return data
        return None
    except Exception as e:
        print(f"Error fetching ETF min data: {e}")
        return None
```

### 使用通用函数

```python
from freshquant.quote.etf import queryEtfCandleSticks

# 获取日线
day_data = queryEtfCandleSticks("sh510050", "1d")

# 获取30分钟线
min30_data = queryEtfCandleSticks("sh510050", "30m")

# 获取3分钟线（重采样）
min3_data = queryEtfCandleSticks("sh510050", "3m")
```

## 判断标的类型

在处理混合持仓（A 股 + ETF）时，需要先判断标的类型：

```python
from freshquant.instrument.general import query_instrument_type
from freshquant.carnation.enum_instrument import InstrumentType

code = "510050"
inst_type = query_instrument_type(code)

if inst_type == InstrumentType.STOCK_CN:
    # A 股：使用 fq_data_stock_fetch_day/min
    data = fq_data_stock_fetch_day(code)
elif inst_type == InstrumentType.ETF_CN:
    # ETF：使用 queryEtfCandleSticksDay/min
    data = queryEtfCandleSticksDay(code)
```

## 数据源与缓存

### 数据流向

```
通达信 (TDX) → MongoDB (index_day/index_min) → Redis 缓存 → 内存缓存
                                      ↓
                              MongoDB (index_realtime) ← 实时数据补充
```

### 缓存策略

| 函数 | 缓存类型 | 过期时间 |
|------|----------|----------|
| `queryEtfCandleSticksDayAdv` | Redis | 900s (15min) |
| `queryEtfCandleSticksMinAdv` | Redis | 900s (15min) |
| `queryEtfCandleSticks` | 内存 | 3s |

## 相关代码文件

| 文件 | 说明 |
|------|------|
| `freshquant/quote/etf.py` | ETF 行情数据获取 |
| `freshquant/data/index.py` | 指数数据获取（ETF 底层实现） |
| `freshquant/instrument/etf.py` | ETF 信息查询 |
| `freshquant/command/etf.py` | ETF 数据保存命令 |

## CLI 命令

```bash
# 使用 fqctl 命令（推荐）
fqctl etf save              # 保存 ETF 数据（列表 + 日线 + 分钟线）
fqctl etf.list save         # 仅保存 ETF 列表
fqctl etf.day save          # 仅保存 ETF 日线
fqctl etf.min save          # 仅保存 ETF 分钟线

# 或使用 python -m 方式
python -m freshquant etf save
python -m freshquant etf.list save
python -m freshquant etf.day save
python -m freshquant etf.min save
```

## 注意事项

1. **代码格式**：ETF 通常需要带市场前缀（`sh510050`）
2. **数据源**：ETF 使用指数数据源，不是股票数据源
3. **价格精度**：ETF 是 3 位小数，A 股是 2 位小数
4. **实时数据**：ETF 实时数据存储在 `index_realtime` 集合
5. **类型判断**：处理混合持仓时需要先判断标的类型
