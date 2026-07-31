# CLXS 信号函数参考

## 当前定位

CLXS 是当前仓库仍在使用的一组缠论信号函数与筛选策略，主要依赖外部扩展：

- `fqcopilot.fq_clxs`
- `fqchan04.fq_recognise_bi`

它们既用于盘后选股，也用于 Guardian 事件驱动链路中的部分信号识别。

## 当前主要落点

- 盘后选股策略
  - `freshquant.screening.strategies.clxs.ClxsStrategy`
- 事件驱动辅助
  - `freshquant.signal.astock.job.monitor_helpers_event`
- 单一模式函数
  - `freshquant.pattern.chanlun.macd_divergence`
  - `freshquant.pattern.chanlun.pullback`
  - `freshquant.pattern.chanlun.v_reversal`

## 当前常见模型参数

- `model_opt=8`
  - MACD 背驰
- `model_opt=9`
  - 中枢回拉
- `model_opt=12`
  - V 反
- `model_opt=10001`
  - CLXS 选股默认模型

### 原生 CLX 模型范围

当前 `morningglory/fqcopilot` 原生扩展已注册 **S0000–S0017 共 18 个模型**。

- 单模型 Python 入口：`fqcopilot.fq_clxs`
  - 生产编码为 `10000..10017`
  - 编码规则：`model_opt = switch_opt * 10000 + model_id`
- 批量 Python 入口：`fqcopilot.fq_clxs_all`
  - 返回 18 行，行号 `0..17` 对应 `S0000..S0017`
  - 与通达信 Func4 / `SALL` 采用 `switch_opt=0` 的批量口径

因此，批量入口与单模型入口做逐项对照时，应比较批量第 `m` 行和
`fq_clxs(..., model_opt=m)`；生产单模型调用则使用 `10000 + m`。

`trend_opt` 同时作为模型扩展参数传入。S0015 的默认 MA 周期由 `trend_opt=0`
触发；传入 `trend_opt=1` 会把扩展参数解释为 MA 周期 1，可能得到空信号，
这属于参数语义而不是模型执行失败。

常见默认参数：

- `wave_opt=1560`
- `stretch_opt=0`
- `trend_opt=1` 或 `0`

## 当前入口

CLI 选股入口：

```powershell
python -m freshquant.cli stock screening --model clxs
```

常用参数：

- `--wave-opt`
- `--stretch-opt`
- `--trend-opt`
- `--model-opt`

## 当前输出语义

- 盘后选股结果可写入 `stock_pre_pools`
- 事件驱动链路把 CLXS 结果转换成：
  - `BUY_LONG`
  - `SELL_SHORT`
- 单一函数通常同时给出：
  - 触发价
  - 止损价
  - 标签或中枢数量

## 当前排查

### CLXS 结果总是空

- 检查 `fqcopilot` / `fqchan04` 是否安装
- 检查历史数据是否完整

### 同一股票重复命中

- 检查去重逻辑是否按 `code + date`
- 检查盘后扫描天数是否过大

### Guardian 与盘后选股结果不一致

- 检查事件驱动链路用的是最新 bar 还是盘后全量数据
- 检查 `trend_opt` / `model_opt` 是否一致
