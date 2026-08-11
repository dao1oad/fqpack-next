# 每日选股

## 职责

`/daily-screening` 现在是 **CLX 基本面评价工作台**（Issue #570 重构，三区
布局），不再是“综合交集 / CLX 18 模型”的 tab 工作区，也不展示主体 K 线：

- ① CLX 基本面排序：全量 Stock pure-buy 按基本面排序（虚拟滚动、两级密度、
  筛选/排序/URL 持久化、星标收藏、跨日连续入选 ×N）；
- ② 标的基本面详情：首屏决策卡 + 手风琴分节，↑↓ 键盘切换保持分节态；
- ③ 池子统计分析：默认 4 图 + 折叠 4 图、全屏、单向下钻。

页面数据全部来自静态产物 `/data/clx-evaluator/**`（latest.json v2 →
clx-fundamental-ranking / fundamental-analysis / fundamental-snapshot /
fundamental-stats），不新增后端接口。底层 CLX 信号选择（S0000-S0017）与
基本面评价链见 `docs/current/modules/clx-daily-selection.md` 与
`docs/current/modules/clx-fundamental-evaluation.md`。

## 入口

- 前端路由
  - `/daily-screening`
- 前端页面
  - `morningglory/fqwebui/src/views/DailyScreening.vue`
- 前端状态/API
  - `morningglory/fqwebui/src/components/clx-workbench/ClxFundamentalRankingPanel.vue`
  - `morningglory/fqwebui/src/components/clx-workbench/ClxFundamentalDetailPanel.vue`
  - `morningglory/fqwebui/src/components/clx-workbench/ClxFundamentalStatsPanel.vue`
  - `morningglory/fqwebui/src/components/clx-workbench/clxFundamentalRankingLogic.mjs`
  - `morningglory/fqwebui/src/components/clx-workbench/clxFundamentalDetailLogic.mjs`
  - `morningglory/fqwebui/src/components/clx-workbench/clxFundamentalStatsLogic.mjs`
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

### 前端页面（CLX 基本面三区工作台）

页面结构：

- 顶栏：标题、排序结果时间 / 交易日 / 批次、CLX 状态与质量门 `StatusChip`、
  “刷新全部”；
- 质量门 amber 时顶部琥珀横幅（列出未通过门项）；
- 三区网格（40% / 38% / 22%）：
  - ① 排序列表：虚拟滚动（固定行高窗口化）、紧凑/舒适两级密度、筛选
    （行业多选 / 证据等级 / 仅风险 / 分区 / 单维等级下限 / 搜索 / 星标）、
    排序切换（综合 / 六维 / 风险，分区边界固定）、URL 状态持久化
    （filter/sort/selected/density）、跨日连续入选 ×N 徽章、星标收藏
    （localStorage `fq:clx-fundamental:stars`）、展开行指标明细、↑↓ / Enter /
    Esc 键盘导航；
  - ② 详情：首屏决策卡（快照条 / 一句话定位 / 六维评分卡 / 关键指标 /
    风险清单 / 三项优势 / 三项问题）+ 手风琴分节（业务结构、财务趋势、成长
    质量、资产负债、行业能力、估值情景、验证节点、证据溯源）；↑↓ 切换标的
    保持手风琴展开态；证据 D 级置灰 + “仅初步观察，估值暂停”；初评标的
    统一标注“本期初评”；
  - ③ 统计：KPI 卡、质量×估值散点、行业分布、六维等级分布（默认 4 图）+
    成长×盈利四象限、风险热力、证据覆盖、估值分位直方图（折叠 4 图）+ 全屏；
    点击行业条/散点只写列表筛选（单向下钻，不覆盖已选中标的）；
- 底部状态条：深析/初评/深析完成/证据 A+B/质量门/生成时间。

交互口径：

- 首次进入自动加载 `latest.json` → 排序与统计；无当日产物时显示空态；
- 列表点击行即出详情（本地静态 JSON，无分页请求）；
- 筛选、排序、选中与密度写入 URL query（`sort/q/industry/evidence/risk/
  tier/mingrade/star/selected/density`），可分享可收藏；
- 星标只存 localStorage，一键“★ 星标”筛选；
- 断点降级：<1280px 统计区移至底部；<960px 仅列表 + 详情抽屉
  （position: fixed）。

已移除（Issue #570）：三池工作区（`PoolWorkspacePanel`）、market_lane /
market_theme_id / market_fit_grade 等市场字段展示、CLX_18 导出与池子同步
入口（CLX 18 模型导入能力仍由 `ClxSelectionPanel` 在 Kline 页内承载）。

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
- `/api/gantt/shouban30/stock-pool/append`
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
- CLX 18 模型的“加入clx15分钟监控”调用 `/api/gantt/shouban30/stock-pool/append` 直接写 `stock_pools`，记录 `clx_scope_id / clx_asset_type / clx_model_keys` 等上下文，不经过 `pre_pools` 或 `must_pool`
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
- `/daily-screening` 是 CLX 基本面评价工作台（三区），数据来自
  `/data/clx-evaluator/**` 静态产物；旧 12 模型综合交集与独立 CLX 工作区
  页面已下线。`/clx-daily-screening` 仅为兼容 redirect 到
  `/daily-screening?tab=clx`（页面不按 tab 切换 UI）。
- `daily_screening_postclose_sensor`（旧综合交集链）继续等待自己的股票/Gantt
  上游合同；该链与基本面评价链互不参与。CLX 信号选择链的 stock/ETF marker
  各自 success 即启动本侧 partition，双侧只门控 CLX finalizer、正式发布和
  跨资产统计。
- 页面查询不会重新触发算法运行；CLX 基本面评价由
  `script/clx_eval_daily.ps1` 每日跑批（见
  `docs/current/modules/clx-fundamental-evaluation.md`）。
- 旧 `/api/daily-screening/**` 执行接口仍保留，但当前页面不再使用。

旧综合交集相关的排障条目（条件目录 / base:union / hot_reasons）只适用于仍
消费 `fqscreening` 的后端消费者；基本面工作台排障见
`docs/current/modules/clx-fundamental-evaluation.md`。

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
