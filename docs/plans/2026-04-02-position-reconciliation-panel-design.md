# 仓位管理对账面板与只读一致性检查设计

## 背景

当前 `/position-management` 右栏“单标的仓位上限覆盖”同时承载了两类职责：

- 可写职责
  - 单标的上限 override 编辑
  - 门禁结果查看
- 只读职责
  - 券商仓位
  - 账本仓位
  - 对账状态
  - 一致性提示

这导致两个问题：

1. “改单标的上限”和“看仓位/账本是否一致”被混在一张表里，读写边界不清楚。
2. 当前页面里的“账本仓位”已经被对齐回 broker truth，展示语义不再是纯账本值，不适合作为多视图一致性检查的原始输入。

## 目标

- 把仓位/账本/对账相关的只读检查，从“基础配置 + 单标的仓位上限”中提取出来
- 在 `/position-management` 中新增独立的“对账检查”面板
- 新增一个严格只读的一致性检查读模型，明确哪些视图本应相等，哪些只是参考视图
- 统一 reconciliation 状态枚举、中文标签和严重级别

## 非目标

- 不在本次设计中引入任何自动修复、自动平账、镜像重建或账本重建动作
- 不修改 `xt_positions`、`om_*`、`stock_fills_compat` 的写链
- 不把 `/subject-management`、`/tpsl` 一并改造成完整复用新面板
- 不新增独立页面路由 `/position-reconciliation`

## 当前系统事实

### 仓位与订单相关视图分层

当前与订单/仓位相关的视图，可以稳定分成以下几层：

1. 券商真值层
   - `xt_positions`
   - `xt_orders`
   - `xt_trades`
2. 券商真值投影层
   - `pm_symbol_position_snapshots`
3. 执行事实层
   - `om_broker_orders`
   - `om_execution_fills`
   - `om_trade_facts`
4. 持仓解释层
   - `om_position_entries`
   - `om_entry_slices`
   - `om_exit_allocations`
5. 对账与兼容层
   - `om_reconciliation_gaps`
   - `om_reconciliation_resolutions`
   - `om_ingest_rejections`
   - `stock_fills_compat`
   - `/api/stock_fills` 当前 open position 投影

### 哪些视图应该相等

#### 必须相等

- `xt_positions`
- `pm_symbol_position_snapshots`

#### 在账本已对齐前提下应相等

- open `om_position_entries` 汇总
- open `om_entry_slices` 汇总
- `stock_fills_compat` open position 汇总
- `/api/stock_fills` 当前 open position 汇总

#### 不应该直接要求等于当前仓位

- `xt_orders`
- `xt_trades`
- `om_broker_orders`
- `om_execution_fills`
- `om_trade_facts`
- raw `stock_fills`

这些视图是“发生过什么”的事实，不是“现在还剩多少”的当前仓位。

### 当前 reconciliation 汇总态

当前汇总态来自 `freshquant.order_management.reconcile.summary.summarize_symbol_reconciliation`，正式汇总态有 5 种：

- `ALIGNED`
- `OBSERVING`
- `AUTO_RECONCILED`
- `BROKEN`
- `DRIFT`

## 方案比较

### 方案 A：继续保留在“单标的仓位上限”表中

把“券商仓位 / 账本仓位 / 对账状态 / 一致性”保留在当前表里，只把渲染抽成子组件。

- 优点：前端改动最小
- 缺点：职责仍然耦合；对账检查继续依附于“单标的 override 编辑”语义，不利于后续复用

### 方案 B：新增独立“对账检查”面板并采用只读读模型（采用）

把当前页面拆成“配置编辑区”“单标的上限编辑区”“对账检查区”“最近决策区”四块；对账检查由新接口返回 canonical row。

- 优点：读写边界最清晰；后续可以被 `TPSL`、`SubjectManagement` 复用
- 缺点：需要同时改后端读模型、前端组件和页面布局

### 方案 C：新开 `/position-reconciliation` 独立页面

- 优点：信息架构最干净
- 缺点：页面入口分裂；当前用户在 PM 页面里查看门禁与对账的链路被打断

## 采用设计

采用方案 B。

### 页面布局

`/position-management` 调整为：

1. 第一行双栏
   - 左：基础配置
   - 右：单标的仓位上限
2. 第二行全宽
   - 对账检查
