# 仓位管理

## 职责

仓位管理负责把账户资产、单标的实时仓位和持仓状态转换成策略可消费的“是否允许提交”门禁结论。它不是订单提交器，也不是 broker 适配层。

## 入口

- worker
- 正式宿主机入口：`python -m freshquant.xt_account_sync.worker --interval 15`
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
  - `GET /api/position-management/symbol-limits`
  - `GET /api/position-management/symbol-limits/<symbol>`
  - `POST /api/position-management/symbol-limits/<symbol>`

## 依赖

- XT 资产/持仓快照
- 内部订单账本（仅用于解释 lot，不再定义当前仓位真值）
- Mongo
- Guardian / Order Submit
- Runtime Observability

## 数据流

账户级链路：

`XT credit detail -> xt_account_sync.worker -> pm_credit_asset_snapshots / pm_current_state -> evaluate_strategy_order -> allow/reject`

单标的链路：

`xt_account_sync.worker(15s) -> xt_positions -> SingleSymbolPositionService -> pm_symbol_position_snapshots -> evaluate_strategy_order / tpsl / subject-management`

提交门禁发生在 Order Management 接收策略单时。卖单原则上总是允许；买单先看账户级状态，再看单标的实时仓位上限。

当前 `xt_account_sync.worker` 默认每 15 秒刷新一次 `assets / credit_detail / positions`；其中 `credit_detail` 不是低频任务，因为 `available_bail_balance` 会直接影响 `pm_current_state` 与开仓门禁。低频的只有 `credit_subjects`。

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

当前同时支持“全局默认值 + 单标的覆盖值”：

- 默认值仍写在 `pm_configs.thresholds.single_symbol_position_limit`
- 单标的覆盖值写在 `pm_configs.symbol_position_limits.overrides.<symbol>`
- 买入门禁按 `override_limit ?? default_limit` 计算有效上限
- Dashboard 会同时返回 `default_limit / override_limit / effective_limit / market_value / blocked`

单标的实时仓位当前统一定义：

- 数量优先 `xt_positions.volume`
- 价格优先 `xt_positions.last_price`
- 市值直接使用 `xt_positions.market_value`
- 缺失券商持仓时，统一视为 `0`

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
- 单标的仓位上限摘要行
- holding scope
- 当前规则矩阵
- 最近决策摘要（包含 `decision_id / symbol / symbol_name / source / source_module / trace_id / intent_id`，以及单标的实时仓位来源）

其中 `effective_state`、`stale` 和规则说明均由服务端按真实 `PositionPolicy` 计算；最近决策会带出单标的实时仓位、上限来源与 trace 上下文，单标的仓位上限摘要会带出默认值、覆盖值和当前阻断状态。

单标的仓位上限摘要行当前同时返回三套仓位视图：

- 券商同步仓位
- 订单推断仓位
- `stock_fills` 对照仓位

三套视图都会带出 `quantity / market_value / source`，并额外返回数量一致性判定，便于页面直接高亮不一致标的。

## 页面组织

`/position-management` 当前已切到统一的 workbench density 语法：

- 页面顶部只保留标题、配置更新时间和状态摘要条
- 最近决策与上下文已合并为一张高密度 ledger，复用 `/runtime-observability` 全局 Trace 的表格语法
- 最近决策 ledger 一次展示 `触发时间 / 标的 / 动作 / 结果 / 门禁状态 / 触发来源 / 仓位上下文 / trace / intent / 附加上下文`
- 最近决策 ledger 默认分页 `100` 条，表体默认显示约 `10` 行，宽度不足时直接使用横向滚动
- 页面下半区固定为左中右三栏：左栏当前仓位状态与规则矩阵，中栏参数 inventory，右栏单标的仓位上限覆盖
- 参数 inventory 维持“可编辑阈值 + 只读参数”边界，但当前统一合并为一张紧凑表格，列包含 `分组 / 参数 / 当前值 / 编辑值 / 说明`
- 可编辑阈值当前包含账户级阈值和单标的实时仓位上限
- 持仓范围卡片已移除，不再单独展示 holding scope
- 规则矩阵已并入“当前仓位状态”，不再作为独立卡片
- “单标的仓位上限覆盖”固定放在右栏，集中展示 `券商同步仓位 / 订单推断仓位 / stock_fills 仓位 / 默认值 / 覆盖值 / 有效值 / 一致性 / 门禁`
- “单标的仓位上限覆盖”可直接编辑“覆盖值”，并调用 `POST /api/position-management/symbol-limits/<symbol>` 写回真实配置
- 已超限或三套仓位数量不一致的标的会在右栏覆盖表中高亮，便于缩放后快速定位
- 当前仓位状态改成摘要条、指标块和元数据块，不再使用大 hero

单标的覆盖值当前可直接从以下入口编辑：

- `/position-management` 右栏“单标的仓位上限覆盖”表
- `/subject-management` 的右侧“基础配置 + 单标的仓位上限”编辑表
- `/kline-slim` 的“标的设置”浮层

## holding scope 口径

页面展示的 holding scope 与门禁判断保持同一口径，不直接复用旧的股票持仓列表接口。

当前口径：

- `get_stock_positions()` / `get_stock_holding_codes()` 统一基于 `xt_positions`
- 页面和门禁只认最新一次券商同步快照
- `projected positions / open buy lots` 继续保留在订单管理里，用于解释成交来源与 lot 结构

## 部署/运行

- 改动后至少重启 worker：

```powershell
python -m freshquant.xt_account_sync.worker --interval 15
```

- 当前正式宿主机 worker 由 `xt_account_sync.worker` 承担；它负责账户级快照与 `xt_positions` 刷新。单标的实时仓位快照仍由 XTData `StrategyConsumer` 在消费 `1m BAR_CLOSE` 时同步刷新，worker 启动时只做一次 fallback 种子刷新。
- 当前正式宿主机 worker 由 `xt_account_sync.worker` 承担；它负责账户级快照、`xt_positions` 刷新以及 `pm_symbol_position_snapshots` 种子刷新。`StrategyConsumer` 不再用 `1m BAR_CLOSE` 改写当前仓位真值。
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
- 检查 `xt_positions` 最近是否被同步
- 检查 `pm_symbol_position_snapshots` 最近更新时间
- 检查目标 symbol 是否能从 `xt_positions` 解析到数量

### 盈利减仓语义异常

- 检查 `FORCE_PROFIT_REDUCE` 下的 `is_profitable` 元数据
- 检查 Guardian 卖单是否携带正确上下文
