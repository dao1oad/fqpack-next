# 首板筛选

## 职责

Shouban30 模块负责“30 天首板”盘后筛选、页面工作区管理和向 `pre_pool / stock_pool / must_pool` 的落库同步。它和通用 Gantt 共用部分后端，但职责不同：Gantt 只读展示，Shouban30 负责筛选结果工作区。

## 入口

- 前端路由
  - `/gantt/shouban30`
- 前端页面
  - `GanttShouban30Phase1.vue`
- 后端接口
  - `/api/gantt/shouban30/plates`
  - `/api/gantt/shouban30/stocks`
  - `/api/gantt/shouban30/pre-pool/*`
  - `/api/gantt/shouban30/stock-pool/*`
- 工作区服务
  - `freshquant.shouban30_pool_service`

## 依赖

- `shouban30_plates`
- `shouban30_stocks`
- `stock_pre_pools`
- `stock_pools`
- `must_pool`
- `TDX_HOME/T0002/blocknew/30RYZT.blk`

## 数据流

`readmodel snapshot -> /api/gantt/shouban30/* -> GanttShouban30Phase1 -> save current filter / save plate / add to stock pool / add to must pool -> Mongo workspace + blk sync`

页面当前支持：

- provider 切换
- `30/45/60/90` 日标的窗口
  - 使用独立 query 参数 `stock_window_days`，不复用通用 Gantt 的 `days`
  - `provider`、`stock_window_days`、`as_of_date` 任一变化都会重新加载当前视图数据
- 额外条件筛选
- 预选池、股票池工作区操作
- 热门理由与缠论统计展示

## 存储

读模型集合：

- `shouban30_plates`
- `shouban30_stocks`

工作区集合：

- `stock_pre_pools`
- `stock_pools`
- `must_pool`

宿主机文件：

- `30RYZT.blk`

## 配置

- `stock_window_days` 只能是 `30|45|60|90`
- 当前缠论过滤版本是 `30m_v1`
- 默认分类：
  - `三十涨停Pro预选`
  - `三十涨停Pro自选`
  - `三十涨停Pro`

## 部署/运行

- 页面或 gantt routes 改动后，重建 API 与 Web UI。
- 读模型逻辑改动后，重跑 Dagster。
- 工作区与 `.blk` 同步逻辑改动后，必须在宿主机验证 `TDX_HOME` 写入。

## 排障点

### `/shouban30/plates` 返回 409

- 说明快照未准备好，先检查 `shouban30_plates` 与 `shouban30_stocks`

### 页面筛选按钮无效

- 检查 `selected_extra_filters` 是否正确回传
- 检查 replace context 是否写入 `stock_pre_pools.extra`

### 保存到 pre_pool 成功但 `.blk` 不更新

- 检查 `TDX_HOME`
- 检查宿主机是否有写权限

### 加入 must_pool 后策略仍不关注

- 检查 `must_pool` 是否真的落库
- 检查 XTData 订阅池刷新是否已生效
