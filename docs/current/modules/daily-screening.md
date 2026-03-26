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
  - `fqdagster.defs.jobs.daily_screening`
  - `fqdagster.defs.schedules.daily_screening`
  - `fqdagster.defs.sensors.postclose`

## 正式链路

### Dagster 盘后链路

`stock_postclose_ready + gantt_postclose_ready -> daily_screening_postclose_sensor -> daily_screening_context(fq_trade_date) -> upstream_guard -> universe -> cls / hot_30 / hot_45 / hot_60 / hot_90 -> base_union -> market_flags_snapshot -> near_long_term_ma / quality_subject / credit_subject / shouban30_chanlun_metrics / chanlun_variants -> snapshot_assemble -> publish_scope -> daily_screening_ready`

### 页面查询链路

`scopes/latest + filters + scope_summary -> 条件组合 -> /api/daily-screening/query -> 结果列表 -> /api/daily-screening/stocks/<code>/detail`

## 当前实现

### 条件模型

前端统一使用 `condition_key` 做交集，不再使用旧的“来源之间交集、来源内并集”页面语义。

当前条件分组：

- `CLS 形态分组`
  - 后端 membership 仍按 `cls:S0001` 到 `cls:S0012` 落库
  - 页面把 12 个模型收敛成 5 个中文分组
  - 单个分组内部多个模型取并集；多个 CLS 分组之间多选也取并集
  - CLS 分组结果再与热门窗口、市场属性、 `chanlun` 、日线缠论涨幅等其他条件继续取交集
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

页面首次进入、切换 scope、点击“重置筛选”后，默认都会启用这组筛选；用户仍可手动关闭。

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
- 标题区右侧的工作台总说明标签行
- 条件分组勾选
- 页头 `每日选股` 的工作说明下方直接放 `Scope` 下拉；左侧筛选面板不再重复展示独立 `Scope` 卡片，也不再显示“筛选工作台”标题和说明
- `基础池（并集）`
  - `CLS 模型分组`
  - `热门窗口`
- `交集条件`
  - `市场属性`
  - `chanlun 周期`
  - `chanlun 信号`
- 左侧筛选工作台自带纵向滚动；桌面端页面本身不再依赖浏览器纵向滚动，空间不足时改为面板内部滚动
- 全市场搜索框
  - 支持按标的代码或名称做模糊搜索
  - 输入后直接覆盖中间交集列表
  - 清空后恢复当前 scope 下的基础池/交集结果
- 每个筛选分组表头的悬浮说明提示
- `日线缠论涨幅` 总开关和默认阈值输入
- 交集结果、共享工作区、历史热门理由统一使用 `/runtime-observability` 同风格的 `runtime-ledger` 表格样式
- 交集列表改成“内部滚动 + 分页”；桌面端当前固定每页 8 条，用来压缩首屏高度并保持工作区可见
- 交集列表左侧的 `全部加入pre_pools`
- 交集列表单行 `加入 pre_pools`
- 共享工作区
  - `pre_pools`
  - `stock_pools`
  - `must_pools`
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
- 页面默认带着“融资标的 + 日线缠论涨幅”参与筛选
- 页面首次进入、切换 scope、点击“重置筛选”后，都会回到这组统一默认条件
- 交集列表分页只影响显示；“全部加入 pre_pools”仍然以当前完整交集结果为准，不只处理当前页
- 当前结果表达式会明确展示：CLS 分组内部和分组之间用并集语义，和其他筛选条件再取交集
- 全市场搜索是覆盖模式，不和左侧勾选条件叠加；搜索结果会直接显示到中间列表中
- 交集列表支持批量加入 `pre_pools`，也支持单条直接加入 `pre_pools`
- 工作区 `pre_pools` / `stock_pools` / `must_pools` 当前都读取共享去重真值；同一个 `code` 只显示一行，并明确展示 `sources / categories`
- 工作区会额外展示 `must_pools` 页签，并直接复用现有必选池读写接口
- `must_pools` 继续按“单 `code` 单主记录”展示；记录内部会保留 `sources / categories / memberships`
- `must_pools` 顶层 `category` 现在是兼容摘要字段：优先 `manual_category`，否则按 `memberships` 主来源推导
- `must_pools` 页签增加 `集合` 列，显示当前摘要 `category`
- `must_pools` 页签支持单条按 `code` 删除整条记录，也提供“同步到通达信”“清空”按钮；两个动作都以当前共享 `must_pool` 全量集合为真值并完整覆盖 `30RYZT.blk`
- 工作区 `分类 / 上下文` 列优先展示聚合 `categories`；如果同时存在板块信息，会在同格补充板块上下文
- 点击交集列表或工作区中的任一标的，右侧都复用 `/api/daily-screening/stocks/<code>/detail` 展示完整详情
- 右侧详情区删除独立“日线缠论涨幅”卡片，改成紧凑条件卡片区，把更多高度留给“历史热门理由”
- 如果当前标的不在基础池，但全市场存在该股票且仍有历史热门理由，详情区仍会展示基础信息、历史热门理由和“最近一次在基础池”的时间
- `历史热门理由` 的悬浮提示卡复用 `/gantt/shouban30` 的 `Shouban30ReasonPopover` 样式
- 页面主工作区改为弹性高度布局；桌面端在 100% 缩放下应尽量让交集列表、工作区和右侧详情同时留在首屏内

