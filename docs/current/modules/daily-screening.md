# 每日选股

## 职责

每日选股模块是“股票视角的统一盘后筛选工作台”。它不替代 `/gantt/shouban30` 的板块工作台职责，而是把多条盘后筛选来源统一收口到一个可执行、可解释、可交集筛选的页面：

- `CLXS` 全模型
- `chanlun` 全周期全信号
- `Shouban30` 90 天聚合结果
- 全市场属性集合
  - `融资标的`
  - `均线附近`
  - `优质标的`

页面既支持手动发起全链路扫描，也支持在最新正式结果或某次手动 run 上做交集筛选、查看详情，并按需把结果复制到共享工作区。

## 入口

- 前端路由
  - `/daily-screening`
- 前端页面
  - `morningglory/fqwebui/src/views/DailyScreening.vue`
- 后端服务
  - `freshquant.daily_screening.service.DailyScreeningService`
  - `freshquant.daily_screening.pipeline_service.DailyScreeningPipelineService`
  - `freshquant.daily_screening.repository.DailyScreeningRepository`
- Dagster
  - `fqdagster.defs.ops.daily_screening`
  - `fqdagster.defs.jobs.daily_screening`
  - `fqdagster.defs.schedules.daily_screening`

## 正式链路

### 手动执行链

`DailyScreening.vue -> /api/daily-screening/runs -> DailyScreeningService -> CLXS / chanlun / shouban30_agg90 / market_flags -> fqscreening -> /api/daily-screening/query + /stocks/<code>/detail`

### 自动执行链

`job_daily_screening_postclose -> 19:00 schedule -> DailyScreeningService.start_run(run_async=false, trigger_type=dagster_schedule) -> fqscreening`

### 页面交互链

`scope summary + stock snapshots + memberships -> 交集筛选 -> 结果列表 -> 统一详情 -> add-to-pre-pool / add-batch-to-pre-pool`

## 当前实现

### 全链路模式

`model=all` 会按固定四段顺序执行：

1. `CLXS`
   - 默认跑 `10001 ~ 10012`
   - 页面标签显示为 `S0001 ~ S0012`
2. `chanlun`
   - 默认只消费“本次 CLXS run 命中的股票集合”
   - 默认跑 `30m / 60m / 1d`
   - 默认跑 6 个固定信号
3. `shouban30_agg90`
   - 读取 `shouban30_stocks` 的 `90` 天快照
   - 聚合 `xgb + jygs`
4. `market_flags`
   - 对全市场打标：
     - `credit_subject`
     - `near_long_term_ma`
     - `quality_subject`

### 前端工作台

页面分成三块：

- 执行区
  - 支持 `全链路 / CLXS / chanlun`
  - 参数由 `/schema` 动态下发
  - 启动后通过 SSE 实时显示阶段事件
- 交集筛选区
  - 来源集合之间做交集
  - 来源内部维度做并集
  - 当前支持：
    - `CLXS`
    - `chanlun`
    - `90天聚合`
    - `融资标的`
    - `均线附近`
    - `优质标的`
- 详情区
  - 展示股票统一画像
  - 展示 `CLXS 命中模型`
  - 展示 `chanlun 命中信号 + 周期`
  - 展示 `90天聚合 / 属性`
  - 复用 `Shouban30` 的历史热门理由展示方式

### 手动工作区动作

页面不会把 `fqscreening` 正式结果自动混写到共享工作区。只有显式动作才会复制到：

- `stock_pre_pools`
  - `/api/daily-screening/actions/add-to-pre-pool`
  - `/api/daily-screening/actions/add-batch-to-pre-pool`
- `stock_pools`
  - 仍由既有工作区链路承接

## 当前接口

- `/api/daily-screening/schema`
- `/api/daily-screening/runs`
- `/api/daily-screening/runs/<run_id>`
- `/api/daily-screening/runs/<run_id>/stream`
- `/api/daily-screening/scopes`
- `/api/daily-screening/scopes/latest`
- `/api/daily-screening/scopes/<run_id>/summary`
- `/api/daily-screening/query`
- `/api/daily-screening/stocks/<code>/detail`
- `/api/daily-screening/actions/add-to-pre-pool`
- `/api/daily-screening/actions/add-batch-to-pre-pool`
- 兼容保留的工作区接口
  - `/api/daily-screening/pre-pools`
  - `/api/daily-screening/pre-pools/stock-pools`
  - `/api/daily-screening/pre-pools/delete`

## 存储

正式结果已经不再以 `stock_pre_pools` 为真值，而是使用独立 `fqscreening` 数据库：

- `daily_screening_runs`
- `daily_screening_memberships`
- `daily_screening_stock_snapshots`

共享工作区仍保留在 `freshquant.stock_pre_pools / stock_pools / must_pool`，只作为人工动作的目标集合。

## SSE 事件

当前页面消费这些事件：

- `run_started`
- `stage_started`
- `stage_progress`
- `stage_completed`
- `run_completed`
- `run_failed`
- `heartbeat`

页面会把阶段级事件汇总成可读日志，不把全量 membership 明细直接推到浏览器。

## 自动任务

- Dagster job：`job_daily_screening_postclose`
- Schedule：`daily_screening_postclose_schedule`
- Cron：工作日 `19:00`

这条任务负责执行正式全链路，不替代现有 `16:40` 的 Gantt / Shouban30 读模型构建任务。

## 当前边界

- `/gantt/shouban30` 继续是板块工作台；每日选股不接管 `.blk` 同步和 `must_pool` 工作区语义。
- `DailyScreeningService` 仍直接调用底层 `CLXS / chanlun` 策略，不重新实现策略逻辑。
- 页面“交集筛选”基于 `fqscreening` 快照做查询，不会重新触发算法计算。
- SSE 会话仍保留在 API 进程内存；正式结果真值在 `fqscreening`，不是 session store。

## 部署/运行

- `freshquant/daily_screening/**` 改动后，重建 API Server。
- `morningglory/fqwebui/**` 改动后，重建 Web UI。
- `morningglory/fqdagster/**` 改动后，重启 Dagster Webserver / Daemon。
- 如果全链路要实际执行，运行环境必须具备原 `clxs / chanlun_service / fqcopilot / fqchan04` 依赖。

## 排障

### 页面能打开但 scope / 结果为空

- 先看 `/api/daily-screening/scopes/latest`
- 再看 `/api/daily-screening/scopes/<run_id>/summary`
- 再看 `fqscreening.daily_screening_stock_snapshots` 是否已有该 `run_id`

### 手动启动成功但没有后续结果

- 看 `/api/daily-screening/runs/<run_id>` 的 `status`
- 看 SSE 是否有 `stage_started`
- 如果停在 `CLXS` 或 `chanlun` 阶段，优先检查底层策略依赖是否可用

### 自动任务没有出最新正式结果

- 看 Dagster 中 `daily_screening_postclose_schedule` 是否在运行
- 看 `job_daily_screening_postclose` 最近一次 run 是否成功
- 再确认 `16:40` 的 Gantt / Shouban30 读模型任务是否先完成
