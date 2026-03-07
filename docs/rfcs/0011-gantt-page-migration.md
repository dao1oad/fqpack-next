# RFC 0011: 甘特图页面迁移与统一板块趋势入口

- **状态**：Done
- **负责人**：Codex
- **评审人**：TBD
- **创建日期**：2026-03-07
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

RFC 0006 已在目标仓库完成 XGB / JYGS 甘特图专题的盘后数据同步、读模型、Dagster 任务和最小查询接口，但前端“板块趋势”页面尚未迁入。当前问题是：

- 导航栏没有“板块趋势”入口。
- 前端没有 `/gantt` 与 `/gantt/stocks/:plateKey` 页面。
- 旧分支页面依赖的旧接口、搜索能力、BLK 导出和盘中 snapshot 注入，在目标仓库均不再成立。
- 用户最关注的“板块热门理由”和“标的热门理由”里，只有标的理由已直接体现在当前 API 契约中；板块理由虽已落在 `plate_reason_daily`，但尚未通过 `/api/gantt/plates` 暴露。

因此需要在不突破 RFC 0006 后端边界的前提下，迁移旧分支统一页主交互，并补齐板块理由的接口暴露。

## 2. 目标（Goals）

- 在 `morningglory/fqwebui` 中恢复“板块趋势”统一入口与页面。
- 统一使用目标仓库 `/api/gantt/plates`、`/api/gantt/stocks`。
- 保留旧统一页的核心交互：
  - XGB / JYGS tabs
  - 板块矩阵
  - 个股矩阵下钻
  - 左侧板块侧栏
  - 板块名称跳转数据源
  - `7/15/30/45/60/90` 天窗口切换
  - tooltip 展示板块热门理由与标的热门理由
- 为板块 tooltip 补齐后端理由契约。

## 3. 非目标（Non-Goals）

- 不迁移“加入近期涨停池”。
- 不迁移“全历史标的异动检索”。
- 不迁移 `GanttShouban30.vue`。
- 不恢复旧 `/api/xgb/history/gantt/*`、`/api/jygs/history/gantt/*`。
- 不恢复盘中 snapshot 注入、WebSocket 或实时刷新。

## 4. 范围（Scope）

**In Scope**

- 新增导航按钮“板块趋势”。
- 新增前端路由 `/gantt` 与 `/gantt/stocks/:plateKey`。
- 迁移旧统一页与下钻页主交互。
- 新增前端统一 API 封装。
- 补齐 `gantt_plate_daily` 的板块理由投影。
- 扩展 `/api/gantt/plates`，返回板块理由映射。
- 新增或修改对应后端、前端测试。

**Out of Scope**

- 搜索抽屉与相关后端接口。
- BLK 导出接口与页面按钮。
- Shouban30 页面迁移。
- 任何盘中数据补充逻辑。

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**

- 以前端统一页承载板块与个股甘特图浏览。
- 以后端读模型承载板块理由，不在前端拼接推导。
- 以统一 `provider + plate_key + trade_date` 作为板块理由关联键。
- 保持旧核心交互体验，但裁剪超出当前后端边界的功能。

**不负责（Must Not）**

- 不把旧分支的附属操作台、搜索、导出能力强行塞回本次迁移。
- 不将个股理由聚合成板块理由 fallback。
- 不为页面迁移重新引入旧 API 面或旧数据库扫描逻辑。

**依赖（Depends On）**

- RFC 0006 已落地的：
  - `plate_reason_daily`
  - `gantt_plate_daily`
  - `gantt_stock_daily`
  - `/api/gantt/*`
  - Dagster 盘后任务
- 旧分支页面代码与交互参考：
  - `D:\fqpack\freshquant\morningglory\fqwebui\src\views\GanttUnified.vue`
  - `D:\fqpack\freshquant\morningglory\fqwebui\src\views\GanttUnifiedStocks.vue`
  - `D:\fqpack\freshquant\morningglory\fqwebui\src\views\components\XgbHistoryGantt.vue`

**禁止依赖（Must Not Depend On）**

- `/api/xgb/history/gantt/*`
- `/api/jygs/history/gantt/*`
- `/api/gantt/search/stock-events`
- `appendPlateHotToJqztBlk` / `appendPlateYidongToJqztBlk`
- 盘中 snapshot 或 WebSocket

## 6. 对外接口（Public API）

### 6.1 前端路由

- `GET /gantt`
  - query：
    - `p=xgb|jygs`
    - `days=7|15|30|45|60|90`
- `GET /gantt/stocks/:plateKey`
  - query：
    - `p=xgb|jygs`
    - `days=7|15|30|45|60|90`
    - `plate_name`
    - `_title`

### 6.2 HTTP API

- `GET /api/gantt/plates`
  - 输入：
    - `provider`
    - `days`
    - 可选 `end_date`
  - 输出：
    - `data.dates`
    - `data.y_axis`
    - `data.series`
    - `meta.reason_map`
- `GET /api/gantt/stocks`
  - 输入：
    - `provider`
    - `plate_key`
    - `days`
    - 可选 `end_date`
  - 输出：
    - 维持当前 `data.dates` / `data.y_axis` / `data.series`
    - `series[4]` 为 `stock_reason`

