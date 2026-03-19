# 每日选股

## 职责

每日选股模块现在是“盘后预计算 + 前端自由交集查询”的工作台，不再是页面手动触发执行的扫描器。

模块职责拆成两层：

- Dagster
  - 负责按交易日生成条件集合与指标快照
  - 把正式结果落到 `fqscreening`
- 前端 `/daily-screening`
  - 只读取正式 scope
  - 让用户自由勾选条件并取交集
  - 展示交集列表和单标的详情

## 入口

- 前端路由
  - `/daily-screening`
- 前端页面
  - `morningglory/fqwebui/src/views/DailyScreening.vue`
- 前端状态/API
  - `morningglory/fqwebui/src/views/dailyScreeningPage.mjs`
  - `morningglory/fqwebui/src/api/dailyScreeningApi.js`
- 后端服务
  - `freshquant.daily_screening.service.DailyScreeningService`
  - `freshquant.daily_screening.repository.DailyScreeningRepository`
- Dagster
  - `fqdagster.defs.assets.daily_screening`
  - `fqdagster.defs.schedules.daily_screening`

## 正式链路

### Dagster 盘后链路

`daily_screening_context -> upstream_guard -> universe -> cls / hot_30 / hot_45 / hot_60 / hot_90 -> base_union -> near_long_term_ma / quality_subject / credit_subject / shouban30_chanlun_metrics / chanlun_variants -> snapshot_assemble -> publish_scope`

### 页面查询链路

`scopes/latest + filters + scope_summary -> 条件组合 -> /api/daily-screening/query -> 结果列表 -> /api/daily-screening/stocks/<code>/detail`

## 当前实现

### 条件模型

前端统一使用 `condition_key` 做交集，不再使用旧的“来源之间交集、来源内并集”页面语义。

当前条件分组：

- `CLS 形态分组`
  - 后端 membership 仍按 `cls:S0001` 到 `cls:S0012` 落库
  - 页面把 12 个模型收敛成 5 个中文分组，组内取并集、和其他条件继续取交集
  - 正式 `trade_date:<YYYY-MM-DD>` scope 下，CLS 分组数量和分组筛选都基于 `daily_screening_memberships` 中的 `cls:S0001` 到 `cls:S0012` 真值聚合，不依赖快照里的旧 `clxs_models` 字段
  - 分组映射：
    - `二买`
      - `类2买`
      - `类2买分型`
      - `复杂类2买`
      - `2买及类2买`
    - `三买`
      - `3买或中枢3买`
    - `压力支撑`
      - `低点反弹`
      - `顶底互换`
    - `背驰`
      - `盘整或趋势背驰`
      - `下盘下`
    - `突破回调`
      - `突破回调`
      - `突破回踩`
      - `V反`
- 热门窗口
  - `hot:30d`
  - `hot:45d`
  - `hot:60d`
  - `hot:90d`
  - 口径是 `xgb + jygs` 聚合
- 市场属性
  - `flag:near_long_term_ma`
  - `flag:quality_subject`
  - `flag:credit_subject`
- `chanlun` 周期
  - `chanlun_period:30m`
  - `chanlun_period:60m`
  - `chanlun_period:1d`
- `chanlun` 信号
  - `chanlun_signal:buy_zs_huila`
  - `chanlun_signal:buy_v_reverse`
  - `chanlun_signal:macd_bullish_divergence`
  - `chanlun_signal:sell_zs_huila`
  - `chanlun_signal:sell_v_reverse`
  - `chanlun_signal:macd_bearish_divergence`

`日线缠论涨幅` 不作为普通 membership 存储，而是作为快照数值字段落库：

- `higher_multiple`
- `segment_multiple`
- `bi_gain_percent`
- `chanlun_reason`

这组数值和 `/gantt/shouban30` 页面保持同口径，当前固定基于 `1d` 缠论结构计算。页面默认展示阈值：

- 高级段倍数 `<= 3`
- 段倍数 `<= 2`
- 笔涨幅% `<= 20`

但首次进入页面时，该组筛选默认不启用；只有用户显式点选“日线缠论涨幅”后，这组阈值才参与交集过滤。

### 基础池语义

查询始终锚定 `base:union`。

也就是：

- 无条件查询：返回“CLS 各模型结果”和“热门 30/45/60/90 天结果”先取并集后的基础池
- 有条件查询：返回“基础池 ∩ 用户勾选条件 ∩ 已启用的数值阈值”

### 前端页面

页面已经移除：

- 手动运行表单
- `/schema` 驱动的执行区
- `SSE` 事件流显示
- “开始扫描”入口

页面只保留：

- scope 选择
- 工作台总说明
- 条件分组勾选
- 左侧筛选工作台独立滚动；在浏览器 100% 缩放下仍通过面板自身滚动条完整访问全部条件
- 每个筛选分组表头的悬浮说明提示
- `日线缠论涨幅` 总开关和默认阈值输入
- 交集结果表格
- 交集列表左侧的 `全部加入pre_pools`
- 共享工作区
  - `pre_pools`
  - `stock_pools`
