# 甘特图页面迁移设计稿

**目标**：在目标仓库基于 RFC 0006 已落地的盘后读模型与统一 `/api/gantt/*` 接口，迁移旧分支“板块趋势”统一页，保留核心分析体验，删除已超出当前后端边界的附属功能。

## 1. 调研结论

### 1.1 旧分支页面能力

- 导航入口位于 `D:\fqpack\freshquant\morningglory\fqwebui\src\views\MyHeader.vue`，点击后进入 `/gantt?p=xgb`。
- 路由位于 `D:\fqpack\freshquant\morningglory\fqwebui\src\router\index.js`，主页面为 `GanttUnified.vue`，下钻页面为 `GanttUnifiedStocks.vue`。
- 底层图表组件为 `D:\fqpack\freshquant\morningglory\fqwebui\src\views\components\XgbHistoryGantt.vue`，支持：
  - `xgb/jygs` 双 provider 切换
  - `7/15/30/45/60/90` 日窗口切换
  - 板块矩阵与个股矩阵下钻
  - 左侧板块侧栏
  - ECharts dataZoom、回到最新、回到顶部
  - 板块名称跳转到数据源页面
  - tooltip 展示板块/个股信息
- 旧页面还包含两个附属功能：
  - “加入近期涨停池”
  - “全历史标的异动检索”

### 1.2 当前目标仓库现状

- 前端尚未迁入甘特图页面、路由与导航入口。
- 后端已完成 RFC 0006 范围内的数据链路：
  - XGB/JYGS 原始同步
  - `plate_reason_daily`、`gantt_plate_daily`、`gantt_stock_daily`
  - `/api/gantt/plates`、`/api/gantt/stocks`
  - Dagster 盘后任务与调度
- 目前 `gantt_stock_daily.stock_reason` 已通过 `/api/gantt/stocks` 暴露。
- 目前板块理由仍只保存在 `plate_reason_daily`，尚未出现在 `/api/gantt/plates` 返回中。

### 1.3 关键模型差异

- 旧分支板块下钻参数为 `plate_id`，目标仓库统一为 `plate_key`。
- 旧分支板块 tooltip 假定接口返回热门标的对象数组；目标仓库当前仅提供 `stock_codes`。
- 旧分支 XGB 页面会混入盘中 snapshot；目标仓库按 RFC 0006 明确只保留盘后读模型，不恢复该逻辑。
- 旧分支搜索接口与 BLK 导出接口在目标仓库均不存在。

## 2. 本次迁移范围

### 2.1 In Scope

- 新增导航按钮“板块趋势”，跳转 `/gantt?p=xgb`。
- 新增统一路由：
  - `/gantt`
  - `/gantt/stocks/:plateKey`
- 迁移旧统一页主交互：
  - provider Tabs
  - 回看窗口切换
  - 板块矩阵
  - 个股矩阵下钻
  - 左侧板块侧栏
  - 回到最新 / 回到顶部
  - 点击板块名称跳数据源
  - tooltip 展示板块热门理由和标的热门理由
- 统一改为调用目标仓库 `/api/gantt/*`。
- 为板块 tooltip 补齐后端理由字段暴露。

### 2.2 Out of Scope

- 不迁移“加入近期涨停池”。
- 不迁移“全历史标的异动检索”。
- 不迁移 `GanttShouban30.vue`。
- 不恢复旧 `/api/xgb/history/gantt/*`、`/api/jygs/history/gantt/*`。
- 不恢复盘中 snapshot 注入、WebSocket 或实时刷新。

## 3. 页面结构与交互设计

### 3.1 路由

- `/gantt`
  - query：`p=xgb|jygs`
  - query：`days=7|15|30|45|60|90`
- `/gantt/stocks/:plateKey`
  - query：`p=xgb|jygs`
  - query：`days=7|15|30|45|60|90`
  - query：`plate_name`
  - query：`_title`

### 3.2 页面分工

- `GanttUnified.vue`
  - 负责 provider Tabs、query 同步、向图表组件传参。
- `GanttUnifiedStocks.vue`
  - 负责下钻个股页的 provider/days/标题同步。
- `components/GanttHistory.vue`
  - 负责图表渲染、数据加载、tooltip、下钻、左侧侧栏和外链逻辑。

### 3.3 板块名称跳转