### 6.3 错误语义

- 板块理由缺失属于数据构建错误，不属于前端兜底场景。
- 若 `provider`、`plate_key` 等参数非法，继续沿用现有 `/api/gantt/*` 错误语义。
- `/api/gantt/plates` 增加 `meta.reason_map` 为向后兼容的扩展字段，不改变已有 `data.series` 结构。

## 7. 数据与配置（Data / Config）

- `gantt_plate_daily` 新增：
  - `reason_text`
  - `reason_ref`
- 数据来源：
  - 按 `provider + plate_key + trade_date` 关联 `plate_reason_daily`
- `/api/gantt/plates` 新增：
  - `meta.reason_map["YYYY-MM-DD|plate_key"] = { reason_text, reason_ref }`
- 不新增新的运行时配置项。

## 8. 破坏性变更（Breaking Changes）

本 RFC 相对目标仓库当前状态新增页面与接口扩展，本身不破坏现有页面；但相对旧分支迁移语义存在以下刻意收敛：

- 不恢复旧 provider 专属甘特接口，统一以 `/api/gantt/*` 为唯一来源。
- 不恢复“加入近期涨停池”。
- 不恢复“全历史标的异动检索”。
- 不恢复盘中 snapshot 注入。
- 板块热门标的展示从对象数组降级为代码列表。

### 影响面

- `morningglory/fqwebui` 新增甘特图入口与页面。
- `freshquant/rear/gantt/routes.py` 增加板块理由返回契约。
- `freshquant/data/gantt_readmodel.py` 增加板块理由投影字段。

### 迁移步骤

1. 审核并通过本 RFC。
2. 在后端补齐板块理由投影和接口返回。
3. 迁移前端统一页与路由。
4. 更新进度表与必要的 breaking changes 记录。

### 回滚方案

- 页面侧：移除导航按钮与新路由。
- 接口侧：回退 `/api/gantt/plates` 的新增 `meta.reason_map` 字段与读模型字段扩展。
- 数据侧：回退 `gantt_plate_daily` 新增字段的写入逻辑。

## 9. 迁移映射（From `D:\fqpack\freshquant`）

- `D:\fqpack\freshquant\morningglory\fqwebui\src\views\MyHeader.vue`
  - 旧导航入口
  - 映射到目标仓库 `morningglory/fqwebui/src/views/MyHeader.vue`
- `D:\fqpack\freshquant\morningglory\fqwebui\src\router\index.js`
  - 旧 `/gantt` 与 `/gantt/stocks/:plateId`
  - 映射到目标仓库 `morningglory/fqwebui/src/router/index.js`
- `D:\fqpack\freshquant\morningglory\fqwebui\src\views\GanttUnified.vue`
  - 旧统一板块页
  - 映射到目标仓库同名页面
- `D:\fqpack\freshquant\morningglory\fqwebui\src\views\GanttUnifiedStocks.vue`
  - 旧统一个股页
  - 映射到目标仓库同名页面
- `D:\fqpack\freshquant\morningglory\fqwebui\src\views\components\XgbHistoryGantt.vue`
  - 旧底层图表组件
  - 映射到目标仓库 `components/GanttHistory.vue`
- `D:\fqpack\freshquant\morningglory\fqwebui\src\api\xgb.js` / `src\api\jygs.js`
  - 旧甘特接口封装
  - 收口为目标仓库 `src/api/ganttApi.js`
- `D:\fqpack\freshquant\morningglory\fqwebui\src\api\ganttSearch.js`
  - 本 RFC 不迁移
- `D:\fqpack\freshquant\morningglory\fqwebui\src\views\GanttShouban30.vue`
  - 本 RFC 不迁移

## 10. 测试与验收（Acceptance Criteria）

- [x] 导航栏新增“板块趋势”按钮，并能进入 `/gantt?p=xgb`
- [x] `/gantt?p=xgb` 与 `/gantt?p=jygs` 可正常加载
- [x] 板块 tooltip 显示板块热门理由
- [x] 个股 tooltip 显示标的热门理由
- [x] 点击板块格子可下钻到 `/gantt/stocks/:plateKey`
- [x] 点击左侧板块名称可跳转到对应数据源页面
- [x] `pytest freshquant/tests/test_gantt_readmodel.py freshquant/tests/test_gantt_routes.py -q` 通过
- [x] `npm run build` 在 `morningglory/fqwebui` 中通过

## 11. 风险与回滚（Risks / Rollback）

- 风险：旧图表组件耦合较深，迁移时容易夹带旧功能。
  - 缓解：按本 RFC 明确裁剪搜索与 BLK 逻辑。
- 风险：JYGS 无稳定板块详情外链。
  - 缓解：保持旧行为，链接到当前悬浮日期的 action 页面。
- 风险：板块理由若未在后端先补齐，前端将无法满足关键验收项。
  - 缓解：后端任务优先于前端页面迁移。

## 12. 里程碑与拆分（Milestones）

- M1：RFC 0011 评审通过
- M2：后端补齐板块理由投影与 `/api/gantt/plates` 契约
- M3：前端迁移统一页、下钻页和导航入口
- M4：完成联调、构建验证与迁移进度更新
