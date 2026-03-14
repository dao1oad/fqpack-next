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
- `settings.tdx.home or TDX_HOME`
- `<tdx_home>/T0002/blocknew/30RYZT.blk`

## 数据流

`readmodel snapshot -> /api/gantt/shouban30/* -> GanttShouban30Phase1 -> save current filter / save plate -> replace pre_pool + auto sync blk`

`workspace pre_pools / stock_pools -> manual sync-to-tdx or clear -> full overwrite 30RYZT.blk`

当前快照前提：

- `shouban30_plates` / `shouban30_stocks` 由 Gantt 盘后链路按 `30/45/60/90` 窗口重建
- Gantt recent hole backfill 修复 `jygs` 历史缺口后，会在同一次 Dagster 流水线里顺带重建 Shouban30 快照
- `jygs` 某个交易日没有热点时，不再把 `trade_date` 漂移到别的日期；Shouban30 依赖的上游窗口会保留真实交易日边界

页面当前支持：

- provider 切换
- `30/45/60/90` 日标的窗口
  - 使用独立 query 参数 `stock_window_days`，不复用通用 Gantt 的 `days`
  - `provider`、`stock_window_days`、`as_of_date` 任一变化都会重新加载当前视图数据
- 额外条件筛选
- 预选池、股票池工作区操作
- 顶部“筛选”与“保存到 pre_pools”会完整替换 `三十涨停Pro预选`，随后自动完整覆盖 `30RYZT.blk`
- 工作区标签显示为 `pre_pools` / `stock_pools`，内部 tab key 仍保持 `pre_pool` / `stockpools`
- `pre_pools` 与 `stock_pools` 标签各自提供“同步到通达信”和“清空”按钮；清空不弹确认框，会直接清空对应池子并立即完整覆盖 `30RYZT.blk`
- 两个工作区共享同一个 `30RYZT.blk`，所以最终文件内容始终由最后一次 `pre_pools` / `stock_pools` 的同步或清空动作决定
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
- 通达信目录解析口径固定为：先读 `settings.tdx.home`，未配置时回退 `TDX_HOME`
- 默认分类：
  - `三十涨停Pro预选`
  - `三十涨停Pro自选`
  - `三十涨停Pro`

## 部署/运行

- 页面或 gantt routes 改动后，重建 API 与 Web UI。
- 读模型逻辑改动后，重跑 Dagster。
- 工作区与 `.blk` 同步逻辑改动后，必须在宿主机验证 `<tdx_home>/T0002/blocknew/30RYZT.blk` 写入。

## 排障点

### `/shouban30/plates` 返回 409

- 说明快照未准备好，先检查 `shouban30_plates` 与 `shouban30_stocks`
- 再检查对应交易日的 Gantt backfill 是否已经完成；Shouban30 不会绕过 Gantt 读模型单独补数

### 页面筛选按钮无效

- 检查 `selected_extra_filters` 是否正确回传
- 检查 replace context 是否写入 `stock_pre_pools.extra`

### 保存到 pre_pools 成功但 `.blk` 不更新

- 检查 `settings.tdx.home` / `TDX_HOME`
- 检查最终目标是否为 `<tdx_home>/T0002/blocknew/30RYZT.blk`
- 检查宿主机是否有写权限

### 点击“同步到通达信”或“清空”后文件内容不对

- 确认当前激活的是 `pre_pools` 还是 `stock_pools` 标签；按钮只会以当前标签对应池子为真值
- 确认这是完整覆盖写，不会 append，也不会合并两个池子
- 如果刚执行过另一个工作区的同步或清空，`30RYZT.blk` 被后一次动作覆盖属于预期

### 加入 must_pool 后策略仍不关注

- 检查 `must_pool` 是否真的落库
- 检查 XTData 订阅池刷新是否已生效