- XGB：跳 `https://xuangutong.com.cn/theme/<plateKey>`
- JYGS：跳当前悬浮日期对应的 action 页面 `https://www.jiuyangongshe.com/action/<hoveredDate>`

### 3.4 tooltip 内容

#### 板块视图

- 日期
- 板块名称
- 排名
- 热门标的数量
- 涨停数量
- 板块热门理由
- 热门标的代码列表

#### 个股视图

- 日期
- 标的名称 / 代码
- 连续活跃天数
- 是否涨停
- 标的热门理由

## 4. 后端契约调整

### 4.1 读模型

- `gantt_plate_daily` 新增字段：
  - `reason_text`
  - `reason_ref`
- 构建方式：
  - 在 `persist_gantt_daily_for_date()` 中，按 `provider + plate_key + trade_date` 关联 `plate_reason_daily`

### 4.2 API

- 保持 `data.series` 现有结构不变：
  - `plates.series = [dateIndex, yIndex, rank, hotStockCount, limitUpCount, stock_codes]`
  - `stocks.series = [dateIndex, yIndex, activeStreakDays, isLimit, stock_reason]`
- `/api/gantt/plates` 额外返回：

```json
{
  "data": {
    "dates": ["2026-03-05"],
    "y_axis": [{"id": "11", "name": "机器人"}],
    "series": [[0, 0, 1, 5, 3, ["300001", "002001"]]]
  },
  "meta": {
    "reason_map": {
      "2026-03-05|11": {
        "reason_text": "板块理由示例",
        "reason_ref": {
          "source": "xgb_top_gainer_history",
          "source_id": "..."
        }
      }
    }
  }
}
```

### 4.3 错误语义

- 板块理由是强约束主数据。
- 若某个进入 `gantt_plate_daily` 的板块缺少当日 `plate_reason_daily`，则构建任务直接失败。
- 前端不做“理由缺失”兜底拼接，不从个股理由反推板块理由。

## 5. 前端字段映射

| 能力 | 旧分支 | 目标仓库迁移后 |
|---|---|---|
| 板块列表主键 | `plate_id` | `plate_key` |
| 板块 API | `/api/xgb/history/gantt/plates` / `/api/jygs/history/gantt/plates` | `/api/gantt/plates?provider=...&days=...` |
| 个股 API | `/api/xgb/history/gantt/stocks` / `/api/jygs/history/gantt/stocks` | `/api/gantt/stocks?provider=...&plate_key=...&days=...` |
| 板块理由 | 混在旧数据/页面假设中 | `meta.reason_map["date|plateKey"].reason_text` |
| 个股理由 | `series[4]` | `series[4]` |
| 热门标的 | 对象数组 | `stock_codes` 字符串数组 |

## 6. 组件迁移策略

- 复用旧统一页结构，不重写交互。
- 旧 `XgbHistoryGantt.vue` 迁为中性命名 `GanttHistory.vue`。
- 新增统一 API 封装 `src/api/ganttApi.js`，不继续复用旧 `xgb.js` / `jygs.js` 甘特接口。
- 删除以下旧逻辑：
  - 搜索抽屉及其 API 调用
  - “加入近期涨停池”按钮和相关 API 调用
- 板块 tooltip 中的热门标的展示降级为代码列表，符合当前后端模型。

## 7. 验收口径

- 导航栏存在“板块趋势”按钮，点击进入 `/gantt?p=xgb`。
- `/gantt?p=xgb` 与 `/gantt?p=jygs` 均可打开并加载矩阵。
- 板块 tooltip 能展示板块热门理由。
- 个股 tooltip 能展示标的热门理由。
- 点击板块格子可以下钻到 `/gantt/stocks/:plateKey`。
- 点击左侧板块名称可以跳到对应数据源页面。
- 页面构建通过 `npm run build`。
- 后端相关测试覆盖理由 join 与 API 返回契约。

## 8. 风险与缓解

- 风险：旧组件对 `series` 下标依赖重，直接改 `series` 结构容易引入回归。
  - 缓解：理由通过 `meta.reason_map` 返回，不调整既有坐标数组结构。
- 风险：JYGS 外链没有稳定的板块详情 URL。
  - 缓解：保持旧行为，跳当前悬浮日期的 action 页面。
- 风险：当前前端仓库没有甘特页面基线，迁移时可能带入旧无关功能。
  - 缓解：按本设计明确裁剪范围，只保留已确认能力。
