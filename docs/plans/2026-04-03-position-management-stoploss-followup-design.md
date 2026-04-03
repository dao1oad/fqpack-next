# Position Management Stoploss Follow-up Design

## 背景

`PositionManagement` 第一轮高密度改版已经把中栏 `标的总览`、右栏选中标的工作区和左栏对账检查整合进同一工作台，但还有三类关键问题没有收口：

- 中栏字段名和实际系统语义不一致，尤其是 `止损价 / 首笔金额 / 常规金额 / 活跃止损`
- 右下 `最近决策与上下文` 仍按选中标的过滤，不符合“查看全部最近决策”的监控诉求
- 右上 `切片明细` 仍然跟每个 entry 卡片内联展示，没有形成明确的主从联动
- `must_pool.stop_loss_price` 目前只是配置字段，TPSL 运行时没有“symbol 级全仓止损”语义

## 目标

- 中栏字段文案和系统真实生效口径对齐
- `全仓止损价` 在 TPSL 中成为正式运行语义，触发时卖出该标的全部可卖仓位
- `最近决策与上下文` 变成全量时间线，不再受中栏选中态影响
- `聚合买入列表 / 按持仓入口止损` 与 `切片明细` 形成明确联动

## 非目标

- 不改 Guardian / 止盈的独立编辑入口
- 不改 `must_pool` 数据模型里原始字段名称
- 不引入新的独立页面或独立后端服务
- 不重做对账检查或门禁规则读模型

## 方案对比

### 方案 A：只改前端展示

- 只改列名、右栏联动和切片视图
- `全仓止损价` 仍然只是 `must_pool.stop_loss_price` 的展示名

缺点：

- 不能满足“触发时卖出所有仓位”的真实业务要求
- 页面语义和 TPSL 语义继续错位

### 方案 B：新增 symbol 级全仓止损语义，并保留 entry 级止损

- 把 `must_pool.stop_loss_price` 明确解释为 symbol 级 `全仓止损价`
- TPSL 评估时先看 symbol 级全仓止损，再看 entry 级止损
- 若同一 tick 同时命中，按用户确认使用“全仓止损优先，只生成一次全仓卖单”
- 中栏继续保留 entry 级止损编辑区，名字改成 `按持仓入口止损`

优点：

- 页面文案、配置来源、运行时行为一致
- entry 级止损和全仓止损职责清晰
- 对现有 `must_pool` 和 `entry_stoploss_bindings` 兼容

这是推荐方案。

### 方案 C：把全仓止损价复制到所有 open entry

- 保存 `全仓止损价` 时同步覆盖当前 open entries 的 entry stoploss

缺点：

- 新开 entry 无法自动继承
- 同一 symbol 下多 entry 语义混乱
- 无法准确表达“全仓止损优先”

## 前端设计

### 中栏 `标的总览`

- 去掉 `分类` 列和对应搜索维度中的分类依赖
- `止损价` 改为 `全仓止损价`
  - 显示 `base_config_summary.stop_loss_price.effective_value`
  - 来源说明继续显示 `must_pool.stop_loss_price / 未配置`
- `首笔金额` 改为 `开仓数量`
  - 页面展示当前系统首次开仓默认金额对应的有效开仓数量口径
  - 优先显示 `initial_lot_amount.effective_value`
  - 文案从“金额”切换成“数量”，避免把首次开仓逻辑误解为手工配置金额名词
- `常规金额` 改为 `默认买入金额`
  - 直接显示 `lot_amount.effective_value`
  - 来源按 `instrument_strategy.lot_amount -> must_pool.lot_amount -> guardian.stock.lot_amount`
- `活跃止损` 改为 `活跃单笔止损`
  - 仅统计 entry 级 stoploss

### 右上工作区

- 顶部保留“当前标的”摘要
- 中间区拆成两张表：
  - `聚合买入列表 / 按持仓入口止损`
  - `切片明细`
- 选中 symbol 后默认选中第一条 open entry
- 点击 entry 行后，只显示该 entry 的 `entry_slices`

### 右下 `最近决策与上下文`

- 不再跟选中 symbol 联动
- 直接展示全部 `recent_decisions`
- 按 `evaluated_at` 从近到远排序
- 保留分页

## 后端设计

### 读模型

- `subject-management` detail 继续复用现有 `base_config_summary`
- 不需要新增中栏字段；前端直接按现有 `effective_value / effective_source` 改展示
- `recent_decisions` 不再在前端按 symbol 过滤

### symbol 级全仓止损

- 新增 symbol 级 stoploss 读写逻辑，真值来自 `must_pool.stop_loss_price`
- TPSL 在 `evaluate_stoploss()` 中：
  - 先读取 symbol 的 `must_pool.stop_loss_price`
  - 若当前 `bid1 <= full_stop_price`，生成 symbol 级全仓 stoploss batch
  - 该 batch 直接按 symbol 聚合全部 open entry slices，并卖出全部可卖仓位
  - `scope_type` 使用独立语义，例如 `symbol_stoploss_batch`
  - `strategy_name` 使用明确名字，例如 `FullPositionStoploss`
- 若已触发 symbol 级全仓止损，则本 tick 不再生成 entry 级 stoploss batch

### entry 级止损

- 现有 `/api/order-management/stoploss/bind` 和 `om_entry_stoploss_bindings` 保持不变
- `PositionManagement` 右上继续只保存 entry 级止损

## 运行时事件

- stoploss 事件里要能区分：
  - `symbol_full_stoploss_hit`
  - `entry_stoploss_hit`
- 历史和 runtime observability 至少保证 `strategy_name / scope_type / remark` 可分辨

## 错误处理

- `全仓止损价` 为空时，不启用 symbol 级止损
- `全仓止损价` 命中但可卖数量不足一手时，返回 blocked batch，原因沿用 `board_lot`
- entry 明细为空时，右上 `切片明细` 显示空态，不报错

## 测试策略

- 前端 Node 测试：
  - `subjectManagement.mjs` 字段标签与有效值来源
  - `positionManagement.mjs` 最近决策全量排序
  - `PositionSubjectOverviewPanel.vue` 结构断言
  - `positionManagementSubjectWorkbench.mjs` entry 选中与切片过滤
- 浏览器 smoke：
  - `标的总览` 新列名
  - `最近决策与上下文` 不随选中 symbol 过滤
  - 右上 entry 选择后，切片明细只显示该 entry 的切片
- 后端 pytest：
  - symbol 级全仓止损优先于 entry 级止损
  - 全仓止损 batch 正确聚合全部 open entry slices
  - stoploss 命中事件能区分 symbol / entry 语义

## 受影响文件

- 前端
  - `morningglory/fqwebui/src/components/position-management/PositionSubjectOverviewPanel.vue`
  - `morningglory/fqwebui/src/views/PositionManagement.vue`
  - `morningglory/fqwebui/src/views/subjectManagement.mjs`
  - `morningglory/fqwebui/src/views/positionManagement.mjs`
  - `morningglory/fqwebui/src/views/positionManagementSubjectWorkbench.mjs`
  - `morningglory/fqwebui/tests/workbench-overlap.browser.spec.mjs`
- 后端
  - `freshquant/tpsl/service.py`
  - `freshquant/tpsl/stoploss_batch.py`
  - `freshquant/order_management/stoploss/service.py` 仅在需要共用 helper 时调整
  - 可能新增 `freshquant/tpsl/full_stoploss.py` 或在现有模块内补 helper
- 文档
  - `docs/current/modules/position-management.md`
  - `docs/current/modules/subject-management.md`
  - `docs/current/modules/tpsl.md`
