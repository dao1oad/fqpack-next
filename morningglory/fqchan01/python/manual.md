# 函数说明

dist目录中是编译好的针对不同python版本的wheel文件，比如python3.9的话，运行python install fqchan01-0.2.3-cp39-cp39-win_amd64.whl进行安装。

其它python版本雷同。

demo.py是一个示例程序。

## 数据结构说明

```python
# Bar表示原始的K柱
Class Bar:
    pos: int # Bar所在的索引号
    high: float # Bar的最高价
    low: float # Bar的最低价

# StdBar表示合并后的K柱
Class StdBar:
    pos: int # StdBar所在的索引号
    start: int # 合并K柱在原始K柱中的开始索引号
    end: int # 合并K柱在原始K柱的结束索引号
    high_vertex: int # 最高点在的原始K柱索引号
    low_vertex: int # 最低点在的原始K柱索引号
    high: float # 合并后的high
    low: float # 合并后的low
    high_high: float # 原始K柱的最高价
    low_low: floatv # 原始K柱的最低价
    direction: float # K柱方向
    factor: float # -1=底分型的底，1=顶分型顶，0=不是分型
    factor_high: float # 分型区间高
    factor_low: float # 分型区间低
    factor_strong: float # 是否强分型

# Pivot表示中枢
Class Pivot
    start: int # 中枢在原始K柱中的开始索引
    end: int # 中枢在原始K柱中的结束索引
    zg: float # 中枢高点价格
    zd: float # 中枢低点价格
    gg: float # 中枢最高点价格
    dd: float # 中枢最低点价格
    direction: float # 中枢方向
    confirmed: bool # 是否确认中枢

# ChanOptions参数选项
Class ChanOptions
    bi_mode: int # 笔模式: 4=最少满足4个K的笔，5=最少满足5个K的笔，6=大笔
    force_wave_stick_count: int # N等于14的时候，不强制成笔，N大于等于15的时候，N根K后必须要强制成笔，笔端点在最高最低点
    allow_pivot_across: int # 最后中枢是否允许跨中枢画
    merge_non_complehensive_wave: int # 是否合并未完备的笔
```

## fq_recognise_bars

入参是列表的元素个数，最高价的列表，最低价的列表
出参是列表，每个元素是Bar

```python
fq_recognise_bars(length: int, high: List[float], low: List[float]) -> List[Bar]
```

## fq_recognise_std_bars

入参是列表的元素个数，最高价的列表，最低价的列表
出参是列表，每个元素是StdBar

```python
fq_recognise_std_bars(length: int, high: List[float], low: List[float]) -> List[StdBar]
```

## fq_recognise_swing

入参是列表的元素个数，最高价的列表，最低价的列表
出参是SW信号列表，每个元素是-1,0,1三种，表示是否是swing的低或者高

```python
fq_recognise_swing(length: int, high: List[float], low: List[float]) -> List[float]
```

## fq_recognise_bi

入参是列表的元素个数，最高价的列表，最低价的列表，和笔的参数选项
出参是笔信号列表，每个元素是-1,0,1三种，表示是否是bi的低或高

```python
fq_recognise_bi(length: int, high: List[float], low: List[float], chan_options ChanOptions) -> List[float]
```

## fq_recognise_duan

入参是列表的元素个数，笔信号的列表，最高价的列表，最低价的列表
出参是段信号列表，每个元素是-1,0,1三种，表示是否是段的低或者高

```python
fq_recognise_duan(length: int, bi: List[float], high: List[float], low: List[float]) -> List[float]
```

## fq_recognise_pivots

入参是列表的元素个数，笔信号列表，段参数列表，最高价的列表，最低价的列表
出参是中枢列表，每个元素是Pivot

```python
fq_recognise_pivots(length: int, duan: List[float], bi: List[float], high: List[float], low: List[float]) -> List[Pivot]
```
