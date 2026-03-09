# 运行观测首页三段式重构设计

- 日期：2026-03-09
- 状态：Design Approved
- 页面范围：`/runtime-observability`
- 设计目标：将运行观测页从“输入查询优先”调整为“异常优先、最近链路优先、组件看板优先”的无输入首页

## 1. 背景

当前运行观测页已经具备：

- `FreshQuant` 实盘核心链路 trace 聚合
- 运行健康卡片
- trace 列表、详情、raw drawer
- `trace_id / request_id / internal_order_id / symbol / component` 输入查询

但当前默认交互是：

1. 先看到 5 个输入框
2. 再看到 trace 表格
3. 最后才进入详情

这个结构更适合“我已经知道要查什么”的排障场景，不适合“我先看看系统刚刚发生了什么”的实盘监控场景。用户当前诉求很明确：不希望依赖手工输入，希望打开页面就能直接看到异常、最近链路和组件状态。

## 2. 目标

本次重构目标：

1. 将运行观测页首页改为无输入主视图。
2. 首页固定按以下顺序展示：
   - 异常优先
   - 最近链路流
   - 组件看板
3. 将现有 5 个输入框降级为“高级筛选”，默认隐藏在抽屉中。
4. 保留现有 trace 详情、raw drawer、异常摘要、组件聚合等能力，不重写后端接口。
5. 保证页面默认行为更接近“监控首页”，而不是“日志查询页”。

## 3. 非目标

本次明确不做：

- 不新增后端 API 契约
- 不重构 `freshquant/runtime_observability/` 后端聚合逻辑
- 不新增新的页面路由
- 不改运行观测事件 schema
- 不修改 trace 详情页的数据结构
- 不新增 URL 深链或分享链接

## 4. 约束

### 4.1 不改变观测写入语义

本次仅改前端展示层，不改变日志旁路写入约束：

- 继续保持“有界队列 + 后台线程 + 队列满丢弃 + 吞异常”
- 绝不让日志模块阻塞下单或主进程

### 4.2 不引入新的查询依赖

当前页面只能依赖已有接口：

- `/api/runtime/health/summary`
- `/api/runtime/traces`
- `/api/runtime/traces/<trace_id>`
- `/api/runtime/raw-files/*`

前端必须在这些接口返回结果上做二次聚合，不新增接口前提下完成首页重排。

## 5. 总体方案

推荐方案：**三段式无输入首页 + 高级筛选抽屉**

首页从上到下固定为 3 段：

1. **异常优先区**
2. **最近链路流**
3. **组件看板**

现有输入框与表格式筛选能力降级为：

- 顶部一个“高级筛选”按钮
- 抽屉内保留原 5 个输入字段
- 高级筛选只在明确排障时使用

这样做的原因：

- 满足“先看问题，再钻细节”的监控习惯
- 保留现有精确查询能力，不丢功能
- 不需要重做后端接口
- 不会把页面再做成两个模式来回切换

## 6. 页面结构

### 6.1 顶部工具行

顶部工具行保留轻量操作，不再直接露出 5 个输入框：

- `刷新`
- `高级筛选`
- `自动刷新`
- `仅异常`

`高级筛选` 打开后显示抽屉，包含现有字段：

- `trace_id`
- `request_id`
- `internal_order_id`
- `symbol`
- `component`

抽屉内保留原有查询和清空动作。

### 6.2 第一段：异常优先区

作用：回答“当前最值得先看的异常链路是什么”。

展示规则：

- 默认展示最近异常链路中的前 `6` 条
- 排序优先级：
  - `failed`
  - `warning`
  - `skipped`
  - 再按 `issue_count`
  - 再按 `total_duration`
  - 再按 `last_ts`

每张异常卡片包含：

- `symbol`
- 首个异常节点
- 最后节点
- `issue_count`
- `total_duration`
- `last_ts`
- 关键 ID 摘要：
  - `trace_id`
  - `request_id`
  - `internal_order_id`
- 一行异常摘要文案

交互：

- 点击整卡：选中该 trace，并展示现有 trace 详情
- 点击 `Raw`：打开 raw drawer 并定位相关记录

空状态：

- 没有异常时显示“当前无异常链路”
- 提供“查看最近链路”按钮，滚动到第二段

### 6.3 第二段：最近链路流

作用：回答“最近系统里发生了什么”。

展示规则：

- 默认展示最近 `20` 条 trace
- 按 `last_ts` 倒序
- 使用链路摘要条，而不是表格作为默认主视图

每条链路流展示：

- 状态灯：`failed / warning / success / skipped`
- 标的 `symbol`
- 简化路径摘要，例如：
  - `guardian -> submit -> broker -> reconcile`
