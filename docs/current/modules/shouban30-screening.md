# 首板筛选

## 职责

Shouban30 模块负责“30 天首板”盘后筛选结果展示、`pre_pool / stock_pool` 工作区管理，以及向通达信同步 `30RYZT.blk`。它和通用 Gantt 共用部分后端，但职责不同：Gantt 只读展示，Shouban30 负责筛选结果与工作区之间的受控同步。

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
- `bootstrap_config.tdx.home or TDX_HOME`
- `D:\tdx_biduan\T0002\blocknew\30RYZT.blk`

## 数据流

`readmodel snapshot -> /api/gantt/shouban30/* -> GanttShouban30Phase1 -> 页面筛选结果`

`页面板块行 -> /api/gantt/shouban30/pre-pool/append -> pre_pool`

`pre_pool -> /api/gantt/shouban30/pre-pool/add-to-stock-pools 或 /sync-to-stock-pool -> stock_pool`

`stock_pool -> /api/gantt/shouban30/stock-pool/add-to-must-pool 或 /sync-to-must-pool -> must_pool`

`pre_pool / stock_pool -> 手动 sync-to-tdx -> full overwrite 30RYZT.blk`

当前快照前提：

- `shouban30_plates` / `shouban30_stocks` 由 Gantt 盘后链路按 `30/45/60/90` 自然日窗口重建
- Gantt recent hole backfill 修复 `jygs` 历史缺口后，会在同一次 Dagster 流水线里顺带重建 Shouban30 快照
- 若最新交易日的 Shouban30 快照仍带旧交易日窗口语义，例如 `stock_window_from` 早于对应自然日窗口起点，Dagster 会把它当成 legacy snapshot 并对该交易日重建
- `jygs` 某个交易日没有热点时，不再把 `trade_date` 漂移到别的日期；Shouban30 依赖的上游窗口会保留真实交易日边界

页面当前支持：

- provider 切换
- `30/45/60/90` 日自然日窗口
  - 对外 query / API 默认使用 `days` + `end_date`
  - 页面仍兼容旧链接里的 `stock_window_days` + `as_of_date`，但交互后会回写成 `days` + `end_date`
  - `provider`、`days`、`end_date` 任一变化都会重新加载当前视图数据
- 板块候选、标的候选、顶部窗口信息、工作区保存上下文使用同一套自然日窗口口径
- 额外条件筛选
  - 条件按钮只改变待应用筛选条件
  - 点击“筛选”后才把条件应用到当前页面结果
  - “条件筛选”表头悬浮说明当前会明确提示：缠论通过口径已切到日线 `1d`
  - 当前默认缠论规则为：高级段倍数 `<= 3`、段倍数 `<= 2`、笔涨幅% `<= 20`
  - “筛选”不再写 `pre_pool`，也不再写通达信
  - “全部加入 pre_pools”会把当前已应用多条件筛选后的页面结果按页面顺序 append 到 `pre_pool`
  - 该批量 append 当前会写入共享 `stock_pre_pools` 去重真值；同一个 `code` 不再新增第二条记录，而是补充 `shouban30` membership
- 预选池、股票池工作区操作
- 板块列表操作列显示“添加到 pre_pools”，会把当前板块标的按页面顺序 append 到 `pre_pool`
  - append 按 `(code, source=shouban30, category)` 幂等；列表展示仍保持 `code` 唯一
  - 该动作不触发 `.blk` 写入
- `pre_pool` 保留单条“加入 stock_pools”，并新增批量“同步到 stock_pool”
  - 批量同步会把 `pre_pool` 的 `sources / categories / memberships` 一并写入 `stock_pool`
  - 对已存在于 `stock_pool` 的同 code 标的，接口仍返回 `already_exists / skipped_count`，但会补齐缺失的 provenance 字段，不要求先删后加
- `stock_pool` 恢复单条“加入 must_pools”，并新增批量“同步到 must_pools”
  - 单条与批量共用同一套 `must_pool` upsert 语义：不存在记为 `created`，已存在记为 `updated`
  - 批量同步返回 `created_count / updated_count / total_count`
  - 批量同步按当前 `stock_pool` 页面顺序执行，但不会改变 `stock_pool` 自身顺序，也不会附带通达信同步
- 工作区标签显示为 `pre_pools` / `stock_pools`，内部 tab key 仍保持 `pre_pool` / `stockpools`
- `pre_pools` 当前展示共享去重池子的全量列表，并明确显示 `sources / categories`
- `stock_pools` 当前也会明确展示并返回 `sources / categories / memberships`，用于说明每只标的是从哪些 `pre_pool` 来源/分类进入工作区
- `pre_pools` 与 `stock_pools` 标签各自提供“同步到通达信”和“清空”按钮；`pre_pools` 的清空当前会清空整个共享 `stock_pre_pools` 池子并立即完整覆盖 `30RYZT.blk`
- 两个工作区共享同一个 `30RYZT.blk`，所以最终文件内容始终由最后一次 `pre_pools` / `stock_pools` 的同步或清空动作决定
- 中间“热点标的”和工作区列表共用同一套“标的详情”联动；点击工作区行也会加载右侧标的详情
- 热门理由与缠论统计展示
- 页面桌面工作区固定按单屏展示；`首板板块`、`热点标的`、`标的详情`、`工作区` 同时保留在视口内
- 各区域超长内容改为各自列表或详情区内滚动，不再依赖浏览器页面滚动把工作区推到屏幕外
- provider 标签当前显示为：`选股通`、`韭研公社`、`聚合`

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

