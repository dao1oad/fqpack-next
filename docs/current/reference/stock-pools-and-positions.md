# 股票池与持仓参考

## 当前集合

- `stock_pre_pools`
  - 预选池 / 工作区
- `stock_pools`
  - 股票池 / 候选交易池
- `must_pool`
  - 策略必选池
- `xt_positions`
  - 外部账户当前持仓

## 当前语义

### `stock_pre_pools`

- 用于暂存筛选结果
- Shouban30 会把单个板块结果 append 进这个集合
- 允许有 `category` 和 `expire_at`
- Shouban30 当前使用 `extra.shouban30_order` 作为页面与 `.blk` 输出顺序真值

### `stock_pools`

- 表示进入进一步跟踪或候选交易的池子
- `load_monitor_codes(mode=clx_15_30)` 会读取非过期 `stock_pools`

### `must_pool`

- 是 Guardian 新开仓范围的重要来源
- 也是 XTData `guardian_1m` 订阅池的一部分
- 记录止损价、首笔金额、常规 lot 金额、是否 forever

### `xt_positions`

- 来自外部账户回报
- 反映当前账户持仓事实
- 既影响 Guardian 持仓内信号，也影响 TPSL 可卖数量

## 当前读取口径

- Guardian event 订阅池
  - `xt_positions + must_pool`
- Guardian 新开仓关注范围
  - `must_pool`
- Guardian 持仓内操作范围
  - `xt_positions`
- CLX 多周期实时模型订阅池
  - 非过期 `stock_pools`
- Shouban30 工作区
  - `stock_pre_pools -> stock_pools`
- `/stock-control` 的 `must_pools买入信号`
  - `stock_signals`
  - 条件是 `position=BUY_LONG`、`is_holding=False`，且 code 当前仍在 `must_pool`
- `/stock-control` 的 `stock_pools模型信号`
  - `realtime_screen_multi_period`
  - 展示 `datetime`、`created_at`、`code`、`name`、`period`、`model`、`close`、`stop_loss_price`、`source`

## 当前高频操作

- 代码加入 `stock_pools`
  - `/api/add_to_stock_pools_by_code`
- 代码加入 `must_pool`
  - `/api/add_to_must_pool_by_code`
- 读取 Guardian 信号列表
  - `/api/get_stock_signal_list`
- 读取 stock_pools 模型信号列表
  - `/api/get_stock_model_signal_list`
- Shouban30 预选池转股票池
  - `/api/gantt/shouban30/pre-pool/add-to-stock-pools`
- Shouban30 预选池批量转股票池
  - `/api/gantt/shouban30/pre-pool/sync-to-stock-pool`
- Shouban30 同步到通达信
  - `/api/gantt/shouban30/pre-pool/sync-to-tdx`
  - `/api/gantt/shouban30/stock-pool/sync-to-tdx`

## 当前排查

### 股票在页面工作区里，但策略不看

- 检查是否只在 `stock_pre_pools`
- 检查是否真正进入 `stock_pools`
- 如果策略链路需要 Guardian 新开仓，再继续检查是否进入 `must_pool`

### 股票已在 must_pool，但 XTData 还没订阅

- 检查 producer 订阅池是否刷新
- 检查 `monitor.xtdata.mode=guardian_1m`

### `stock_pools模型信号` 列表为空

- 检查 `realtime_screen_multi_period` 是否有数据
- 检查 XTData consumer 是否在跑
- 检查 `monitor.xtdata.mode` 是否切到了 `clx_15_30`

### 持仓有票，但 Guardian 卖点不触发

- 检查 `xt_positions` 是否有目标 code
- 检查 symbol/code6 是否规格一致
