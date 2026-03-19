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
- `load_monitor_codes(mode=guardian_and_clx_15_30)` 会在 Guardian 池之后补充非过期 `stock_pools`
- 兼容旧值 `clx_15_30`，读取时会按联合模式执行

### `must_pool`

- 是 Guardian 新开仓范围的重要来源
- 也是 XTData `guardian_1m` 和 `guardian_and_clx_15_30` 订阅池的一部分
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
  - 联合模式下由 Guardian 池优先后，再用非过期 `stock_pools` 补足
- Shouban30 工作区
  - `stock_pre_pools -> stock_pools`
- `/stock-control` 的 `must_pools买入信号`
  - `stock_signals`
  - 条件是 `position=BUY_LONG`、`is_holding=False`，且 code 当前仍在 `must_pool`
- `/stock-control` 当前页面布局
  - 左列展示“持仓股信号”
  - 中列展示“stock_pools模型信号”
  - 右列展示“must_pools买入信号”
  - 原“持仓股列表”已从该页移除
  - 三个列表当前统一使用 `/runtime-observability` 全局 Trace 同款 dense ledger，面板内滚动、sticky 表头
- `/stock-control` 的 Guardian 信号列表
  - `stock_signals` 当前会补齐 `created_at` 展示字段；历史缺失时回退 `fire_time`
  - 列结构当前为 `信号时间 / 入库时间 / 标的代码 / 标的名称 / 方向 / 类型 / 触发价/止损价/止损%`
  - `方向` 直接由 `position` 派生，`类型` 优先展示 `remark`，缺失时回退 `category`
  - 时间列统一压缩显示为 `MM-DD HH:mm`
  - 价格列统一为单行 `触发价/止损价/止损%` 顺序的紧凑值串，价格数值保留三位小数
  - `100%` 浏览器缩放下页面不再出现横向滚动，左右价格列按单行完整显示
- `/stock-control` 的 `stock_pools模型信号`
  - `realtime_screen_multi_period`
  - 当前展示 `datetime`、`created_at`、`code`、`name`、`period`、`source` 与单行价格摘要
  - `分组 / 模型` 当前复用 `/daily-screening` 对 CLX 12 模型的中文映射与分组真值

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
- 检查 `monitor.xtdata.mode` 是否是 `guardian_1m` 或 `guardian_and_clx_15_30`

### `stock_pools模型信号` 列表为空

- 检查 `realtime_screen_multi_period` 是否有数据
- 检查 XTData consumer 是否在跑
- 检查 `monitor.xtdata.mode` 是否切到了 `guardian_and_clx_15_30`
- 如果库里还是旧值 `clx_15_30`，运行时也会按联合模式执行

### 持仓有票，但 Guardian 卖点不触发

- 检查 `xt_positions` 是否有目标 code
- 检查 symbol/code6 是否规格一致