- `days` 只能是 `30|45|60|90`
- `end_date` 要求 `YYYY-MM-DD`
- `/api/gantt/shouban30/plates`、`/api/gantt/shouban30/stocks` 的返回 `meta` 会同时带 `days/end_date` 与兼容别名 `stock_window_days/as_of_date`
  - `end_date` 表示自然日窗口终点
  - `as_of_date` 表示实际命中的快照交易日；当 `end_date` 落在非交易日时，会回落到 `<= end_date` 的最近快照
- 工作区 extra 会同时写入 `shouban30_days/shouban30_end_date` 与兼容别名 `shouban30_stock_window_days/shouban30_as_of_date`
- `stock_pre_pools` 当前正式真值是“同一个 `code` 只保留一条记录”，并通过 `sources / categories / memberships` 区分 `daily-screening`、`shouban30` 等来源
- `pre_pool` 顶层使用 `workspace_order` 作为共享顺序真值；兼容字段 `extra.shouban30_order` 仍保留用于旧页面与 `.blk` 输出桥接
- `stock_pool` 继续使用 `extra.shouban30_order` 作为页面顺序与 `.blk` 输出顺序真值
  - 历史 `stock_pool` 记录缺失该字段时，读取顺序兼容回退到 `datetime desc`
- 当前缠论过滤版本是 `1d_v1`
- 通达信目录解析口径固定为：先读 `bootstrap_config.tdx.home`，未配置时回退 `TDX_HOME`
- Docker 并行部署下，`fq_apiserver` 当前必须挂载 `${FQPACK_TDX_SYNC_DIR:-D:/tdx_biduan}` 到 `/opt/tdx`
- 默认分类：
  - `三十涨停Pro预选`
  - `三十涨停Pro自选`
  - `三十涨停Pro`

## 部署/运行

- 页面或 gantt routes 改动后，重建 API 与 Web UI。
- 读模型逻辑改动后，重跑 Dagster。
- 工作区与 `.blk` 同步逻辑改动后，必须在宿主机验证 `D:\tdx_biduan\T0002\blocknew\30RYZT.blk` 写入。

## 排障点

### `/shouban30/plates` 返回 409

- 说明快照未准备好，先检查 `shouban30_plates` 与 `shouban30_stocks`
- 再检查对应交易日的 Gantt backfill 是否已经完成；Shouban30 不会绕过 Gantt 读模型单独补数

### 页面时间窗口切换后最早上板时间不变

- 先核对返回 `meta.end_date` 与 `meta.as_of_date`，确认前端是否已经落到 `days/end_date`
- 再查最新 `shouban30_plates` 的 `stock_window_from`；如果它早于同窗口自然日理论起点，说明仍是旧交易日窗口快照
- 这种情况不需要手工先删旧数据，直接重跑 Dagster 或调用同一套 Shouban30 snapshot 重建逻辑即可覆盖

### 页面筛选按钮无效

- 检查当前路由是否已经落到 `days` / `end_date`
- 检查页面是否只是切换了待应用条件，还没有点击“筛选”
- 检查 `selected_extra_filters` 是否正确进入当前页面筛选结果，而不是误写到 `stock_pre_pools.extra`

### 添加到 pre_pools 成功但 `.blk` 不更新

- 这是当前预期
- “添加到 pre_pools”只做 append，不触发 `.blk` 写入
- 需要显式点击 `pre_pools` 或 `stock_pools` 标签里的“同步到通达信”

### 点击“同步到通达信”或“清空”后文件内容不对

- 确认当前激活的是 `pre_pools` 还是 `stock_pools` 标签；按钮只会以当前标签对应池子为真值
- 确认这是完整覆盖写，不会 append，也不会合并两个池子
- 检查工作区列表顺序是否和预期一致；`.blk` 会按 `extra.shouban30_order` 输出
- 如果刚执行过另一个工作区的同步或清空，`30RYZT.blk` 被后一次动作覆盖属于预期

### 加入 must_pool 后策略仍不关注

- 先确认当前动作是单条“加入 must_pools”还是批量“同步到 must_pools”
- 单条返回 `created`/`updated`，批量返回 `created_count / updated_count / total_count`
- 再检查 `must_pool` 是否落库，以及 XTData 订阅池是否已经刷新
