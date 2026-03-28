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
- 单标的默认持仓上限默认约 `800000`

单标的实时仓位上限当前统一使用“系统默认值兜底 + 显式 override”语义：

- 系统级“单标的默认持仓上限”的真值仍写在 `pm_configs.thresholds.single_symbol_position_limit`
- 该默认值可在 `/system-settings -> 仓位门禁` 直接编辑
- 单标的覆盖值写在 `pm_configs.symbol_position_limits.overrides.<symbol>`
- 标的级 override 仍在 `/position-management` 等标的入口维护，不并入 `/system-settings`
- 没有 override 时，实际生效值天然等于系统默认值
- 买入门禁按 `override_limit ?? default_limit` 计算有效上限
- 保存值等于系统默认值时，后端会自动删除 override
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
  - `single_symbol_position_limit`（系统级单标的默认持仓上限）
- 只读展示
  - `state_stale_after_seconds`
  - `default_state`
  - `xtquant.path`
  - `xtquant.account`
  - `xtquant.account_type`

阈值写入 `pm_configs.thresholds`。其中：

- `allow_open_min_bail / holding_only_min_bail` 在下一次账户快照刷新后影响 `state_from_bail()`
- `single_symbol_position_limit` 作为系统级单标的默认持仓上限，直接影响后续买入门禁

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

其中 `effective_state`、`stale` 和规则说明均由服务端按真实 `PositionPolicy` 计算；最近决策会带出单标的实时仓位、上限来源与 trace 上下文，单标的仓位上限摘要会带出系统默认值（即单标的默认持仓上限）、当前生效值、来源事实和当前阻断状态。

最近决策当前会对以下字段做系统真值回填：

最近决策中的实时市值、仓位上限、市值来源、数量来源、盈利减仓、减仓模式和附加上下文字段都会做系统真值回填。

- `实时市值`
- `仓位上限`
- `市值来源`
- `数量来源`
- `盈利减仓`
- `减仓模式`
- `附加上下文`

如果历史 `pm_strategy_decisions.meta` 缺少这些字段，Dashboard 会用当前 `pm_symbol_position_snapshots`、`pm_configs.symbol_position_limits` 和 tracked scope 口径补齐。其中附加上下文至少会带出 `symbol_limit_source`、`symbol_scope_memberships` 等当前系统真值。

单标的仓位上限摘要行当前同时返回三套仓位视图：

- 券商同步仓位
- 订单推断仓位
- `stock_fills` 兼容镜像仓位
  - 后端实际读取 `freshquant.stock_fills_compat`，只在 compat 缺失时才兜底原始 `stock_fills`

三套视图都会带出 `quantity / market_value / source`。其中“订单推断仓位”和“`stock_fills` 兼容镜像仓位”在页面展示前会按券商仓位真值对齐，`source` 会保留 `broker_truth` 标记，避免把对齐后的显示视图误当成原始 lot 残量。

单标的仓位上限摘要行只保留 tracked scope 内的 symbol：

- 当前持仓股
- `must_pool`
- `stock_pools`
- `pre_pools`

脏数据只要不在持仓股、must_pool、stock_pools、pre_pools 中，就不会进入“单标的仓位上限覆盖”，即使它残留在旧 snapshot、订单推断仓位或 `stock_fills` 兼容视图里也一样。

## 页面组织

`/position-management` 当前已切到统一的 workbench density 语法：

