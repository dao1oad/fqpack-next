# fqchan04 缠论分析库使用手册

## 安装说明

dist目录中是编译好的针对不同python版本的wheel文件，比如python3.9的话，运行：

```bash
pip install fqchan04-0.2.3-cp39-cp39-win_amd64.whl
```

其它python版本雷同。

## 数据结构说明

```python
# Bar表示原始的K柱
class Bar:
    pos: int # Bar所在的索引号
    high: float # Bar的最高价
    low: float # Bar的最低价

# StdBar表示合并后的K柱
class StdBar:
    pos: int # StdBar所在的索引号
    start: int # 合并K柱在原始K柱中的开始索引号
    end: int # 合并K柱在原始K柱的结束索引号
    high_vertex_raw_pos: int # 最高点在的原始K柱索引号
    low_vertex_raw_pos: int # 最低点在的原始K柱索引号
    high: float # 合并后的high
    low: float # 合并后的low
    high_high: float # 原始K柱的最高价
    low_low: float # 原始K柱的最低价
    direction: float # K柱方向
    factor: float # -1=底分型的底，1=顶分型顶，0=不是分型
    factor_high: float # 分型区间高
    factor_low: float # 分型区间低
    factor_strong: float # 是否强分型

# Pivot表示中枢
class Pivot:
    start: int # 中枢在原始K柱中的开始索引
    end: int # 中枢在原始K柱中的结束索引
    zg: float # 中枢高点价格
    zd: float # 中枢低点价格
    gg: float # 中枢最高点价格
    dd: float # 中枢最低点价格
    direction: float # 中枢方向
    is_comprehensive: bool # 是否为完备中枢

# ChanOptions参数选项
class ChanOptions:
    bi_mode: int # 笔模式: 4=最少满足4个K的笔，5=最少满足5个K的笔，6=大笔
    force_wave_stick_count: int # N等于14的时候，不强制成笔，N大于等于15的时候，N根K后必须要强制成笔，笔端点在最高最低点
    allow_pivot_across: int # 最后中枢是否允许跨中枢画
    merge_non_complehensive_wave: int # 是否合并未完备的笔
```

## 函数接口说明

### fq_recognise_bars

识别原始K柱

**参数：**

- `length: int` - K线数据长度
- `high: List[float]` - 最高价列表
- `low: List[float]` - 最低价列表

**返回值：**

- `List[Bar]` - Bar对象列表

```python
fq_recognise_bars(length: int, high: List[float], low: List[float]) -> List[Bar]
```

### fq_recognise_std_bars

识别标准化K柱（合并后的K柱）

**参数：**

- `length: int` - K线数据长度
- `high: List[float]` - 最高价列表
- `low: List[float]` - 最低价列表

**返回值：**

- `List[StdBar]` - StdBar对象列表

```python
fq_recognise_std_bars(length: int, high: List[float], low: List[float]) -> List[StdBar]
```

### fq_recognise_swing

识别分型信号

**参数：**

- `length: int` - K线数据长度
- `high: List[float]` - 最高价列表
- `low: List[float]` - 最低价列表

**返回值：**

- `List[float]` - 分型信号列表，-1表示底分型，1表示顶分型，0表示无分型

```python
fq_recognise_swing(length: int, high: List[float], low: List[float]) -> List[float]
```

### fq_recognise_bi

识别笔信号

**参数：**

- `length: int` - K线数据长度
- `high: List[float]` - 最高价列表
- `low: List[float]` - 最低价列表
- `chan_options: ChanOptions` - 缠论参数选项（可选，有默认值）

**返回值：**

- `List[float]` - 笔信号列表，-1表示笔的低点，1表示笔的高点，0表示非笔端点

```python
fq_recognise_bi(length: int, high: List[float], low: List[float], 
                chan_options: ChanOptions = ChanOptions(bi_mode=6, force_wave_stick_count=15, 
                                                       allow_pivot_across=0, merge_non_complehensive_wave=0)) -> List[float]
```

### fq_recognise_duan

识别段信号

**参数：**

- `length: int` - K线数据长度
- `bi: List[float]` - 笔信号列表
- `high: List[float]` - 最高价列表
- `low: List[float]` - 最低价列表

**返回值：**

- `List[float]` - 段信号列表，-1表示段的低点，1表示段的高点，0表示非段端点

```python
fq_recognise_duan(length: int, bi: List[float], high: List[float], low: List[float]) -> List[float]
```

### fq_recognise_pivots

识别中枢

**参数：**

- `length: int` - K线数据长度
- `higher_level_sigs: List[float]` - 高级别信号列表（通常是段信号）
- `sigs: List[float]` - 当前级别信号列表（通常是笔信号）
- `high: List[float]` - 最高价列表
- `low: List[float]` - 最低价列表
- `chan_options: ChanOptions` - 缠论参数选项（可选，有默认值）

**返回值：**

- `List[Pivot]` - 中枢对象列表

```python
fq_recognise_pivots(length: int, higher_level_sigs: List[float], sigs: List[float], 
                   high: List[float], low: List[float],
                   chan_options: ChanOptions = ChanOptions(bi_mode=6, force_wave_stick_count=15, 
                                                          allow_pivot_across=0, merge_non_complehensive_wave=0)) -> List[Pivot]
```

### fq_count_vertexes

计算指定区间内的顶点数量

**参数：**

- `vertexes: List[float]` - 顶点信号列表
- `i: int` - 起始索引
- `j: int` - 结束索引

**返回值：**

- `int` - 顶点数量

```python
fq_count_vertexes(vertexes: List[float], i: int, j: int) -> int
```

### fq_locate_pivots

定位中枢位置，这个用来识别i和j之间是否有重叠区间（中枢）。i和j要是vertexes中的顶点，并且是高点到低点或者低点到高点。

**参数：**

- `vertexes: List[float]` - 顶点信号列表，笔顶点或者段顶点
- `high: List[float]` - 最高价列表
- `low: List[float]` - 最低价列表
- `direction: int` - 方向
- `i: int` - 起始索引
- `j: int` - 结束索引

**返回值：**

- `List[Pivot]` - 中枢对象列表

```python
fq_locate_pivots(vertexes: List[float], high: List[float], low: List[float], 
                direction: int, i: int, j: int) -> List[Pivot]
```

### fq_recognise_trend

识别趋势

**参数：**

- `length: int` - K线数据长度
- `duan: List[float]` - 段信号列表
- `high: List[float]` - 最高价列表
- `low: List[float]` - 最低价列表

**返回值：**

- `List[float]` - 趋势信号列表

```python
fq_recognise_trend(length: int, duan: List[float], high: List[float], low: List[float]) -> List[float]
```

## 使用示例

```python
import fqchan04

# 准备数据
length = len(high_prices)
high_list = high_prices  # 最高价列表
low_list = low_prices    # 最低价列表

# 识别分型
swing_signals = fqchan04.fq_recognise_swing(length, high_list, low_list)

# 识别笔
bi_signals = fqchan04.fq_recognise_bi(length, high_list, low_list)

# 识别段
duan_signals = fqchan04.fq_recognise_duan(length, bi_signals, high_list, low_list)

# 识别中枢
pivots = fqchan04.fq_recognise_pivots(length, duan_signals, bi_signals, high_list, low_list)

# 自定义参数
options = fqchan04.ChanOptions(bi_mode=5, force_wave_stick_count=14, 
                              allow_pivot_across=1, merge_non_complehensive_wave=1)
bi_signals_custom = fqchan04.fq_recognise_bi(length, high_list, low_list, options)
```
