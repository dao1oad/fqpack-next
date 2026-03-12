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
