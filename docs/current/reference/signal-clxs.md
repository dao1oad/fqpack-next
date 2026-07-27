# CLXS 信号函数参考

## 当前定位

CLXS 是当前仓库仍在使用的一组缠论信号函数与筛选策略，主要依赖外部扩展：

- `fqcopilot.fq_clxs`
- `fqchan04.fq_recognise_bi`

它们既用于盘后选股，也用于 Guardian 事件驱动链路中的部分信号识别。

独立的 CLX 大规模回测使用 `S0000`～`S0017` 全模型 native batch、逐日因果前缀和冻结 HOLDOUT 合同，不沿用本页盘后扫描的单模型参数口径。详见 [CLX 大规模回测](../modules/clx-backtest.md)。

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

## 通达信 CLX18 插件接口

32 位通达信插件由 `morningglory/fqcopilot` 的 `tdx` target 构建。
现有函数槽位 `1～4` 保持兼容，其中 CLX18 专家回测继续使用：

```text
TDXDLL7(3,HIGH,LOW,CLOSE)
```

它返回选定模型唯一的主触发编码，交易规则不读取并发掩码。

CLX18 三层主图使用：

```text
TDXDLL7(5,HIGH,LOW,CLOSE)
```

5 号函数只计算 `PARAM_MODEL_OPT` 指定的一个模型，同时返回主信号和完整并发触发
掩码：

```text
packed = sign(signal) * (abs(signal) * 128 + trigger_mask)
```

- `trigger_mask` 的 `1/2/4/8/16/32/64` 分别表示
  `模型结构/Pin Bar/吞没/强分型/MA5拐头/量价齐升/MACD金叉`。
- 完整掩码等于方向基础掩码与主触发位按位或，因此主触发位始终存在。
- 最大 packed 值小于 `2^24`，在通达信 float32 插件协议中可精确往返。
- 主图在信号后的可执行开盘 K 线上区分“原始未增强”和“增强”，并把同 K 线
  全部触发按固定顺序纵向显示；专家回测仍只使用增强入场条件。

当前通达信运行 DLL 路径是：

```text
D:\new_tdx\T0002\dlls\fqcopilot.dll
```

部署时先关闭 `D:\new_tdx\tdxw.exe`，备份旧 DLL 和公式数据库，再替换 DLL、重新
登记 18 个主图公式并执行逐 K 线 parity 与公式编译检查。

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
