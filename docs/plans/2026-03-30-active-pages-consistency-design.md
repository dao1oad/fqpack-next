# Active Pages Consistency Design

**日期**: 2026-03-30

## 目标

只围绕 `MyHeader` 中仍然保留的主导航页面做一致性治理，不再继续为废弃页面投入统一化成本。

本轮设计确认以下事实：

- 默认首页改为 `/runtime-observability`
- `RuntimeObservability.vue` 作为主工作台页面模板
- `StockControl.vue` 并入主工作台页面体系，不再单列成特殊类别
- `期货 / 股票池 / 超级赛道` 三个页面从主导航下线
- 若安全，可删除这三个页面对应的路由页面文件与测试约束

## 页面范围

### 保留并纳入一致性治理

- `RuntimeObservability.vue`
- `KlineSlim.vue`
- `OrderManagement.vue`
- `PositionManagement.vue`
- `SubjectManagement.vue`
- `TpslManagement.vue`
- `SystemSettings.vue`
- `DailyScreening.vue`
- `GanttUnified.vue`
- `GanttUnifiedStocks.vue`
- `GanttShouban30Phase1.vue`
- `StockControl.vue`

### 下线并移出治理范围

- `FuturesControl.vue`
- `FuturePositionList.vue`
- `components/StockPools.vue`
- `components/StockCjsd.vue`

## 删除边界

### 可以删除的页面层对象

- `/futures-control` 路由及其页面实现链
- `/stock-pools` 路由及其页面实现链
- `/stock-cjsd` 路由及其页面实现链
- 与以上三页直接绑定的页面级测试、bundle 断言、导航元信息

### 不能一起删除的业务能力

- `stock pool` 业务 API 与操作能力
- `DailyScreening.vue` 里的 `stock pool` 写入动作
- `GanttShouban30Phase1.vue` 里的 `stock pool` 工作区能力
- `klineSlimController.mjs` 中对 `stock pool` 数据的消费

结论：本轮删除的是“独立页面入口”，不是“stock pool 业务域”。

## 信息架构

### 默认页面

- 根路由 `/` 重定向到 `/runtime-observability`
- 顶部导航中的“运行观测”成为默认进入点

### 主工作台页面 contract

所有保留主导航页默认遵守以下结构：

1. `MyHeader`
2. `WorkbenchPage`
3. `WorkbenchToolbar`
4. 页面级摘要区
5. 主内容区
6. 页面级错误态与空态

### 焦点图表页面 contract

`KlineSlim.vue` 保留图表焦点页特性，但仍必须共享：

- 顶部导航
- 统一标题与状态 chip 语法
- 统一错误态/空态表达
- 统一滚动与浮层层级规则

## 一致性治理标准

### 视觉与页壳

- 所有保留主导航页统一使用 `WorkbenchPage`
- 页面标题、副标题、主要刷新动作都放在 `WorkbenchToolbar`
- 页面不依赖浏览器主滚动，优先使用 panel 内部滚动

### 状态反馈

- 页面级错误统一使用 `el-alert`
- 空态统一使用 `workbench-empty` 或 `el-empty`
- loading 命名与展示方式统一
- 分页与“加载更多”策略按页面家族统一，而不是每页自定义

### 代码组织

- 路由页只放在 `src/views/`
- 页面元信息只从 `router/pageMeta.mjs` 维护
- 页面 contract 用测试锁住，而不是靠约定维持

## 页面家族

### 主工作台页

- `RuntimeObservability`
- `OrderManagement`
- `PositionManagement`
- `SubjectManagement`
- `TpslManagement`
- `SystemSettings`
- `DailyScreening`
- `GanttUnified`
- `GanttUnifiedStocks`
- `GanttShouban30Phase1`
- `StockControl`

### 焦点页

- `KlineSlim`

## 风险与规避

### 风险 1：删除页面后测试仍然绑定旧页面

规避：

- 同步清理 `pageMeta.test.mjs`
- 同步清理 `legacy-route-shells.test.mjs`
- 同步清理 `workbenchDesignSystem.test.mjs`
- 同步清理 `build-budget.test.mjs`

### 风险 2：误删 stock pool 业务能力

规避：

- 只删独立页面入口，不删 `stockApi` 与业务动作
- 保留 `DailyScreening`、`GanttShouban30Phase1`、`KlineSlim` 中的 stock pool 交互

### 风险 3：默认页切换后文档与导航描述失真

规避：

- 同步更新 `docs/current/**`
- 同步更新 header/nav 元信息测试

## 成功标准

- `MyHeader` 中不再出现废弃页面入口
- `/` 默认进入 `RuntimeObservability`
- 保留页面能明显看出属于同一套工作台系统
- `KlineSlim` 作为唯一焦点页变体，仍然共享全站统一页面语言
