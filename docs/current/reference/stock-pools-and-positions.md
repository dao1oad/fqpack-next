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
- Shouban30 会把当前筛选集批量替换进这个集合
- 允许有 `category` 和 `expire_at`

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

- 监控池总集
  - `get_stock_monitor_codes()`
  - 来源是 `holding + must_pool + stock_pools`
- Guardian 新开仓关注范围
  - `must_pool`
- Guardian 持仓内操作范围
  - `xt_positions`
- Shouban30 工作区
  - `stock_pre_pools -> stock_pools -> must_pool`

## 当前高频操作

- 代码加入 `stock_pools`
  - `/api/add_to_stock_pools_by_code`
- 代码加入 `must_pool`
  - `/api/add_to_must_pool_by_code`
- Shouban30 预选池转股票池
  - `/api/gantt/shouban30/pre-pool/add-to-stock-pools`
- Shouban30 股票池转 must_pool
  - `/api/gantt/shouban30/stock-pool/add-to-must-pool`

## 当前排查

### 股票在页面工作区里，但策略不看

- 检查是否只在 `stock_pre_pools`
- 检查是否真正进入 `must_pool` 或 `stock_pools`

### 股票已在 must_pool，但 XTData 还没订阅

- 检查 producer 订阅池是否刷新
- 检查 `monitor.xtdata.mode`

### 持仓有票，但 Guardian 卖点不触发

- 检查 `xt_positions` 是否有目标 code
- 检查 symbol/code6 是否规格一致