- 单标的条件画像与热门理由

页面中的说明文案固定解释：

- 上游范围是全市场，排除 `ST` 和北交所
- 基础池由 `CLS` 各模型结果和热门 `30/45/60/90` 天结果先取并集形成
- 用户勾选条件后，对当前结果继续取交集
- 交集结果可以沉淀到共享工作区

页面交互当前口径：

- 页面首次进入会自动查询当前正式 scope，不需要再点“查询结果”
- 点击任意条件按钮后会立即刷新交集结果
- 修改“日线缠论涨幅”阈值后会经短防抖自动刷新
- 中间“交集列表/工作区”和右侧“标的详情”平分剩余宽度，避免详情面板过窄

### Dagster 节点 helper

`DailyScreeningService` 现在暴露可供 asset 调用的显式方法：

- `build_universe()`
- `build_cls_memberships()`
- `build_hot_window_memberships()`
- `build_market_flag_memberships()`
- `build_chanlun_variant_memberships()`
- `build_shouban30_chanlun_metrics()`

## 当前接口

前端主路径使用：

- `/api/daily-screening/scopes`
- `/api/daily-screening/scopes/latest`
- `/api/daily-screening/filters`
- `/api/daily-screening/scopes/<scope_id>/summary`
- `/api/daily-screening/query`
- `/api/daily-screening/stocks/<code>/detail`

页面工作区直接复用：

- `/api/gantt/shouban30/pre-pool`
- `/api/gantt/shouban30/pre-pool/append`
- `/api/gantt/shouban30/pre-pool/add-to-stock-pools`
- `/api/gantt/shouban30/pre-pool/sync-to-stock-pool`
- `/api/gantt/shouban30/pre-pool/sync-to-tdx`
- `/api/gantt/shouban30/pre-pool/clear`
- `/api/gantt/shouban30/pre-pool/delete`
- `/api/gantt/shouban30/stock-pool`
- `/api/gantt/shouban30/stock-pool/add-to-must-pool`
- `/api/gantt/shouban30/stock-pool/sync-to-must-pool`
- `/api/gantt/shouban30/stock-pool/sync-to-tdx`
- `/api/gantt/shouban30/stock-pool/clear`
- `/api/gantt/shouban30/stock-pool/delete`

已禁用的旧手动执行入口：

- `/api/daily-screening/schema`
- `/api/daily-screening/runs`
- `/api/daily-screening/runs/<run_id>`
- `/api/daily-screening/runs/<run_id>/stream`

仍保留但当前页面不再使用的旧辅助接口：

- `/api/daily-screening/actions/add-to-pre-pool`
- `/api/daily-screening/actions/add-batch-to-pre-pool`
- `/api/daily-screening/pre-pools`
- `/api/daily-screening/pre-pools/stock-pools`
- `/api/daily-screening/pre-pools/delete`

## 存储

正式真值在 `fqscreening`：

- `daily_screening_runs`
  - 运行审计
- `daily_screening_memberships`
  - 唯一键：`scope_id + code + condition_key`
- `daily_screening_stock_snapshots`
  - 唯一键：`scope_id + code`

页面正式只读取 `trade_date:<YYYY-MM-DD>` scope。

## 自动任务

- Dagster job：`daily_screening_postclose_job`
- Schedule：`daily_screening_postclose_schedule`
- Cron：工作日 `19:00`

这条任务负责生成每日选股正式结果，不再依赖页面手动触发；旧图任务 `job_daily_screening_postclose` 已从 Dagster definitions 移除。

## 当前边界

- `/gantt/shouban30` 仍是板块工作台；每日选股除了消费其读模型与缠论快照语义，也直接复用其共享工作区接口。
- 页面查询不会重新触发算法运行。
- API 仍保留旧执行接口，但当前页面不再使用。
- `market_flags` 仍基于全市场能力构建，但前端查询始终锚定 `base:union`。

## 部署/运行

- `freshquant/daily_screening/**` 改动后，重建 API Server。
- `morningglory/fqdagster/**` 改动后，重启 Dagster Webserver / Daemon。
- `morningglory/fqwebui/**` 改动后，重新构建 Web UI。

## 排障

### 页面能打开但没有条件目录

- 看 `/api/daily-screening/filters?scope_id=trade_date:<date>`
- 再看 `fqscreening.daily_screening_memberships` 是否已有对应 `scope_id`

### 页面有条件但查询为空

- 看 `/api/daily-screening/scopes/<scope_id>/summary`
- 再看 `daily_screening_stock_snapshots` 是否已有 `base:union` 对应股票快照
- 再确认是否设置了过严的 `higher_multiple / segment_multiple / bi_gain_percent` 阈值

### Dagster 没出正式结果

- 看 Dagster 中 `daily_screening_postclose_schedule` 是否在运行
- 看 `daily_screening_postclose_job` 最近一次 run 是否成功
- 再确认 `Shouban30` / Gantt 上游快照是否已就绪
