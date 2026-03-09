# Gantt Shouban30 默认缠论筛选设计

## 背景

当前 `/gantt/shouban30` 页面已经具备首期三栏结构：

- 左栏：首板板块
- 中栏：热点标的
- 右栏：历史全量热门理由

页面还支持 `xgb / jygs / agg` 三种视图，以及 `30 / 45 / 60 / 90` 标的窗口切换。但当前展示仍是“原始热门标的”视角，尚未叠加旧分支中常用的默认缠论筛选，也没有过滤部分明确不希望展示的板块。

本次需求只聚焦当前页面优化，不迁移旧分支整套 `chanlun calc / cache / filter / blk / pool / watchlist` 闭环。缠论结构必须复用当前分支已经存在的后端接口，而不是把旧分支的 SSE 与缓存链路搬回目标仓库。

## 目标

- 在 `/gantt/shouban30` 页面过滤掉板块黑名单：
  - `其他`
  - `公告`
  - `ST股`
  - `ST板块`
- 在“30天首板热门标的”基础上，默认叠加 30 分钟缠论筛选。
- 左栏板块数量改为“通过默认缠论筛选后的标的数”。
- 中栏只展示当前板块下通过默认缠论筛选的标的。
- `agg` 视图继续支持跨来源聚合，但聚合输入改为“通过筛选后的标的集”。
- 保持右栏“历史全量热门理由”语义不变。

## 非目标

- 不新增新的公共 Flask API。
- 不新增新的 Mongo 读模型或 Dagster 盘后快照字段。
- 不迁移旧分支的 `chanlun/calc/stream`、`chanlun/filter`、`sync_blk`、`pool`、`watchlist`。
- 不把右栏详情改造成缠论详情面板。
- 不修改现有 `/api/gantt/shouban30/*` 与 `/api/gantt/stocks/reasons` 的对外契约。

## 当前事实

### 页面与前端数据流

- 页面位于 `morningglory/fqwebui/src/views/GanttShouban30Phase1.vue`。
- 左栏板块和中栏标的来自：
  - `GET /api/gantt/shouban30/plates`
  - `GET /api/gantt/shouban30/stocks`
- 右栏详情来自：
  - `GET /api/gantt/stocks/reasons`
- `agg` 视图由前端 `morningglory/fqwebui/src/views/shouban30Aggregation.mjs` 本地聚合完成，不存在后端聚合接口。

### 当前分支可复用的缠论结构接口

- 当前分支已经有：
  - `GET /api/stock_data_chanlun_structure`
- 服务实现位于：
  - `freshquant/chanlun_structure_service.py`
- 返回结构中已包含：
  - `structure.higher_segment`
  - `structure.segment`
  - `structure.bi`
- 每一级都已有：
  - `start_price`
  - `end_price`
  - `price_change_pct`

这意味着当前页面可以直接基于现有接口完成 30 分钟默认筛选，无需引入旧分支的 fullcalc cache/filter 服务。

### 旧分支相关行为

- 旧分支 `GanttShouban30.vue` 的“默认筛选 + 分组/板块切换”是基于一组已计算结果做前端展示控制。
- 旧分支还存在 `XGB_EXCLUDE_PLATE_NAMES / JYGS_EXCLUDE_PLATE_NAMES`，其中明确排除了 `ST股`、`ST板块`、`其他`、`公告`。
- 本次只复用其中两类经验：
  - 黑名单板块过滤
  - 通过结果按板块分组显示

## 方案选择

### 方案 A：前端本地筛选，复用现有缠论结构接口

- 页面先拉现有 `shouban30` 列表。
- 对黑名单过滤后的候选标的去重后，逐个请求 `/api/stock_data_chanlun_structure?period=30m`。
- 前端本地判定是否通过，再把结果重新映射回左栏/中栏/聚合视图。

优点：

- 不新增公共 API。
- 不改读模型与 Dagster。
- 严格复用当前分支已有后端能力。
- 与本次“页面优化”范围一致。

缺点：

- 页面请求量增加，需要并发控制和缓存。

### 方案 B：新增后端聚合筛选接口

- 新增 `/api/gantt/shouban30/...` 的默认筛选路由。
- 服务端内部再调用 `get_chanlun_structure()` 并返回筛选后的板块/标的结果。

优点：

- 前端逻辑更薄。

缺点：

- 新增公共接口，超出本轮最小必要变更。
- 需要额外文档与更严格的接口治理。

### 方案 C：盘后固化缠论筛选结果

- 在 Dagster 盘后任务中直接把 30m 缠论筛选结果落入读模型。
- 页面只读取现成快照。

优点：

- 页面最快。

缺点：

- 改动面最大。
- 需要扩展读模型和调度语义，不适合本轮。

**结论：采用方案 A。**

## 最终设计

### 1. 黑名单板块过滤

页面在接收到 `xgb / jygs` 板块列表后，先按 `plate_name` 过滤以下板块：

- `其他`
- `公告`
- `ST股`
- `ST板块`

过滤发生在当前页的数据装配层，不修改现有后端查询接口和 Mongo 读模型。

### 2. 默认缠论筛选规则

筛选周期固定为 `30m`，请求参数中的 `endDate` 取当前页解析后的 `resolvedAsOfDate`。

单个标的要被判定为“通过默认筛选”，必须同时满足：

