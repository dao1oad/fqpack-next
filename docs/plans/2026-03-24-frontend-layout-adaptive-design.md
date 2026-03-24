# Frontend Layout Adaptive Refactor Design

## 目标

把 `morningglory/fqwebui` 当前“页面各自管理高度/滚动”的实现收口为统一 viewport shell，保证主工作台页面在浏览器 `1920x1080`、缩放 `100%` 下满足：

- 不出现浏览器纵向页面滚动条。
- 页面内容超出时，只在组件内部滚动，不把滚动压力传给 `body`。
- 不依赖把浏览器缩到 `80%` 才能完整看到布局。
- 双栏/多栏页面在空间不足时优先避免覆盖，再退化为单列或组件内滚动。

## 当前实现事实

- 根壳子 `src/App.vue` 当前保留 `body { overflow-x: auto; overflow-y: auto; }`，浏览器层仍可承担主滚动。
- 通用布局样式主要在 `src/style/workbench-density.css`，提供了：
  - `.workbench-page`
  - `.workbench-body`
  - `.workbench-panel`
  - `.workbench-table-wrap`
- 新页面多数复用上述类，但仍各自设置 `height / min-height / overflow / grid-template-columns`。
- 旧页面与组件页（例如 `FuturesControl`、`StockPools`、`StockCjsd`）已经有单独 shell，但和新页面没有统一约束。
- 现有页面问题主要来自三类：
  - `body` 仍可滚动，页面一旦高度估算不准就直接退化成整页滚动。
  - 页面/面板混用 `overflow: hidden/auto/visible`，滚动责任不清晰。
  - 双栏/表格布局对最小宽高假设过强，`min-width: 0`、`min-height: 0` 不完整，导致撑破或互相覆盖。

## 设计原则

### 1. 统一 viewport shell

- 根层锁定浏览器 viewport。
- 浏览器 `body` 不再承担主内容滚动。
- 路由页自己承担剩余高度分配。

### 2. 统一滚动责任

每个页面都按三层分工：

- page shell：整页容器，占满 viewport，`overflow: hidden`
- page body：除头部外的剩余空间，负责布局分配，默认不直接向浏览器泄露滚动
- panel/table/ledger wrap：真正承载长列表和大表格滚动

### 3. 统一最小尺寸约束

所有 flex/grid 父子关系补齐：

- `min-height: 0`
- `min-width: 0`

避免默认最小内容尺寸把父容器撑爆。

### 4. 统一退化策略

- 优先减少空白、压缩非关键间距。
- 空间仍不足时，优先让局部列表滚动。
- 双栏不足时提前切单列，不允许继续横向挤压到遮挡。
- 不再依赖硬编码 `calc(100vh - xxx)` 维持结构。

## 方案

### 根层改造

更新 `src/App.vue`：

- `html/body/#app/.app-shell` 使用 `height: 100%`
- `body` 改为 `overflow: hidden`
- `.app-shell` 改为 viewport shell，`min-height/height: 100vh/100dvh`

### 通用样式重构

更新 `src/style/workbench-density.css`：

- `.workbench-page` 从“最小高度页面”改成“固定 viewport shell”
- `.workbench-body` 从“默认可滚动”改成“默认布局容器”
- 新增通用类，减少页面各自重复实现：
  - 例如 `workbench-body--scroll`
  - 例如 `workbench-panel--scroll`
  - 例如 `workbench-stack--scroll`
  - 例如 `workbench-grid-fill`

### 页面迁移策略

按页面类型分三组迁移：

#### A. 已使用 workbench shell 的复杂工作台

- `DailyScreening.vue`
- `OrderManagement.vue`
- `PositionManagement.vue`
- `SubjectManagement.vue`
- `SystemSettings.vue`
- `TpslManagement.vue`
- `RuntimeObservability.vue`
- `GanttShouban30Phase1.vue`
- `GanttUnified.vue`
- `GanttUnifiedStocks.vue`

处理方式：

- 移除页面级 `overflow: auto` 作为默认出口
- 明确每个主 grid / stack 的填充关系
- 把表格/ledger/detail 区变成真正的内部滚动容器

#### B. 图表/旧页面

- `FuturesControl.vue`
- `StockControl.vue`
- `StockPools.vue`
- `StockCjsd.vue`
- `KlineSlim.vue`

处理方式：

- 保留现有壳子，但收口到统一 viewport 规则
- 避免旧页面继续依赖浏览器滚动

#### C. 自定义视觉页

- `SystemSettings.vue`

处理方式：

- 保留当前视觉设计
- 仅改布局骨架，不改变信息架构和视觉方向

## 验收

### 人工验收

在浏览器 `1920x1080`、缩放 `100%` 下：

- 工作台页面无浏览器纵向滚动条
- 页面头部、主工具条、主列表、详情区全部可用
- 任何长列表仅在自身区域滚动
- 不出现相互覆盖、裁切后只能缩放浏览器解决的问题

### 自动化验收

补充/更新源码级布局测试，至少覆盖：

- `App.vue` 与 `workbench-density.css` 不再允许 `body` 级主滚动
- 新工作台页面必须使用 viewport shell
- 复杂页面的主布局容器不再依赖页面级 `overflow: auto`
- 列表/ledger/table 容器具备显式内部滚动容器
- 关键断点下双栏页面会提前退化

## 非目标

- 不在本次重构中改变页面业务交互、接口协议或数据结构。
- 不引入新的设计系统或视觉主题替换。
- 不为移动端重新设计完整交互，只保证当前页面在较小宽度下不破版。
