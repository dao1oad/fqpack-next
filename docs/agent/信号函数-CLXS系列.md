---
name: signal-clxs-functions
description: CLXS系列信号函数参考指南。包含 fq_clxs 缠论信号计算函数的用法，包括函数签名、参数说明、信号模型类型（选股/背驰/拉回/V反）、使用场景和止损价格计算方法。适用于需要使用缠论信号进行股票筛选或模式识别的场景。
---

# CLXS 系列信号函数

## 函数概述

`fq_clxs` 是来自 `fqcopilot` 包的缠论信号计算函数，用于识别 A 股市场中的各类交易信号。该函数通过分析价格、成交量等数据，返回多个维度的信号值。

**来源**：`fqcopilot.fq_clxs`

## 函数签名

```python
from fqcopilot import fq_clxs

signals = fq_clxs(
    length: int,           # 数据长度
    high_list: List[float],   # 最高价列表
    low_list: List[float],    # 最低价列表
    open_list: List[float],   # 开盘价列表
    close_list: List[float],  # 收盘价列表
    volume_list: List[float], # 成交量列表
    wave_opt: int = 1560,   # 波浪参数（默认 1560）
    stretch_opt: int = 0,   # 拉伸参数（默认 0）
    trend_opt: int = 0,     # 趋势参数（信号识别默认 0，选股场景使用 1）
    model_opt: int = 10001  # 信号模型选择（关键参数）
)
```

**返回值**：`List[float]` - 与输入数据等长的信号值列表

## 信号模型 (model_opt)

`model_opt` 是决定计算什么类型信号的关键参数：

| model_opt | 信号类型 | 说明 | 信号值含义 |
|-----------|----------|------|-----------|
| 8 | MACD 背驰 | 识别 MACD 与价格的背离信号 | 正值=看涨背驰，负值=看跌背驰，绝对值/100=中枢数量 |
| 9 | 拉回信号 (ZS 拉回) | 识别回调/反弹至中枢的信号 | 正值=买入拉回，负值=卖出拉回 |
| 12 | V 反转 | 识别 V 型反转信号 | 正值=买入 V 反，负值=卖出 V 反 |
| 10001+ | CLXS 选股信号 | 5 位数格式 `1xxxx` | 正值=买入信号，数值越大信号越强 |

## 使用场景

### 1. 股票筛选

当需要批量筛选符合条件的股票时使用：

```python
# freshquant/screening/clxs.py
signals = fq_clxs(
    length, highs, lows, opens, closes, volumes,
    wave_opt=1560, stretch_opt=0, trend_opt=1, model_opt=10001
)
if signals[-1] > 0:
    # 最后一天有买入信号，加入股票池
    pass
```

### 2. MACD 背驰识别

当需要识别价格与 MACD 指标的背离信号时使用：

```python
# freshquant/pattern/chanlun/macd_divergence.py
signals = fq_clxs(
    length, highs, lows, opens, closes, volumes,
    wave_opt=1560, stretch_opt=0, trend_opt=0, model_opt=8
)
signal_value = int(signals[i])
zhongshu_count = abs(signal_value) // 100  # 中枢数量
```

### 3. 中枢拉回识别

当需要识别价格回调至中枢区域的买卖机会时使用：

```python
# freshquant/pattern/chanlun/pullback.py
signals = fq_clxs(
    length, highs, lows, opens, closes, volumes,
    wave_opt=1560, stretch_opt=0, trend_opt=0, model_opt=9
)
if signal_value > 0:
    # 买入拉回信号
elif signal_value < 0:
    # 卖出拉回信号
```

### 4. V 型反转识别

当需要识别快速反转信号时使用：

```python
# freshquant/pattern/chanlun/v_reversal.py
signals = fq_clxs(
    length, highs, lows, opens, closes, volumes,
    wave_opt=1560, stretch_opt=0, trend_opt=0, model_opt=12
)
```

## 止损价格计算

配合 `fq_recognise_bi` (笔识别) 计算止损价格：

```python
from fqchan04 import fq_recognise_bi

bi_list = fq_recognise_bi(length, high_list, low_list)

# 买入信号的止损：往前找最近的笔底 (bi[x] == -1)
if signal_value > 0:
    stop_loss_price = None
    for j in range(i, -1, -1):
        if bi_list[j] == -1:
            stop_loss_price = low_list[j]
            break

# 卖出信号的止损：往前找最近的笔顶 (bi[x] == 1)
if signal_value < 0:
    stop_loss_price = None
    for j in range(i, -1, -1):
        if bi_list[j] == 1:
            stop_loss_price = high_list[j]
            break
```

## 成交量数据处理

对于信号识别（非选股），成交量数据可以传入默认值，因为信号计算不依赖成交量：

```python
volume_list = [1.0] * length  # 默认值，不影响信号计算
```

## 参数默认值建议

| 参数 | 选股场景 | 信号识别场景 |
|------|----------|-------------|
| wave_opt | 1560 | 1560 |
| stretch_opt | 0 | 0 |
| trend_opt | 1 | 0 |

## 相关代码文件

- `freshquant/screening/clxs.py` - CLXS 选股主程序
- `freshquant/pattern/chanlun/pullback.py` - 拉回信号识别
- `freshquant/pattern/chanlun/v_reversal.py` - V 反转识别
- `freshquant/pattern/chanlun/macd_divergence.py` - MACD 背驰识别

## 注意事项

1. **数据长度要求**：需要足够的历史数据才能准确计算信号
2. **信号过滤**：建议对信号进行额外过滤（如 ST 股过滤、流动性过滤）
3. **止损计算**：始终配合 `fq_recognise_bi` 计算止损价格
4. **异步调用**：在批量处理时使用 asyncio 提高效率
