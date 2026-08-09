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

- 用于共享预选池 / 工作区真值
- 当前正式口径是“同一个 `code` 只保留一条记录”
- `sources / categories / memberships` 用于区分 `daily-screening`、`shouban30` 等来源和分类
- 顶层 `workspace_order` 是共享页面与 `.blk` 输出顺序真值；兼容字段 `extra.shouban30_order` 仍保留用于旧页面桥接

### `stock_pools`

- 表示进入进一步跟踪或候选交易的池子
- 若由 `stock_pre_pools` / `pre_pool` 转入，会保留顶层 `sources / categories / memberships`，用于说明来源和命中分类
- `load_monitor_codes(mode=guardian_and_clx_15_30)` 会在 Guardian 池之后补充非过期 `stock_pools`
- `load_monitor_codes(mode=clx_15_30_only)` 只读取非过期 `stock_pools`
- 兼容旧值 `clx_15_30`，读取时会按联合模式执行

### `must_pool`

- 是 Guardian 新开仓范围的重要来源
- 也是 XTData `guardian_1m` 和 `guardian_and_clx_15_30` 订阅池的一部分
- 当前正式口径仍是“同一个 `code` 只保留一条主记录”
- `sources / categories / memberships` 用于保留从 `stock_pools`、`shouban30`、`daily-screening` 等进入 `must_pool` 的 provenance
- 顶层 `category` 是兼容摘要字段；优先 `manual_category`，否则按主 `membership` 推导
- `SubjectManagement` 只编辑 `manual_category` 和交易参数，不直接编辑 `memberships`
- 记录止损价、首笔金额、常规 lot 金额
- `forever` 当前固定写为 `true`，不再作为页面可配置项
- `workspace_order_hint` 用于 `must_pool -> 30RYZT.blk` 的输出顺序，缺失时回退 `updated_at / created_at / datetime desc`

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
  - `clx_15_30_only` 下只读取非过期 `stock_pools`
  - 实时模型为 `S0000-S0017 / 10000..10017`
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
  - 实时 CLX 生产模型为 `S0000-S0017 / 10000..10017`
- CLX 15/30 实时监控命中标的通达信分组
  - consumer 正信号写库后会把本批命中标的去重追加到通达信自选股分组 `clx_15_30`（`T0002/blocknew/CLX_15_30.blk`）
  - 复用 `freshquant/clx_daily_selection/tdx_export.py` 的编码与原子写实现，best-effort 失败不阻塞信号链

## 当前高频操作

- 代码加入 `stock_pools`
  - `/api/add_to_stock_pools_by_code`
  - 会把 `pre_pool` 的 `sources / categories / memberships` 一并写入 `stock_pools`
  - 默认仍依赖 `pre_pool`；传 `allow_direct=1` 时可直接写入 `stock_pools`，并显式写入 `expire_at / sources / categories / memberships`
- KlineSlim CLX 工作台加入实时监控
  - `/kline-slim?clxScreening=1&clxWorkbench=1&period=1d` 右侧 `CLX 信号工作台` 的 `加入clx15分钟监控` 按钮会把当前标的写入 `stock_pools`
  - 该按钮只加入 `stock_pools`，不加入 `must_pool`，不触发下单
  - 写入后可作为 `clx_15_30_only` 的实时监控池来源
- KlineSlim 从通达信自选股同步到 `stock_pools`
  - `/kline-slim` 左侧 `stock_pools` 分组的 `同步自选股` 按钮调用 `POST /api/sync_stock_pools_from_tdx_self_select?days=30`
  - 后端读取当前 TDX home 下的 `T0002/blocknew/ZXG.blk`，解码通达信前缀代码，排除当前 `xt_positions` 持仓后，以该集合覆盖 `stock_pools`
  - 不在当前 TDX 标的池中的旧 `stock_pools` 记录会被删除；当前 TDX 标的会按 `tdx_self_select` 来源更新，默认有效期 30 天
  - 同步只写 `stock_pools`，不写 `must_pool`，不触发下单；左侧 `stock_pools` 分组仍会过滤已在“持仓股”分组出现的标的
- KlineSlim 从通达信「待买」分组导入 `must_pool`
  - `/kline-slim` 左侧 `must_pool` 分组的 `同步待买` 按钮调用 `POST /api/sync_must_pool_from_tdx_self_select?days=30`
  - 后端先解析 `T0002/blocknew/blocknew.cfg`，按显示名「待买」找到真实 BLK 文件名（当前宿主机为 `DM.blk`），cfg 缺失或未登记时回退 `T0002/blocknew/待买.blk`；读取后解码通达信前缀代码，排除当前 `xt_positions` 持仓后，增量导入 `must_pool`
  - 导入为增量合并：已存在 `must_pool` 记录保留 `stop_loss_price / initial_lot_amount / lot_amount` 交易参数，仅合并 `tdx_must_pool` 来源 provenance；不在「待买」分组中的既有 `must_pool` 记录不会被删除
  - 新增记录 `stop_loss_price` 保持未配置（`None`），`lot_amount / initial_lot_amount` 走 `get_trade_amount` 默认值；`forever` 固定为 `true`
  - 导入只写 `must_pool`，不写 `stock_pools`，不触发下单
- 代码加入 `must_pool`
  - `/api/add_to_must_pool_by_code`
  - 当前显式加入后统一固定写 `forever=true`
  - 会把 `stock_pools` 的 provenance merge 到 `must_pool`
- 代码从 `must_pool` 删除
  - `/api/delete_from_must_pool_by_code`
  - 当前显式删除只按 `code` 删除整条主记录，不再看 `forever`
- 读取 Guardian 信号列表
  - `/api/get_stock_signal_list`
- 读取 stock_pools 模型信号列表
  - `/api/get_stock_model_signal_list`
- Shouban30 预选池转股票池
  - `/api/gantt/shouban30/pre-pool/add-to-stock-pools`
  - 对已存在 `stock_pool` 的 code，也会补齐 `sources / categories / memberships`
- Shouban30 预选池批量转股票池
  - `/api/gantt/shouban30/pre-pool/sync-to-stock-pool`
- Shouban30 同步到通达信
  - `/api/gantt/shouban30/pre-pool/sync-to-tdx`
  - `/api/gantt/shouban30/stock-pool/sync-to-tdx`
- Shouban30 must_pool 同步到通达信
  - `/api/gantt/shouban30/must-pool/sync-to-tdx`
  - `/api/gantt/shouban30/must-pool/clear`
  - 两个动作都以当前 `must_pool` 全量主记录为真值并完整覆盖 `30RYZT.blk`

## 当前排查

### 股票在页面工作区里，但策略不看

- 检查是否只在 `stock_pre_pools`
- 检查是否真正进入 `stock_pools`
- 如果策略链路需要 Guardian 新开仓，再继续检查是否进入 `must_pool`

### 股票已在 must_pool，但 XTData 还没订阅

- 检查 producer 订阅池是否刷新
  - 检查 `monitor.xtdata.trading_mode` 是否为 true
  - 若生产配置为 `trading_mode=false`，交易线不订阅 `must_pool`

### `stock_pools模型信号` 列表为空

- 检查 `realtime_screen_multi_period` 是否有数据
- 检查 XTData consumer 是否在跑
  - 检查 `monitor.xtdata.screening_mode` 是否为 true
  - 旧 `monitor.xtdata.mode`（如 `clx_15_30`）由一次性迁移映射后退役

### 持仓有票，但 Guardian 卖点不触发

- 检查 `xt_positions` 是否有目标 code
- 检查 symbol/code6 是否规格一致
