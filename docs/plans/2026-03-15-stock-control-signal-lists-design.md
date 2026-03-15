# Stock Control Signal Lists Design

## 背景

`/stock-control` 当前仍保留旧的“候选股信号”文案，但实际查询语义只是 `stock_signals` 中 `is_holding=False` 且 `position=BUY_LONG` 的记录。这个口径和当前新模式 `guardian_1m` 的正式监控语义不一致。

同时，`realtime_screen_multi_period` 已经保存 `stock_pools` 模型信号，但前端没有对应展示入口，导致 `clx_15_30` 链路的实时信号无法在现有控制页中查看。

此外，旧 `poll` 模式已经废弃，不再属于正式运行面，应从 CLI、代码路径和文档说明中清理。

## 目标

- 清理废弃 `poll` 模式，只保留 Guardian event 模式。
- 将 `/stock-control` 左侧原“候选股信号”改为“must_pools买入信号”。
- 将该列表的后端语义收紧为“当前 `must_pool` 中、当前非持仓、方向为 `BUY_LONG` 的 `stock_signals`”。
- 在 `/stock-control` 新增“stock_pools模型信号”列表，展示 `realtime_screen_multi_period` 的 8 个字段：
  - `datetime`
  - `created_at`
  - `code`
  - `name`
  - `period`
  - `model`
  - `close`
  - `stop_loss_price`
  - `source`

## 非目标

- 不改变 `realtime_screen_multi_period` 的写入结构。
- 不引入新的实时计算逻辑。
- 不改动 Guardian 的信号判定规则。
- 不把 `stock_pools` 模型信号复用到现有 `SignalList` 的 Guardian 数据结构中。

## 设计

### 1. 废弃 `poll` 模式

- `freshquant.signal.astock.job.monitor_stock_zh_a_min` 的 CLI 入口移除 `poll` 选项。
- 保留 event 主路径，删除/裁剪仅用于 `poll` 的代码分支。
- 同步更新 `docs/current/**`，只保留 `--mode event` 作为正式入口。

### 2. must_pools 买入信号

- 现有 `/api/get_stock_signal_list` 保留用于持仓信号。
- 新增更明确的后端查询语义：当 `category=must_pool_buys` 时，返回满足以下条件的 `stock_signals`：
  - `position="BUY_LONG"`
  - `is_holding=False`
  - `code` 当前存在于 `must_pool`
- `/stock-control` 左侧列表标题改为“must_pools买入信号”，并把查询参数改为 `must_pool_buys`。

### 3. stock_pools 模型信号列表

- 后端新增独立接口读取 `realtime_screen_multi_period`。
- 默认按 `datetime DESC`，必要时再用 `created_at DESC` 做稳定排序。
- 返回前端直接可用的 8 个展示字段，时间格式统一转字符串。
- 前端新增独立组件显示这 8 列，避免和 Guardian `SignalList` 字段结构耦合。

### 4. 页面布局

- `/stock-control` 左列顺序调整为：
  - `StockPositionList`
  - `must_pools买入信号`
  - `stock_pools模型信号`
- 右列继续保留“持仓股信号”。

## 影响文件

- 后端
  - `freshquant/signal/astock/job/monitor_stock_zh_a_min.py`
  - `freshquant/rear/stock/routes.py`
  - `freshquant/stock_service.py`
- 前端
  - `morningglory/fqwebui/src/views/StockControl.vue`
  - `morningglory/fqwebui/src/views/SignalList.vue`
  - `morningglory/fqwebui/src/api/stockApi.js`
  - 新增模型信号列表组件
- 文档
  - `docs/current/runtime.md`
  - `docs/current/modules/strategy-guardian.md`
  - `docs/current/modules/kline-webui.md`
  - `docs/current/reference/stock-pools-and-positions.md`

## 测试策略

- 后端：
  - 为 `must_pool_buys` 查询补单测。
  - 为 `realtime_screen_multi_period` 查询补单测。
  - 为 `poll` 清理后的 CLI 行为补单测。
- 前端：
  - 为 `/stock-control` 新标题和新增模型信号列表补测试。
- 验证：
  - 运行相关 pytest。
  - 运行相关前端测试。

