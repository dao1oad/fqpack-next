# 前端后续密度与可用性修复设计

## 目标

在已有 viewport shell 重构基础上，继续完成以下收口：

1. `kline-slim` 去掉无效说明字，压缩“标的设置 / 单标的仓位上限”信息密度。
2. `order-management` 把大筛选区改为“高级筛选”展开式。
3. `position-management` 压缩“当前仓位状态”，调整模块顺序，并修正超窄列。
4. `subject-management` 修复 `/overview` 的后端 500。
5. `tpsl` 修复 `stock_fills` 方向缺失的来源问题，并扩展窄列宽度。
6. `runtime-observability` 修复左侧组件卡片点击无响应，同时降低页面交互卡顿。

## 已确认事实

### `kline-slim`

- `基础配置` 标题旁的 `must_pool` 不是后端真值，而是 [KlineSlim.vue](D:/fqpack/freshquant-2026.2.23/.worktrees/frontend-followups-20260324/morningglory/fqwebui/src/views/KlineSlim.vue) 里的硬编码说明字。
- 真实 `512000` 详情中 `must_pool = None`，`scope_memberships = ['holding']`，因此当前文案会误导用户。
- “单标的仓位上限”现在同时展示默认值、当前值、来源、说明文案，信息密度偏低。

### `order-management`

- [OrderManagement.vue](D:/fqpack/freshquant-2026.2.23/.worktrees/frontend-followups-20260324/morningglory/fqwebui/src/views/OrderManagement.vue) 顶部筛选区始终展开，页面首屏被筛选器挤压。

### `position-management`

- [PositionManagement.vue](D:/fqpack/freshquant-2026.2.23/.worktrees/frontend-followups-20260324/morningglory/fqwebui/src/views/PositionManagement.vue) 当前把“参数 inventory”放在“规则矩阵”前面，与用户关注顺序相反。
- “当前仓位状态”里存在大量留白，信息分布过松。
- “推断仓位 / stock_fills仓位”列宽不足，导致数值无法完整展示。

### `subject-management`

- `SubjectManagementDashboardService.get_overview()` 会对并集里的每个 symbol 调 `position_management.get_symbol_limit()`。
- 其中任何一个 symbol 不在 holdings/pools 追踪范围内，就会抛 `ValueError("symbol is not tracked by holdings or pools")`，整页 500。
- 这是后端真 bug，不是纯前端展示问题。

### `tpsl`

- [TpslManagement.vue](D:/fqpack/freshquant-2026.2.23/.worktrees/frontend-followups-20260324/morningglory/fqwebui/src/views/TpslManagement.vue) 模板里仍然有“方向”列，前端没有删掉该列。
- 问题在数据链：`TpslManagementService -> get_stock_fills()` 返回的 `stock_fills` 记录里根本没有 `op` 字段，只有 `source=external_inferred` 等聚合字段。
- 对这类“外部推断持仓”记录，无法伪造真实成交方向，只能明确标注来源并给出可读的方向占位。

### `runtime-observability`

- 左侧组件卡片点击链路在源码里存在：`handleComponentFilter()` 会设置 `boardFilter.component` 并把 `activeView` 切到 `events`。
- 当前页面存在两类风险：
  1. 交互态依赖多个 `watch` 和整页刷新，组件切换很容易被并发刷新和默认回退逻辑吞掉。
  2. 页面把 trace/detail/event 的大量派生计算都堆在单文件组件中，切换时会触发整页级 recompute，交互阻尼大。
- 在最小 mock 环境下，旧 headless Chrome 能拿到页面标题，但渲染很快断开，说明当前构建产物确实存在脆弱的页面生命周期问题；不把交互和派生状态拆薄，这类问题还会反复出现。

## 设计决策

### 1. `kline-slim` 只保留有决策价值的信息

- 去掉基础配置标题旁的硬编码 `must_pool` 提示。
- 将“单标的仓位上限”压成四块：
  - 当前生效值
  - 市值
  - 可编辑设置框
  - 买入状态
