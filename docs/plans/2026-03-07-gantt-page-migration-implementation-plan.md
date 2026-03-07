# 甘特图页面迁移实施计划

> 执行阶段按 `executing-plans` 逐任务落地，先补后端契约，再迁前端页面。

**目标**：在目标仓库恢复“板块趋势”统一页与入口，保留板块/个股甘特矩阵、板块名称外链、tooltip 理由等核心能力，并基于统一 `/api/gantt/*` 契约完成迁移。

**架构约束**：

- 只基于 RFC 0006 的盘后读模型工作，不恢复盘中 snapshot。
- 继续使用统一 `provider + plate_key` 模型，不恢复旧 provider 专属接口。
- 板块理由只能来自 `plate_reason_daily`，缺失即构建失败。
- 页面只保留已确认的功能，不迁移搜索和 BLK 导出。

**技术栈**：Vue 2、Vue Router、Axios、ECharts、Flask、PyMongo、pytest

---

### 任务 1：补齐板块理由读模型投影

**文件**

- 修改：`freshquant/data/gantt_readmodel.py`
- 测试：`freshquant/tests/test_gantt_readmodel.py`

**实施点**

1. 为 `persist_gantt_daily_for_date()` 增加针对 `plate_reason_daily` 的同日 join。
2. 将 `reason_text`、`reason_ref` 写入 `gantt_plate_daily`。
3. 保持 `gantt_stock_daily` 逻辑不变。
4. 如果某个进入 `gantt_plate_daily` 的板块没有对应理由，直接抛错失败。

**验证**

- 先补失败用例：
  - 板块理由被写入 `gantt_plate_daily`
  - 缺少板块理由时构建失败
- 运行：`pytest freshquant/tests/test_gantt_readmodel.py -q`

### 任务 2：扩展 `/api/gantt/plates` 返回板块理由映射

**文件**

- 修改：`freshquant/rear/gantt/routes.py`
- 测试：`freshquant/tests/test_gantt_routes.py`

**实施点**

1. 保持 `data.dates`、`data.y_axis`、`data.series` 结构不变。
2. 新增 `meta.reason_map`，键为 `YYYY-MM-DD|plate_key`。
3. `meta.reason_map` 的值至少包含：
   - `reason_text`
   - `reason_ref`

**验证**

- 补充失败用例：
  - `/api/gantt/plates` 返回 `meta.reason_map`
  - 理由映射与 `dates/y_axis` 可正确关联
- 运行：`pytest freshquant/tests/test_gantt_routes.py -q`

### 任务 3：新增前端统一 API、路由和导航入口

**文件**

- 新增：`morningglory/fqwebui/src/api/ganttApi.js`
- 修改：`morningglory/fqwebui/src/router/index.js`
- 修改：`morningglory/fqwebui/src/views/MyHeader.vue`

**实施点**

1. 新增统一 API：
   - `getGanttPlates({ provider, days, endDate })`
   - `getGanttStocks({ provider, plateKey, days, endDate })`
2. 新增路由：
   - `/gantt`
   - `/gantt/stocks/:plateKey`
3. 在导航栏新增按钮“板块趋势”，默认跳 `/gantt?p=xgb`。

**验证**

- 本地路由可解析到新页面。
- 导航点击后 URL 正确。

### 任务 4：迁移统一页、下钻页和图表组件

**文件**

- 新增：`morningglory/fqwebui/src/views/GanttUnified.vue`
- 新增：`morningglory/fqwebui/src/views/GanttUnifiedStocks.vue`
- 新增：`morningglory/fqwebui/src/views/components/GanttHistory.vue`

**实施点**

1. 以旧分支 `GanttUnified.vue`、`GanttUnifiedStocks.vue`、`XgbHistoryGantt.vue` 为基础迁移。
2. 将底层组件改名为 `GanttHistory.vue`，消除 XGB 专用命名。
3. 统一改为调用 `src/api/ganttApi.js`。
4. 将旧 `plate_id` 逻辑替换为 `plate_key`。
5. 删除：
   - 搜索抽屉
   - “加入近期涨停池”
   - 任何旧 `/api/xgb/history/gantt/*`、`/api/jygs/history/gantt/*` 依赖
6. 板块 tooltip 从 `meta.reason_map` 取理由。
7. 个股 tooltip 继续使用 `series[4]` 的 `stock_reason`。
8. 板块热门标的展示调整为代码列表。
9. 保留板块名称外链：
   - XGB -> `https://xuangutong.com.cn/theme/<plateKey>`
   - JYGS -> `https://www.jiuyangongshe.com/action/<hoveredDate>`

**验证**

- `/gantt?p=xgb`
- `/gantt?p=jygs`
- `/gantt/stocks/:plateKey?p=xgb`
- `/gantt/stocks/:plateKey?p=jygs`

### 任务 5：前后端联调与构建验证

**命令**

- 后端：`pytest freshquant/tests/test_gantt_readmodel.py freshquant/tests/test_gantt_routes.py -q`
- 前端：`npm run build`

**手工验收**

1. 进入 `/gantt?p=xgb`，hover 板块格子可看到板块热门理由。
2. 进入 `/gantt?p=jygs`，hover 板块格子可看到板块热门理由。
3. 点击板块格子进入个股页。
4. hover 个股格子可看到标的热门理由。
5. 点击左侧板块名称可跳到对应数据源页面。
6. 回看窗口切换、回到最新、回到顶部均可用。

### 任务 6：治理收尾

**文件**

- 修改：`docs/migration/progress.md`
- 视落地内容决定是否修改：`docs/migration/breaking-changes.md`

**实施点**

1. RFC 状态随阶段推进更新：
   - Draft
   - Review
   - Approved
   - Implementing
   - Done
2. 若实现中出现实际 breaking changes，同提交登记到 `breaking-changes.md`。
3. 在实现完成同一提交中更新进度表备注、风险与下一步。