- `higher_segment.end_price / higher_segment.start_price <= 3.0`
- `segment.end_price / segment.start_price <= 3.0`
- `bi.price_change_pct <= 30`

说明：

- “3 倍”按价格倍数理解，即 `end_price / start_price <= 3.0`。
- “笔 30%”按当前接口现成字段 `price_change_pct <= 30` 判断。
- 任一结构缺失、接口返回 `ok=false`、请求异常、价格字段不可用，统一视为“不通过”。

### 3. 前端数据流

页面查询链路调整为：

1. 拉取 `xgb / jygs` 两侧原始板块列表。
2. 对板块先做黑名单过滤。
3. 拉取过滤后板块对应的原始标的列表。
4. 对候选标的按 `code6 + resolvedAsOfDate + 30m` 去重。
5. 对去重后的标的集合请求 `/api/stock_data_chanlun_structure`。
6. 生成本地 `chanlun pass / fail / unavailable` 结果缓存。
7. 用“通过筛选后的标的集”重建：
   - 左栏板块计数
   - 中栏标的列表
   - `agg` 聚合视图

### 4. 缓存与并发控制

- 前端本地维护结构请求缓存，键为：
  - `code6 + as_of_date + period(30m)`
- 同一股票即使同时出现在多个板块或 `agg` 视图，也只请求一次。
- 结构请求必须设置固定并发上限，避免对后端产生瞬时洪峰。
- 当用户切换以下任一维度时，上一轮未完成请求结果必须失效：
  - `provider`
  - `stock_window_days`
  - `as_of_date`

### 5. 左栏与中栏展示规则

#### 左栏“首板板块”

- 只显示“至少有 1 个通过默认缠论筛选标的”的板块。
- 原 `stocks_count` 列改为“通过默认筛选后的唯一标的数”。
- 列标题也要改成明确文案，避免继续被理解为原始热门标的数。
- 排序继续沿用当前页既有规则：
  - `last_up_date desc`
  - `appear_days_30 desc`
  - `plate_name asc`

#### 中栏“热点标的”

- 只展示当前板块下通过默认缠论筛选的标的。
- 建议新增一列简短缠论摘要，至少展示：
  - 高级段倍数
  - 段倍数
  - 笔涨幅%
- 这样用户可以直接看到每只股票是如何满足默认筛选的。

### 6. `agg` 视图规则

- `agg` 视图继续复用现有同名板块聚合逻辑。
- 但参与聚合的输入不再是“原始热点标的全集”，而是“通过默认缠论筛选后的标的集”。
- 聚合后的板块数量和标的数量都基于通过集重算。
- 同一 `code6` 在聚合视图中仍按现有逻辑去重。

### 7. 右栏详情

- 右栏仍然使用 `/api/gantt/stocks/reasons`。
- 语义保持为“历史全量热门理由”。
- 不混入缠论结构详情，避免一个面板承担两套业务语义。

### 8. 失败语义与页面统计

- 缠论结构接口异常时，不让异常项进入默认通过列表。
- 页面应额外展示最小统计信息，至少包括：
  - 原始候选总数
  - 默认筛选通过数
  - 默认筛选失败或不可用数
- 这样可以区分：
  - 没有股票通过
  - 后端结构能力未返回结果

## 涉及文件

主要改动预期集中在前端：

- `morningglory/fqwebui/src/views/GanttShouban30Phase1.vue`
- `morningglory/fqwebui/src/views/shouban30Aggregation.mjs`
- `morningglory/fqwebui/src/api/ganttShouban30.js`

复用但不修改契约的后端入口：

- `freshquant/rear/stock/routes.py`
- `freshquant/chanlun_structure_service.py`

## 测试策略

### 前端测试

- 黑名单板块过滤：
  - `其他 / 公告 / ST股 / ST板块` 不再出现在 `xgb / jygs / agg`
- 默认缠论筛选判定：
  - 高级段倍数
  - 段倍数
  - 笔涨幅%
- 板块通过数重算：
  - 左栏数量等于通过筛选后的唯一 `code6` 数
- `agg` 视图：
  - 同名板块聚合
  - 同一 `code6` 去重
  - 通过数按通过集统计

### 现有后端测试复用

- 继续依赖当前已有的：
  - `test_chanlun_structure_service.py`
  - `test_stock_data_chanlun_structure_route.py`

不修改其接口契约，只在前端消费层新增测试。

## 验收标准

- `xgb / jygs / agg` 三个视图都不再出现：
  - `其他`
  - `公告`
  - `ST股`
  - `ST板块`
- 左栏板块数量等于该板块下通过以下条件的唯一标的数：
  - 30m 高级段倍数 `<= 3.0`
  - 30m 段倍数 `<= 3.0`
  - 30m 笔涨幅 `<= 30`
- 中栏只显示通过默认缠论筛选的标的。
- 同一股票在同一 `as_of_date` 下只发起一次 30m 结构请求。
- 切换 `provider / stock_window_days / as_of_date` 后，不出现旧结果残留。
- 右栏详情仍能正常显示历史全量热门理由。

## 风险

- 页面会新增一批结构请求，若并发控制不足，可能拖慢交互或给后端带来峰值压力。
- 结构接口对失败项一律判“不通过”，会让“后端不可用”表现成“通过数减少”，因此必须补充页面统计。
- `agg` 视图继续按同名板块聚合，这一业务假设不覆盖“同义不同名”的来源差异；本轮接受这一边界。
