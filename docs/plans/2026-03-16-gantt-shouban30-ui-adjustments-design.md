# /gantt/shouban30 工作区交互优化设计

## 背景

`/gantt/shouban30` 当前页面已经支持热点板块、热点标的、标的详情，以及 `pre_pools / stock_pools` 工作区操作，但仍有三个交互缺口：

- 工作区里点击标的后，右侧“标的详情”不会联动刷新。
- 工作区表格的“操作”列位于最右侧，常用动作与标的名称割裂。
- 条件筛选只影响当前页面展示，还不能把“多条件筛选后的当前结果”批量追加到 `pre_pools`。

## 目标

- 让工作区中的标的和中间热点标的一样，都能驱动“标的详情”展示。
- 优化工作区表格的信息密度，把“操作”列移动到“名称”列后。
- 在“筛选”按钮后增加“全部加入 pre_pools”，把当前多条件筛选结果按页面顺序追加到 `pre_pools`。

## 非目标

- 不新增后端接口。
- 不改变 `pre_pools` 现有 append 语义。
- 不重构整页状态管理，也不拆分新的页面模块。

## 方案

### 1. 工作区选中也联动标的详情

页面继续复用现有 `selectedStockCode6 -> loadStockReasons(code6)` 这一条详情加载链路，不新增第二套详情状态。

做法是把工作区行点击也接到同一个选中 `code6`，并引入一个“当前详情上下文”：

- 如果选中来源是热点标的，则标题、副标题继续优先使用中间“热点标的”数据。
- 如果选中来源是工作区，则从工作区行构造一个轻量 `selectedStockDetailContext`，用于详情标题显示 `code6 / name / provider / plate_name`。

这样可以做到：

- 热点标的和工作区共用同一套详情请求。
- 详情表不依赖当前热点列表一定包含该 `code6`。
- 页面在切换板块、切换窗口时，仍能保持当前既有的清空与回退逻辑。

### 2. 工作区操作列前移

工作区表格列顺序调整为：

`代码 -> 名称 -> 操作 -> 来源 -> 板块 -> 分类`

只改前端表格声明，不改数据结构。

### 3. “全部加入 pre_pools” 复用现有 append 语义

当前仓库已经有 `buildCurrentFilterReplacePrePoolPayload(...)`，可以根据“当前页面筛选后的板块 + 对应筛选后的标的”生成批量 payload。

本次只做两件事：

- 在“筛选”按钮后增加“全部加入 pre_pools”按钮。
- 点击后调用现有 `appendShouban30PrePool(payload)`。

语义保持为：

- 以当前多条件筛选后的页面顺序生成 `items`
- 后端 append 时继续按 `code6` 去重
- 已存在标的不覆盖、不重排

如果当前筛选结果为空，则只弹出提示，不发请求。

## 影响文件

- `morningglory/fqwebui/src/views/GanttShouban30Phase1.vue`
- `morningglory/fqwebui/src/views/shouban30PoolWorkspace.mjs`
- `morningglory/fqwebui/src/views/shouban30PoolWorkspace.test.mjs`

## 测试策略

- 先补 `shouban30PoolWorkspace.test.mjs`，锁定“当前筛选结果批量加入”的 payload 顺序、去重和筛选上下文。
- 实现页面改动后运行 `npm run test:shouban30`。
- 追加运行 `npm run build`，确认页面编译通过。

## 部署影响

本次仅改 `morningglory/fqwebui/**` 前端页面逻辑，按仓库规则需要重新构建并部署 Web UI。