3. 第三行全宽
   - 最近决策与上下文

### 单标的仓位上限表保留字段

保留：

- `标的`
- `单标的上限设置`
- `当前来源`
- `门禁`
- `操作`

移除：

- `一致性`
- `券商仓位`
- `账本仓位`
- `对账状态`

### 新的只读对账接口

新增：

- `GET /api/position-management/reconciliation`
- `GET /api/position-management/reconciliation/<symbol>`

接口返回 canonical DTO：

- `summary`
  - 总行数
  - `OK/WARN/ERROR` 数量
  - 各 reconciliation state 数量
- `rows`
  - 每个 symbol 的 broker/snapshot/entry/slice/compat/api projection
  - reconciliation 汇总态
  - 只读 audit 结果
  - mismatch codes

### 只读审计规则

#### R1 broker_snapshot_consistency

比较：

- `xt_positions`
- `pm_symbol_position_snapshots`

预期：

- 必须一致

#### R2 ledger_internal_consistency

比较：

- `om_position_entries`
- `om_entry_slices`

预期：

- 必须一致

#### R3 compat_projection_consistency

比较：

- `om_position_entries`
- `stock_fills_compat`
- `/api/stock_fills`

预期：

- 应一致

#### R4 broker_vs_ledger_consistency

比较：

- `xt_positions`
- `om_position_entries`

预期：

- 不要求直接相等
- 必须由 reconciliation 状态解释

判定：

- `OK`
  - `broker == ledger`
  - 且 state 为 `ALIGNED` 或 `AUTO_RECONCILED`
- `WARN`
  - `broker != ledger`
  - 且 state 为 `OBSERVING`
- `ERROR`
  - `broker != ledger`
  - 且 state 为 `BROKEN`、`DRIFT` 或状态缺失

### 新组件设计

新增：

- `PositionReconciliationPanel.vue`

组件职责：

- 展示 summary chips
- 展示只读 dense ledger
- 展示 symbol detail evidence

组件不负责：

- 修改任何配置
- 触发自动平账
- 触发 compat sync
- 调用任何修复接口

### 主表字段

主表固定展示：

- `标的`
- `券商`
- `PM快照`
- `Entry账本`
- `对账状态`
- `检查结果`
- `最新 resolution`

detail evidence 展示：

- `Slice账本`
- `Compat镜像`
- `StockFills投影`
- `mismatch_codes`
- `signed gap`
- `open gap`
- `sources`

### 统一状态元数据

新增共享前端状态元数据：

- `reconciliationStateMeta.mjs`

统一：

- 中文 label
- chip variant
- severity

避免 `/position-management`、`/tpsl`、`/subject-management` 各自维护大写/小写和不同颜色语义。

## 后端契约约束

- 新只读服务不允许通过 HTTP 自调本仓库接口
- 直接复用：
  - `xt_positions`
  - `pm_symbol_position_snapshots`
  - `repository.list_position_entries()`
  - `repository.list_open_entry_slices()`
  - `StockFillsCompatibilityService.compare_symbol()`
  - `holding.get_stock_fill_list()`
  - `build_reconciliation_summary_map()`
- 不复用当前 PM symbol-limit row，因为其账本视图已被 broker truth 覆盖

## 测试要求

### 后端

新增 `test_position_reconciliation_read_service.py`，覆盖：

- `ALIGNED`
- `OBSERVING`
- `AUTO_RECONCILED`
- `BROKEN`
- `DRIFT`
- odd-lot rejection
- compat mismatch
- api projection mismatch

### 前端

新增：

- `positionReconciliation.test.mjs`

覆盖：

- state label/variant/severity
- `OK/WARN/ERROR` 排序
- state/severity/query 过滤
- detail evidence 展开

### 页面回归

更新 `position-management.test.mjs`：

- 断言“单标的仓位上限”表不再出现对账列
- 断言页面新增“对账检查”独立面板

## 验收标准

- `/position-management` 中，配置编辑与对账检查职责明显分离
- 对账检查完全只读
- 主表能够先给出 symbol 级结论，detail 再给 evidence
- `BROKEN / DRIFT` 一眼可见
- `OBSERVING` 被标记为警告，不被误当作错误
- 当前页面不再把对账信息绑在“单标的上限编辑”表中
