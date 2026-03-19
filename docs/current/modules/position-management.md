# 仓位管理

## 职责

仓位管理负责把账户资产、单标的实时仓位和持仓状态转换成策略可消费的“是否允许提交”门禁结论。它不是订单提交器，也不是 broker 适配层。

## 入口

- worker
  - 正式宿主机入口：`python -m freshquant.xt_account_sync.worker --interval 3`
- 核心服务
  - `freshquant.position_management.snapshot_service.PositionSnapshotService`
  - `freshquant.position_management.service.PositionManagementService`
  - `freshquant.position_management.symbol_position_service.SingleSymbolPositionService`
  - `freshquant.position_management.dashboard_service.PositionManagementDashboardService`
- Web UI
  - `/position-management`
- HTTP API
  - `GET /api/position-management/dashboard`
  - `GET /api/position-management/config`
  - `POST /api/position-management/config`

## 依赖

- XT 资产/持仓快照
- XTData producer `QUEUE:BAR_CLOSE:*`
- XTData `StrategyConsumer.handle_bar_close`
- projected positions / open buy lots
- Mongo
- Guardian / Order Submit
- Runtime Observability

## 数据流

账户级链路：

`XT credit detail -> xt_account_sync.worker -> pm_credit_asset_snapshots / pm_current_state -> evaluate_strategy_order -> allow/reject`

单标的链路：

`StrategyConsumer.handle_bar_close(1m) + xt_positions + projected positions -> SingleSymbolPositionService -> pm_symbol_position_snapshots -> evaluate_strategy_order / tpsl / subject-management`

提交门禁发生在 Order Management 接收策略单时。卖单原则上总是允许；买单先看账户级状态，再看单标的实时仓位上限。

## 存储

仓位管理单独使用 `freshquant_position_management`，主要集合：

- `pm_configs`
- `pm_credit_asset_snapshots`
- `pm_current_state`
- `pm_strategy_decisions`
- `pm_symbol_position_snapshots`

## 配置

关键策略状态：

- `ALLOW_OPEN`
- `HOLDING_ONLY`
- `FORCE_PROFIT_REDUCE`

当前默认规则：

- 状态超过 15 秒未刷新视为 stale
- stale 默认按 `HOLDING_ONLY` 处理
- 允许开仓的最低保证金默认约 `800000`
- 仅允许持仓内操作的最低保证金默认约 `100000`
- 单标的实时仓位上限默认约 `800000`

单标的实时仓位当前统一定义：

- 数量优先 `xt_positions.volume`
- 缺失时回退 `projected positions.quantity`
- 价格优先最新 `1m BAR_CLOSE.close`
- 缺失最新 `1m close` 时回退 `xt_positions.market_value`

当前页面配置边界：

- 可编辑并真实生效
  - `allow_open_min_bail`
  - `holding_only_min_bail`
  - `single_symbol_position_limit`
- 只读展示
  - `state_stale_after_seconds`
  - `default_state`
  - `xtquant.path`
  - `xtquant.account`
  - `xtquant.account_type`

阈值写入 `pm_configs.thresholds`。其中：

- `allow_open_min_bail / holding_only_min_bail` 在下一次账户快照刷新后影响 `state_from_bail()`
- `single_symbol_position_limit` 直接影响后续买入门禁

如果阈值刚更新、`pm_current_state` 还没被下一次 snapshot 刷新重算，Dashboard 会明确标记“阈值已更新，当前状态待下一次快照刷新”；在这段窗口期内，真实门禁仍按当前 `pm_current_state` 生效。
`POST /api/position-management/config` 只接受有限数值（finite number）阈值；`nan`、`inf`、`-inf` 会直接返回 400。若历史配置中出现这类脏值，Dashboard 读取时会回退到默认阈值，避免污染门禁判断。

## 页面读模型

`/api/position-management/dashboard` 当前聚合返回：

- 配置 inventory
- 当前 `raw_state` / `effective_state` / `stale`
- 最新资产摘要
- holding scope
- 当前规则矩阵
- 最近决策摘要（包含 `symbol / symbol_name` 以及单标的实时仓位来源）

其中 `effective_state`、`stale` 和规则说明均由服务端按真实 `PositionPolicy` 计算；最近决策还会带出单标的实时仓位与上限来源。

## 页面组织

`/position-management` 当前已切到统一的 workbench density 语法：

- 页面顶部只保留标题、配置更新时间和状态摘要条
- 参数 inventory 维持“可编辑阈值 + 只读参数”边界，但当前统一合并为一张紧凑表格，列包含 `分组 / 参数 / 当前值 / 编辑值 / 说明`
- 可编辑阈值当前包含账户级阈值和单标的实时仓位上限
- 当前仓位状态改成摘要条、指标块和元数据块，不再使用大 hero
- holding scope、规则矩阵、最近决策统一改成高密度列表/表格表达；最近决策主表显式展示标的名称

## holding scope 口径

页面展示的 holding scope 与门禁判断保持同一口径，不直接复用旧的股票持仓列表接口。

当前口径：

- `get_stock_positions()` 投影持仓
- `xt_positions` 外部账户持仓
- 两者 union 后得到 `get_stock_holding_codes()`

## 部署/运行

- 改动后至少重启 worker：

```powershell
python -m freshquant.xt_account_sync.worker --interval 3
```

- 当前正式宿主机 worker 由 `xt_account_sync.worker` 承担；它负责账户级快照与 `xt_positions` 刷新。单标的实时仓位快照仍由 XTData `StrategyConsumer` 在消费 `1m BAR_CLOSE` 时同步刷新，worker 启动时只做一次 fallback 种子刷新。
- 涉及门禁语义时，必须同时验证 Guardian 策略单与手工/API 单。

## 排障点

### 仓位状态一直不刷新

- 检查 `xt_account_sync.worker` 是否在跑
- 检查 XT 资产接口是否可读
- 检查 `pm_credit_asset_snapshots` 最近更新时间

### 所有买单都被拒绝

- 检查 `pm_current_state`
- 检查是否进入 stale
- 检查保证金阈值是否触发 `HOLDING_ONLY` 或 `FORCE_PROFIT_REDUCE`
- 检查 `pm_symbol_position_snapshots.market_value`
- 检查 `single_symbol_position_limit` 是否触发 `symbol_position_limit_blocked`

### 单标的实时仓位不刷新

- 检查 `xt_account_sync.worker` 是否在跑
- 检查 XTData `StrategyConsumer` 是否正常消费 `QUEUE:BAR_CLOSE:*` 的 `1m` 事件
- 检查 `pm_symbol_position_snapshots` 最近更新时间
- 检查目标 symbol 是否能从 `xt_positions` 或 projected positions 解析到数量

### 盈利减仓语义异常

- 检查 `FORCE_PROFIT_REDUCE` 下的 `is_profitable` 元数据
- 检查 Guardian 卖单是否携带正确上下文