### Dagster 节点 helper

`DailyScreeningService` 现在暴露可供 asset 调用的显式方法：

- `build_universe()`
- `build_cls_memberships()`
- `build_hot_window_memberships()`
- `build_market_flag_memberships()`
- `build_chanlun_variant_memberships()`
- `build_shouban30_chanlun_metrics()`

盘后资产当前额外具备两条编排约束：

- `daily_screening_context` 优先读取 sensor 注入的 `fq_trade_date`
- `daily_screening_upstream_guard` 只接受同一 `trade_date` 的 `stock_postclose_ready` 和 `gantt_postclose_ready`

## 当前接口

前端主路径使用：

- `/api/daily-screening/scopes`
- `/api/daily-screening/scopes/latest`
- `/api/daily-screening/filters`
- `/api/daily-screening/scopes/<scope_id>/summary`
- `/api/daily-screening/query`
- `/api/daily-screening/stocks/search`
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
- `/api/gantt/shouban30/must-pool/sync-to-tdx`
- `/api/gantt/shouban30/must-pool/clear`
- `/api/get_stock_must_pools_list`
- `/api/delete_from_must_pool_by_code`

当前工作区返回口径：

- `/api/gantt/shouban30/pre-pool` 返回共享 `stock_pre_pools` 的去重列表，不再只看 `category=三十涨停Pro预选`
- 每行会携带 `sources / categories / memberships`
- `/api/gantt/shouban30/stock-pool` 也会返回并展示 `sources / categories / memberships`
- 从 `pre_pools` 加入 `stock_pools` 时会保留来源与分类 provenance；同 code 已存在时会补齐这些字段
- `/api/get_stock_must_pools_list` 返回共享 `must_pool` 的去重列表，并带上 `manual_category / sources / categories / memberships / workspace_order_hint`
- 从 `stock_pools` 加入 `must_pool` 时会 merge provenance，不再把 `category` 固定写成单一常量
- `/api/gantt/shouban30/pre-pool/delete` 按 `code` 删除整条共享记录
- `/api/delete_from_must_pool_by_code` 也按 `code` 删除整条 `must_pool` 主记录，不提供 membership 级删除
- `/api/gantt/shouban30/must-pool/sync-to-tdx` 与 `/api/gantt/shouban30/must-pool/clear` 会按 `workspace_order_hint` 输出 `must_pool`，缺失时回退 `updated_at / created_at / datetime desc`

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
- Sensor：`daily_screening_postclose_sensor`
- 触发条件：
  - `stock_postclose_ready(trade_date)` 已成功
  - `gantt_postclose_ready(trade_date)` 已成功
  - `daily_screening_ready(trade_date)` 尚未存在
- Legacy schedule：`daily_screening_postclose_schedule`
  - 仍保留定义，但默认 `STOPPED`，只作手工兜底，不参与正式链路

这条任务负责生成每日选股正式结果，不再依赖页面手动触发；运行成功后会写入 `dagster_pipeline_markers.daily_screening_ready`。

## 当前边界

- `/gantt/shouban30` 仍是板块工作台；每日选股除了消费其读模型与缠论快照语义，也直接复用其共享工作区接口。
- 页面查询不会重新触发算法运行。
- API 仍保留旧执行接口，但当前页面不再使用。
- `market_flags` 仍基于全市场能力构建，但前端交集查询始终锚定 `base:union`。
- 全市场搜索接口不锚定 `base:union`；它只负责全市场模糊匹配，并在命中当前 scope 快照时叠加当前 scope 的缠论指标与市场属性字段。

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

### 工作区点开标的详情返回 `stock detail not found`

- 先看 `/api/daily-screening/stocks/<code>/detail?scope_id=trade_date:<date>`
- 如果该股票当前不在基础池，接口现在会回退到全市场股票主数据，并继续返回 `hot_reasons`
- 再看返回里的 `base_pool_status.last_seen_trade_date`
  - 有值：说明只是当前 scope 不在基础池，页面应显示“最近一次在基础池”的时间
  - 空值：说明既不在当前基础池，也没有命中过往 `trade_date:*` scope 的 `base:union`

### Dagster 没出正式结果

- 先看 `daily_screening_postclose_sensor` 最近一次 evaluation 是否命中目标 `trade_date`
- 看 `dagster_pipeline_markers` 里是否已有同一 `trade_date` 的 `stock_postclose_ready` / `gantt_postclose_ready`
- 看 `daily_screening_postclose_job` 最近一次 run 的 tag 是否带 `fq_trade_date`
- 再确认 `Shouban30` / Gantt 上游快照是否已就绪
