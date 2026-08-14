# 当前总览

## 项目定位

FreshQuant 当前阶段以“当前系统事实收敛、潜在 bug 修复、部署与排障可维护”为主。正式文档只描述当前实现，不记录迁移过程。

## 当前已落地能力

- HTTP API 已统一挂载 `stock / gantt / daily-screening / clx-daily-selection / order / position-management / position-review / subject-management / tpsl / runtime / system-config`
- 独立 `clx_daily_selection` 已提供 S0000-S0017 的 `production_v1 / switch_opt=1` 日线计算、批次查询与解释证据 API；它不复用旧 12 模型 `/daily-screening` 的 scope 或 marker
- CLX 盘后链采用 stock/ETF partition fork-join：任一侧 ready marker success 即启动本侧计算，partition 由 owner/token lease fencing；三个 sensor newest-first 追赶最近 5 个已完成交易日；双侧完成只门控持久化 finalization attempt、正式发布和跨资产统计，单侧完成可明确展示 partial
- Guardian、订单管理、仓位管理、TPSL 已形成分层交易链
- `PositionManagement / KlineSlim / RuntimeObservability / SystemSettings` 已统一为 workbench 风格页面
- 独立「持仓列表」页（`/stock-position-list`，顶栏第二组入口）：表格含「底仓」「做T」双账本列（底仓靛蓝 / 做T 琥珀，数据来自 `/api/get_stock_position_list` 的 `base_quantity/base_amount/t_quantity/t_amount`）
- 仓位管理-持仓账本 tab（聚合买入列表 + 切片明细）与相关订单 tab（订单列表 + 订单详情基础信息）均展示双账本「账本」列：entry/slice 读取 `position_type`（缺失按底仓），订单行由后端按 `strategy_context` 推导 `ledger`（base/t/-）
- `/daily-screening?tab=clx` 是 CLX 18 模型正式工作区：在每日选股页内提供批次状态、完整筛选条件、cursor 结果列表、统计、详情、看图跳转和导入通达信；`看图` 进入 `/kline-slim` 并以所选 scope 交易日同步 K 线 `endDate`
- `/clx-daily-screening` 只保留兼容深链并重定向到 `/daily-screening?tab=clx`，不再挂载第二套筛选页面
- `PositionReview` 已通过顶部“持仓复盘”导航和独立 `/position-review` 路由提供只读历史交易复盘；当前持仓与已清仓标的使用同一套全量成交、策略判定和图表口径
- `PositionReview` 采用单页左右栏结构（不再用标签切换）：左栏为组合总览与标的复盘共用的持仓列表，右栏纵向联动“组合总览”与“标的复盘”；组合总览提供持仓市值、成本、浮盈、已实现盈亏、月度成交额与标的贡献 Top N，并按 QMT 口径（净资产 = 总资产 − 总负债）展示账户净资产曲线（日/周/月可切换、交易发生的周期标注交易点）；标的复盘以持仓成本价曲线（Y 轴 = 成本价，X 轴从首个持仓/订单点开始）为主，点击 marker 固定订单并查看完整条件阈值证据
- `SubjectManagement` 独立路由已移除，相关读模型与行内编辑能力已并入 `PositionManagement` 中栏“标的总览”
- 订单账本已经切到 `broker order / execution fill / position entry / reconciliation` 主语义
- XT 自动还款已经独立为宿主机 `xt_auto_repay.worker`，只处理普通融资负债，并通过 `/system-settings -> XTQuant` 暴露开关与留底现金
- PositionManagement 已改为统一两栏工作台：左栏当前仓位状态 + 高密度标的总览，右栏选中标的工作区 + 最近决策
- `/system-settings` 已补入仓位管理 inventory 去重后的只读补充项
- 独立 `/order-management` 路由已移除；订单列表、订单详情与对账排障统一收口到 `/position-management`
- 独立 `/tpsl`、`/futures-control`、`/stock-cjsd` 路由已移除
- 止损触发功能（全仓止损 + 单笔止损）已随 Issue #603 整体下线，三条 BUY 抄底线承担补仓
- `stock_fills` 旧接口仍保留，但底层优先读取 entry ledger

## 当前目录职责

- `freshquant/`
  - API、CLI、CLX 日线选股、订单、仓位、TPSL、运行观测与行情处理
- `morningglory/fqwebui/`
  - Web UI
- `morningglory/fqdagster/`
  - Gantt / 筛选相关读模型作业
- `runtime/memory/`
  - memory bootstrap 与 context pack
## 当前真值

- 代码真值
  - 最新远程 `origin/main`
- 运行真值
  - 最新远程 `main` 的正式 deploy + health check
- 运行真相源：最新远程 `origin/main` 的正式 deploy 结果
- 文档真值
  - `docs/current/**`
- CLX 日选 partition 真值
  - `freshquant_clx_daily_selection.partitions` 及其 `memberships / snapshots / model_stats`
- CLX finalizer dispatch 真值
  - `freshquant_clx_daily_selection.finalization_attempts` 中持久化的 batch generation 与两个 partition id
- CLX 默认完整批次真值
  - `freshquant_clx_daily_selection.batch_statuses` 中 `is_final=true` 且 `publication.status in [published, not_required]` 的最新 batch
  - 普通 partial 与 publication `pending/publishing/failed` 仅作显式中间态，不替代正式发布
  - ready marker publication 还必须通过规范 UTC `generation_order + publication_id` CAS；迟到旧 generation 的 batch 保持 `failed/stale_publication`
- 券商仓位真值
  - `xt_positions`
- 券商成交与持仓复盘历史真值
  - 当前快照：`xt_trades`
  - 持久历史（仅写入侧留存，复盘读模型不读取）：`om_execution_history_archive`
- 内部执行交叉核对真值
  - 当前 `om_execution_fills / om_trade_facts`
  - 持久策略与持仓证据（仅写入侧留存，复盘读模型不读取）：`position_review_evidence_archive`
- 内部持仓解释真值
  - `om_position_entries`

## 当前工作流

- 轻量更新允许直接走 `feature branch -> PR`
- 高影响、破坏性变更应先建 GitHub Issue，再进入编码与部署
- 本地会话完成后先合并到远程 `main`，再执行正式 deploy 与 health check

## 当前维护重点

- 保持 `xt_positions`、订单账本、TPSL、前端读模型的一致性
- 保持 docs、deploy、health check、cleanup 与合并结果同步
- 保持 stock/ETF marker、最近 5 个已完成交易日 catch-up、partition owner/token fencing、独立 attempt/漂移处理、不可变 partition、finalization attempt 与 generation-aware publication CAS 合同一致
- legacy `buy_lot / stock_fills / stock_fills_compat` 已随 6b 拆表删除（Issue #605），运行期仅 V2 单路径

## 模块入口

- [CLX 日线选股](./modules/clx-daily-selection.md)
- [Kline Web UI](./modules/kline-webui.md)
- [每日选股（旧 12 模型链）](./modules/daily-screening.md)
