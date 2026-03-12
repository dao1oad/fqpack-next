# 甘特图展示

## 职责

通用 Gantt 页面负责展示热门板块与板块下热点标的的时间窗口分布。它是读模型展示层，不直接参与筛选写入或交易链。

## 入口

- 前端路由
  - `/gantt`
  - `/gantt/stocks/:plateKey`
- 前端组件
  - `GanttUnified.vue`
  - `GanttUnifiedStocks.vue`
  - `components/GanttHistory.vue`
- 后端接口
  - `/api/gantt/plates`
  - `/api/gantt/stocks`
  - `/api/gantt/stocks/reasons`

## 依赖

- `gantt_plate_daily`
- `gantt_stock_daily`
- `stock_hot_reason_daily`
- Dagster 读模型更新

## 数据流

`Mongo gantt readmodel -> freshquant.rear.gantt.routes -> GanttHistory -> provider tabs / window switch / drill down`

页面当前支持：

- provider 切换
  - `xgb`
  - `jygs`
- plate 视图与 stock 视图
- `days` 窗口切换
- 热门理由弹窗

## 存储

通用 Gantt 只读下列集合：

- `gantt_plate_daily`
- `gantt_stock_daily`
- `stock_hot_reason_daily`
- `plate_reason_daily`

不写工作区集合。

## 配置

- `provider`
- `days`
- `plate_key`
- `end_date`

所有日期参数都要求 `YYYY-MM-DD`。

## 部署/运行

- 后端逻辑改动：重建 `fq_apiserver`
- 页面改动：重建 `fq_webui`
- 读模型改动：必要时重跑 Dagster

## 排障点

### 板块页为空

- 检查 `/api/gantt/plates?provider=xgb`
- 检查 `gantt_plate_daily` 是否有窗口内数据

### drill-down 进入标的页后为空

- 检查 `plate_key` 是否在读模型中存在
- 检查 `/api/gantt/stocks` 返回

### 热门理由弹窗为空

- 检查 `stock_hot_reason_daily`
- 检查 provider 是否正确
