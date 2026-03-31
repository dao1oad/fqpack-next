# 前端 Workbench 风格

## 职责

本页记录 FreshQuant 当前业务页的前端组织方式真值。它不是设计提案，而是当前代码已经采用的页面语法：以 `/gantt/shouban30` 的 workbench 页面壳和 `/runtime-observability` 的 dense ledger 为来源，把高密度工作台风格统一到其余业务管理页。

## 当前采用范围

当前默认页与来源页：

- `/runtime-observability`（默认首页）
- `/gantt`
- `/gantt/shouban30`
- `/runtime-observability`

当前已采用统一 workbench 风格或共享 page-shell contract 的业务页：

- `/daily-screening`
- `/gantt`
- `/gantt/stocks/:plateKey`
- `/gantt/shouban30`
- `/stock-control`
- `/order-management`
- `/position-management`
- `/runtime-observability`
- `/subject-management`
- `/system-settings`
- `/tpsl`
- `/kline-big`
- `/kline-slim`
- `/multi-period`

补充事实：

- `/runtime-observability` 当前既是默认首页，也是主工作台页面 contract 的模板页；`page title / page meta / summary row / page-level alert / sidebar|ledger|detail panel` 这套页面语法优先以它为真值
- `/stock-control`、`/daily-screening`、`/gantt`、`/gantt/stocks/:plateKey`、`/gantt/shouban30`、`/order-management`、`/position-management`、`/subject-management`、`/system-settings`、`/tpsl` 当前都已经直接消费共享 `WorkbenchPage / WorkbenchToolbar / WorkbenchSummaryRow / WorkbenchPanel` primitives
- `/system-settings` 当前把顶部摘要与 dense ledger 行内状态统一收口到共享 `StatusChip`
- `/system-settings` 当前把每列拆成固定列头和独立滚动 body；每个 section 的标题摘要与 ledger 表头都改成静态头部，滚动时不再出现 sticky 叠层遮挡首行
- `/daily-screening`、`/position-management`、`/runtime-observability` 与 `/stock-control` 当前也已经把 dense ledger 改成“静态表头 + 独立 viewport”结构；表头不再使用 sticky 叠层，纵向滚动只发生在 viewport 内
- `/daily-screening` 的交集列表和历史热门理由在桌面端会压平横向滚动条；当视口收窄到单列布局时，ledger 根容器会恢复横向滚动，避免列内容被裁切
- `/gantt`、`/gantt/stocks/:plateKey`、`/gantt/shouban30` 当前已经补齐研究页 contract：统一页头 title/meta、summary row、页面级 `workbench-alert`、主 panel header 语法，同时继续保留 provider switch / drill-down / workspace 工作流
- `/kline-big`、`/kline-slim`、`/multi-period` 当前至少统一接入共享 `page-shell contract`：根容器显式带 `workbench-page`，并复用同一套视口高度、背景与滚动兜底语义
- `/kline-slim` 当前保留旧版单行工具栏与暗色图表节奏，不再额外挂载全局 `MyHeader` 或白底 workbench 标题/告警带；图表、chanlun 与 controller 仍保持专用实现
- `/futures-control`、`/stock-pools`、`/stock-cjsd` 当前已经下线，不再作为活跃 workbench 页面维护

## 页面壳

当前统一页面壳是：

`MyHeader -> workbench-body -> toolbar/panel -> 列表/详情/操作区`

对于图表页或仍在保留历史内部结构的页面，最低统一要求是：

- 根容器显式接入 `workbench-page`
- 主内容区接入 `workbench-body` 或等价的页面级滚动兜底语义
- 不再各自维护另一套视口高度和背景 contract

当前规则：

- `MyHeader` 顶部导航由 `src/router/pageMeta.mjs` 的元数据分组驱动，不在页面里硬编码按钮清单
- 页面背景使用中性浅灰白底。
- 标题区不再使用大 hero、大渐变、大面积主题背景。
- 页面主内容由多个白底 panel 组成，间距默认紧凑。
- 桌面工作区默认按 `3440x1440` 优先适配。
- 根容器使用 `min-height: 100vh / 100dvh` 的视口壳，而不是固定高度裁切。
- 浏览器窗口允许承担页面级滚动兜底；当页面在较窄有效宽度下无法继续并排时，页面可以自然下推和滚动。
- 列表、表格、详情区仍优先保留局部滚动，但不再依赖外层 `overflow: hidden` 强行裁切页面。