- 删除“系统默认值 / 当前来源 / 说明长句”这类对当前场景决策价值低的重复展示。

### 2. 列表页统一采用“主操作显性，高级条件折叠”

- `order-management` 顶部保留核心筛选与统计，把长筛选表单收进“高级筛选”展开区。
- 默认关闭，保留已生效条件 chips，避免用户误以为筛选消失。

### 3. `position-management` 改成“结论先行”

- “规则矩阵”前置到“参数 inventory”之前。
- “当前仓位状态”压成紧凑的 summary + dense ledger，不再用大块留白。
- symbol-limit ledger 中放宽“推断仓位 / stock_fills仓位”列。

### 4. `subject-management` 先兜底，再保真

- overview 聚合时对未追踪 symbol 的 `position_limit` 查询做异常兜底，返回空 summary 而不是整页报错。
- 同时保留“该 symbol 未被 position-management 追踪”的信息，以免把异常静默吞掉。

### 5. `tpsl` 区分“真实成交方向”与“推断持仓来源”

- 对仍有 `op` 的旧 `stock_fills` 记录继续显示实际方向。
- 对 `external_inferred` 这类纯持仓快照记录，前端显示 `推断持仓`，而不是空白。
- 扩大“原始/剩余”列宽，避免数值截断。

### 6. `runtime-observability` 拆交互与派生状态

- 将“左侧组件选中态”和“events 请求 key”收口成单一切换入口，避免多个 `watch` 互相回写。
- 组件卡片点击后立即切 view，再异步刷新 events，保证有可见响应。
- 让 `componentSidebarItems` 只在 overview 数据变更时回填默认组件，禁止在用户已显式选择后强制重置。
- 对重计算链做最小化：
  - 减少每次切换时对全量 traces 的重复 hydration
  - 把 trace/detail/event 的派生依赖分层，避免切一个 sidebar 卡片时整页跟着重算

## 影响文件

### 前端

- `morningglory/fqwebui/src/views/KlineSlim.vue`
- `morningglory/fqwebui/src/views/klineSlim.test.mjs`
- `morningglory/fqwebui/src/views/OrderManagement.vue`
- `morningglory/fqwebui/src/views/orderManagement.test.mjs`
- `morningglory/fqwebui/src/views/PositionManagement.vue`
- `morningglory/fqwebui/src/views/position-management.test.mjs`
- `morningglory/fqwebui/src/views/SubjectManagement.vue`
- `morningglory/fqwebui/src/views/subjectManagement.test.mjs`
- `morningglory/fqwebui/src/views/tpslManagement.mjs`
- `morningglory/fqwebui/src/views/TpslManagement.vue`
- `morningglory/fqwebui/src/views/tpslManagement.test.mjs`
- `morningglory/fqwebui/src/views/runtimeObservability.mjs`
- `morningglory/fqwebui/src/views/RuntimeObservability.vue`
- `morningglory/fqwebui/src/views/runtime-observability.test.mjs`

### 后端

- `freshquant/subject_management/dashboard_service.py`
- `freshquant/tpsl/management_service.py`

### 文档

- `docs/current/modules/subject-management.md`
- `docs/current/modules/tpsl.md`
- `docs/current/modules/runtime-observability.md`

## 验收

1. `kline-slim` 不再出现误导性的 `must_pool` 标题注记，仓位上限区更紧凑。
2. `order-management` 默认不再常驻大块高级筛选区。
3. `position-management` 的当前仓位状态更紧凑，规则矩阵前置，窄列完整显示。
4. `subject-management` 不再因为单个未追踪 symbol 整页 500。
5. `tpsl` 的 `stock_fills` 方向列对推断持仓不再空白，窄列完整显示。
6. `runtime-observability` 左侧组件卡片点击后立即切到组件 Event 视图，并正确刷新该组件事件。
