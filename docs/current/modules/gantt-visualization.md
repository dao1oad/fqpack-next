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

当前窗口语义：

- `days` 先按自然日窗口截取 `start_date ~ end_date`
- `dates` 轴按交易日历展开该窗口内全部交易日
- 某个交易日没有热点时，该日期仍保留在 `dates` 轴上，只是 `series` 不产生点位
- `/api/gantt/plates` 与 `/api/gantt/stocks` 对 `xgb` / `jygs` 使用同一套窗口语义

## 存储

通用 Gantt 只读下列集合：

- `gantt_plate_daily`
- `gantt_stock_daily`
- `stock_hot_reason_daily`
- `plate_reason_daily`

不写工作区集合。

Gantt 读模型当前还依赖以下盘后事实：

- Dagster 在最新交易日追平后，会额外扫描最近 `90` 个交易日的 `jygs` 原始集合与 gantt 读模型，发现旧缺口就重新补跑
- `jygs_action_fields` / `jygs_yidong` 在目标交易日无上游热点时，会写入 `is_empty_result=true` 的 zero-fill marker，保持请求的 `trade_date`，不再漂移到别的交易日

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
- 检查返回里的 `dates` 是否完整；如果日期轴完整但 `series=[]`，说明窗口内没有热点，而不是窗口参数失效

### `jygs` 大窗口仍收敛到同一小段日期

- 检查 `jygs_action_fields` / `jygs_yidong` 是否覆盖目标窗口内交易日
- 若某天只有 `is_empty_result=true` marker，表示上游该交易日无可回补热点，当前系统会保留交易日轴但不生成 `jygs` 点位
- 若目标交易日既无 marker 也无真实数据，重跑 Dagster；当前 backfill 会扫描最近 `90` 个交易日并补最近历史洞

### drill-down 进入标的页后为空

- 检查 `plate_key` 是否在读模型中存在
- 检查 `/api/gantt/stocks` 返回

### 热门理由弹窗为空

- 检查 `stock_hot_reason_daily`
- 检查 provider 是否正确