## 标题区

当前标题区固定承载：

- 页面标题
- 当前上下文 meta
- 主操作按钮
- 当前筛选或摘要条

标题区不再承载 marketing copy 式大段描述，也不再用大号统计卡抢占首屏空间。

## 面板

当前业务页统一使用以下面板语法：

- 白底
- 浅灰边框
- 小圆角
- 紧凑 padding
- 标题、次级说明、右侧动作分区

面板内优先使用：

- 摘要条
- 标签组
- dense ledger
- 紧凑列表

## 列表与表格

当前默认优先高密度列表和表格，而不是大卡片堆叠。

当前规则：

- 单屏尽量同时看到筛选、摘要、主列表、详情
- 选中态统一用浅蓝高亮
- 操作优先使用 link button 或小按钮
- 表格区域优先保留内部滚动，但页面外层必须允许在必要时继续滚动
- dense ledger 的固定表头必须放在独立滚动 viewport 之外；禁止再用 sticky 表头叠在行列表上
- 浏览器回归当前已经覆盖 `/daily-screening`、`/position-management`、`/runtime-observability`、`/stock-control` 的 ledger 几何关系，验收口径是“表头下缘不得侵入真实 viewport 起点”
- 跨业务页的日期时间字段当前统一按北京时间（`Asia/Shanghai`）展示，并固定保留到秒；后端返回 UTC 时间时由前端负责换算后再显示

## 标签与摘要

当前摘要和状态信息统一用行内标签表达：

- 统计摘要标签
- 状态标签
- 筛选标签
- 上下文 meta 标签

当前落地事实：

- `/runtime-observability` 已经用共享 `StatusChip` 承担只读摘要 badge 与行内状态 badge
- `/position-management` 已经用共享 `StatusChip` 承担顶部摘要、规则矩阵结果、右栏一致性/门禁和最近决策结果
- `/order-management` 已经用共享 `StatusChip` 承担筛选摘要、订单摘要条和详情 identifier chip
- `/tpsl` 已经用共享 `StatusChip` 承担顶部摘要、symbol 导航卡片 badge 与统一历史明细标签
- `/subject-management` 已经用共享 `StatusChip` 承担顶部摘要条与右侧编辑区摘要 chip
- `/daily-screening` 已经用共享 `StatusChip` 承担工作台说明标签、顶部摘要条、详情数值摘要与命中条件 chip
- `/kline-slim` 已经用共享 `StatusChip` 承担工具栏状态条、标的设置/画线编辑摘要与缠论结构摘要
- `/system-settings` 已经用共享 `StatusChip` 承担顶部 Bootstrap/Mongo 摘要与 dense ledger 的生效/来源/状态标签
- `/gantt/shouban30` 已经用共享 `StatusChip` 承担顶部日期/窗口摘要和四个主面板的计数 badge
- 页面本地只允许保留尺寸与布局约束，不再在单页里重复维护成功/警告/危险配色类

状态色只允许做局部强调：

- 主交互色：蓝色
- 成功：绿色
- 警告：黄色/橙色
- 危险：红色

不允许再为每个业务页维持独立主题色系统。

## 页面组织规则

当前业务页统一遵守：

- 不删信息，只调整组织形式
- 优先把重复说明压缩成 meta 或 summary row
- 优先把统计卡压缩成摘要条
- 详情优先与主列表同屏并排，而不是增加跳转层级
- 响应式以面板堆叠和断点提前降级为主，不删字段
- 顶部导航按钮打开浏览器新标签页；标签标题优先使用对应按钮文案，并由导航元数据自动注入 `tabTitle`

## 禁止项

当前业务页默认避免：

- 大 hero
- 强主题背景
- 低密度大卡片优先布局
- 为视觉装饰牺牲可见信息量
- 同一语义在不同页面使用完全不同的标签/摘要表达