- `last_ts`
- `total_duration`
- `step_count`
- `issue_count`
- 2 到 3 个关键节点标签

交互：

- 点击整条：进入现有 trace 详情
- hover：显示完整 ID 摘要
- 支持“查看更多”，从 `20` 条展开到 `50` 条

### 6.4 第三段：组件看板

作用：回答“哪一段链路整体有问题”。

只覆盖实盘核心组件：

- `xtdata_producer`
- `xtdata_consumer`
- `guardian_strategy`
- `position_gate`
- `order_submit`
- `broker_gateway`
- `puppet_gateway`
- `xt_report_ingest`
- `order_reconcile`
- `tpsl_worker`

组件看板分两层：

1. **组件状态卡**
   - 组件名
   - 当前状态
   - 心跳年龄
   - 最近异常链路数
   - 最近异常节点数
   - 最近一次异常时间
2. **组件异常分布**
   - 展示 `issue_count / trace_count`
   - 用于快速发现当前最不稳定的组件

关键交互：

- 点击组件卡或组件分布项，直接对首页进行组件过滤
- 过滤后联动第一段和第二段
- 页面显示轻量 filter chip，而不是要求用户手输 `component`

## 7. 旧元素的保留与降级

### 7.1 保留

- trace 详情面板
- step inspector
- raw drawer
- 失败摘要与最长耗时节点等详情信息
- 现有 trace 组装和排序基础能力

### 7.2 降级

- 5 个输入框从首页主交互降级为抽屉内高级筛选
- 现有 trace 表格从默认主视图降级为高级视图

### 7.3 不删除

首期不直接删除表格能力，因为它仍对精细排障有价值。主页面改为卡片/链路流优先，但表格保留给高级筛选结果使用。

## 8. 数据与状态流

页面初始化时：

1. 拉取 `health/summary`
2. 拉取 `traces`
3. 前端基于 `traces` 派生：
   - `异常优先卡片`
   - `最近链路流`
   - `组件异常分布`

页面状态拆分为：

- `serverQuery`
  - 高级筛选抽屉内的服务端过滤条件
- `viewFilter`
  - 首页级轻量视图过滤，例如：
    - `onlyIssues`
    - `selectedComponent`
    - `autoRefresh`
    - `recentTraceLimit`
- `selection`
  - 当前选中 trace
  - 当前选中 step

原则：

- 高级筛选影响服务端请求
- 首页交互优先在前端派生数据上完成

## 9. 推荐实现拆分

建议仅修改：

- `morningglory/fqwebui/src/views/RuntimeObservability.vue`
- `morningglory/fqwebui/src/views/runtimeObservability.mjs`
- `morningglory/fqwebui/src/views/runtime-observability.test.mjs`

新增 helper：

- `buildIssuePriorityCards`
- `buildRecentTraceFeed`
- `buildComponentBoard`
- `applyBoardFilter`
- `buildAdvancedQuerySummary`

不新增新的前端路由和 API client 文件。

## 10. 错误处理与空态

首页空数据时：

- 异常区：显示“当前无异常链路”
- 最近链路流：显示“暂无最近链路”
- 组件看板：显示“暂无组件健康数据”

接口失败时：

- 顶部显示统一错误提示
- 保持当前已有数据显示，不直接清空页面
- 用户仍可手动点击刷新

## 11. 测试与验收

首期验收标准：

1. 页面默认首屏不再显示 5 个输入框。
2. 首页从上到下依次为：
   - 异常优先
   - 最近链路流
   - 组件看板
3. 异常区优先展示失败/异常链路，而不是成功链路。
4. 最近链路流默认展示最近 `20` 条。
5. 点击组件看板可联动过滤异常区与最近链路流。
6. 打开高级筛选抽屉后，原有 `trace_id/request_id/internal_order_id/symbol/component` 查询能力不退化。
7. 现有 trace 详情与 raw drawer 继续可用。
8. `node --test src/views/runtime-observability.test.mjs` 通过。
9. `npm run build` 通过。

## 12. 风险

主要风险：

- 当前页面已承载较多详情逻辑，首页重排后状态管理复杂度上升
- 如果不谨慎拆 helper，`RuntimeObservability.vue` 会继续膨胀
- 组件过滤、仅异常、自动刷新三类视图状态容易互相干扰

缓解方式：

- 把新聚合逻辑尽量下沉到 `runtimeObservability.mjs`
- 页面模板只负责展示与事件绑定
- 对新聚合 helper 补纯函数测试，避免把 UI 逻辑埋进模板

## 13. 结论

本次首页重构不改变运行观测的后端能力边界，而是调整默认信息架构：

- 从“先输入再查”
- 改为“先看异常、再看最近、再看组件”

这样既保留排障精度，也让运行观测页真正具备实盘首页价值。