- 页面顶部不再保留“仓位管理”标题卡片
- 三栏摘要区上移到“最近决策与上下文”上方
- 当前仓位状态与参数 inventory 已合并为左栏，顶部第一行只保留左右两栏
- 左栏继续展示当前仓位状态、资产摘要、参数 inventory 和规则矩阵；右栏保留更宽的“单标的仓位上限覆盖”
- 最近决策与上下文已合并为一张高密度 ledger，复用 `/runtime-observability` 全局 Trace 的表格语法
- 最近决策 ledger 一次展示 `触发时间 / 标的 / 动作 / 结果 / 门禁状态 / 触发来源 / 仓位上下文 / trace / intent / 附加上下文`
- 最近决策 ledger 默认分页 `100` 条，表体默认显示约 `15` 行，宽度不足时直接使用横向滚动
- 参数 inventory 维持“可编辑阈值 + 只读参数”边界，但当前统一合并为左栏中的一张紧凑表格，说明列已移除，编辑态直接嵌入“当前值”列
- 可编辑阈值当前包含账户级阈值和单标的默认持仓上限
- 持仓范围卡片已移除，不再单独展示 holding scope
- 规则矩阵已并入“当前仓位状态”，不再作为独立卡片，也不再使用滚动条隐藏三种状态
- 当前命中规则说明改成与资产摘要同层级的紧凑指标卡，不再单独使用虚线提示块
- “单标的仓位上限覆盖”固定放在右栏，集中展示 `单标的上限设置 / 操作 / 当前来源 / 一致性 / 门禁 / 券商同步仓位 / 订单推断仓位 / stock_fills 仓位`
  - 页面列名仍保留 `stock_fills` 以兼容原有认知，但后端来源是 `stock_fills_compat`
  - 订单推断仓位与 `stock_fills` 对照视图都会按券商仓位真值对齐，只保留来源语义和 `broker_truth` 标记
- “单标的仓位上限覆盖”当前只展示持仓股，并按券商真值仓位市值从大到小排序
- 顶部摘要条、规则矩阵结果、右栏一致性/门禁状态和最近决策结果当前统一复用共享 `StatusChip` 语义，不再各自维护本地 `runtime-inline-status` 颜色类
- 顶部两栏标题当前只保留标题与操作，移除说明长句；顶部双栏当前恢复等高面板，顶部双栏都改为面板内竖向滚动，这样首屏就能把“最近决策与上下文”露出来
- “单标的仓位上限覆盖”里的系统默认值（即单标的默认持仓上限）列已移除；输入框默认直接展示当前生效值，`操作` 列挪到 `当前来源` 前
- “单标的仓位上限覆盖”里的 `券商仓位 / 订单推断仓位 / stock_fills 仓位` 当前都挪到主列右侧，最小宽度上调并会扩展占满右栏剩余宽度；其中 `订单推断仓位 / stock_fills 仓位` 内容左对齐，来源文本会截断显示并保留 tooltip，避免扰乱主列排版
- 右栏三列仓位当前改成表头与数据行共用固定列宽，避免右侧三列在长来源文本下发生错位
- “当前命中规则”卡片当前复用 `position-metric-card` 的标题与数值样式，只保留详情文案段落，并与“可用保证金”等小指标卡保持同尺寸
- “单标的仓位上限覆盖”输入框默认展示当前生效值，并调用 `POST /api/position-management/symbol-limits/<symbol>` 写回真实配置
- “单标的仓位上限覆盖”保存值等于系统默认值时，后端会自动删除 override，不再存在 `use_default / 恢复默认 / 默认-单独切换`
- “单标的仓位上限覆盖”里的金额统一按“万”展示，并保留两位小数
- 已超限或三套仓位数量不一致的标的会在右栏覆盖表中高亮，便于缩放后快速定位
- 当前仓位状态改成摘要条、指标块和元数据块，不再使用大 hero

标的级 override 当前仍可直接从以下入口编辑，三个入口共享同一语义：

- `/position-management` 右栏“单标的仓位上限覆盖”表
- `/subject-management` 的右侧“基础配置 + 单标的仓位上限”编辑表
- `/kline-slim` 的“标的设置”浮层

这些入口维护的是单标的 override，不是 `/system-settings -> 仓位门禁` 里的系统级单标的默认持仓上限。

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
- 如果只是右栏 `stock_fills` 视图不一致，先查 `om_buy_lots`，再查 `freshquant.stock_fills_compat` 是否同步

### 盈利减仓语义异常

- 检查 `FORCE_PROFIT_REDUCE` 下的 `is_profitable` 元数据
- 检查 Guardian 卖单是否携带正确上下文
