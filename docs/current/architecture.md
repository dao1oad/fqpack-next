# 当前架构

## Guardian Grid 与三档止盈

- Guardian 买入 Grid 使用三条 BUY 价格与三档累计仓位上限
  `max_position_amounts`；四个价格区间分别受 CAP-1、CAP-2、CAP-3 和
  Position Management 单标的有效上限约束。
- 单次买入量取基础金额对应数量与剩余容量对应数量的较小值，不再使用
  2/3/4 倍率；`buy_active` 仅保留兼容审计，不参与买入准入。
- Guardian 新买单提交前复用订单管理撤单链处理同标的内部活动买单；存在
  等待态、外部单或撤单请求时，本 Tick 不提交新单。
- 当前 Guardian 与 `om_broker_orders` 运行面按单一已配置 XT 账户部署；XT
  回报会把 `account_id` 持久化到订单与 broker-order 读模型，并纳入 canonical
  broker identity。Guardian 活动买单查询仍在该单账户部署边界内按标的过滤；
  若未来同一运行实例承载多个券商账户，撤单查询与执行必须显式加入
  `account_id` 过滤，不能直接复用当前单账户编排。
- 三档止盈按触发时券商总仓位分别计算 1/3、1/2、全部，并受 open ledger
  与 `can_use_volume` 截断；来源分配先使用达价 Slice，不足部分从剩余数量
  最大的 Slice 补足。

## 总体分层

- 行情层
  - `freshquant.market_data.xtdata.*`
- 策略层
  - `freshquant.strategy.*`
  - `freshquant.signal.*`
  - `freshquant.clx_daily_selection.*`
- 交易执行层
  - `freshquant.order_management.*`
  - `freshquant.position_management.*`
  - `freshquant.tpsl.*`
- 展示层
  - `freshquant.rear.*`
  - `morningglory/fqwebui`
- 观测层
  - `freshquant.runtime_observability.*`
- 记忆层
  - `freshquant.runtime.memory.*`

## 记忆层

- 热记忆
  - 当前会话通过 `FQ_MEMORY_CONTEXT_PATH` 加载的 context pack
- 冷记忆
  - `runtime/memory/**` 中由 bootstrap / archive / retrieval 维护的长期记忆材料
  - 自由会话通过 `runtime/memory/scripts/bootstrap_freshquant_memory.py` 生成并加载 context pack
- 正式边界
  - 记忆层只提供上下文，不覆盖 GitHub、`docs/current/**` 与最新远程 `origin/main` / `main` 的正式真值
  - 涉及运行交付时，以最新远程 `main` 的正式 deploy 与 health check 为准
  - 所有代码更新的 PR + CI + merge gate 仍是交付收敛面的正式真值

## CLX 日线选股 fork-join 链

### 股票 partition

`stock_postclose_ready(success) -> clx_daily_selection_stock_sensor -> scheduled attempt -> owner/token running claim -> production_v1 CLX18 -> marker drift recheck -> fenced committing -> immutable stock partition`

### ETF partition

`etf_postclose_ready(success) -> clx_daily_selection_etf_sensor -> scheduled attempt -> owner/token running claim -> production_v1 CLX18 -> marker drift recheck -> fenced committing -> immutable ETF partition`

两条 partition 链并发且互不读取另一侧 marker。单侧失败、运行中或 marker 漂移只影响本侧；已经 completed 的另一侧 partition 按 `selection_key + content_hash` 复用。partition attempt 按 `scheduled -> running -> committing -> completed` 推进，claim 由 `claim_owner + claim_token + lease_expires_at` fencing；同一 attempt 的第二 executor 不进入计算，过期旧 worker 不能提交不可变输出。

### sensor 跨日追赶

stock、ETF 和 finalizer 三个 CLX sensor 都按 newest-first 扫描最近 5 个已完成交易日。交易日来自交易日历；本地时间未到 `15:05` 时当天不算完成，周末也不会推导出未来交易日。每个 sensor 每个 tick 最多派发一个 `RunRequest`：marker 缺失或计划为 `reuse/wait` 时继续检查更早日期，遇到 `active` 时停止本轮以避免并发重复，遇到 `run` 时立即返回。由此可在 D+1 找回延迟到达的旧日 marker、失败 partition 的下一 attempt，以及旧日失败 publication，同时不重复计算已完成侧。

### finalizer

`immutable stock partition + immutable ETF partition -> persisted finalization_attempt -> strict Dagster tag check -> finalizer contract check -> immutable final content -> owner/token publication claim -> clx_daily_selection_ready`

finalizer 只在两侧 completed 后运行。sensor 先持久化 `finalization_attempts` 的 trade date、batch id 和两个 partition id，每次 dispatch 使用独立 attempt/run key；job 必须按 `finalization_attempt_id` 读取该计划，并强校验所有 Dagster tags。finalizer 再校验同交易日、`production_v1 / switch_opt=1`、算法/数据/参数/schema/条件目录/线定义版本一致。任一当前 marker 缺失时只返回 waiting；marker 或 partition generation 漂移时不发布旧 failed/pending generation。final 内容与 ready marker publication 分离：publication 为 `pending/publishing/failed` 时公共 API 仍投影为 partial，只有 `published/not_required` 才进入默认完整结果；publication 也以 owner/token CAS 防止旧发布者覆盖新 claim，发布重试不重算 partition。ready marker 的 generation 使用规范 UTC 可排序键和不可变 `publication_id`：相同 publication id 重试幂等复读，迟到的旧 generation 被显式拒绝为 `stale_publication`，旧 batch 保持 publication failed，不能覆盖新 marker 或被标为 published。单侧完成只形成明确的 partial。

### 读链

`freshquant_clx_daily_selection -> /api/clx-daily-selection/* -> /daily-screening?tab=clx CLX master-detail 工作区 -> 当前 symbol/endDate K 线与详情 -> ECharts CLX marker series`

新链使用独立数据库、API 和 `clx_daily_selection_ready` marker，统一页面入口为 `/daily-screening?tab=clx`。页面采用高密度 master-detail 布局：左侧条件与交集结果，中间工作区，右侧标的详情；保留静态 JSON schema/API 与 `importGroupToTdx()` 能力。`/clx-daily-screening` 只把兼容 query 映射后重定向到该入口，不再挂载第二套页面状态；旧 `fqscreening` 与 `daily_screening_ready` 继续保持 12 模型链的原有语义。
## 当前行情复权边界

- Stock / ETF 线上读取统一由 `freshquant.data.qfq_reader` 解析 `quantaxis.qfq_ready` 指向的 active A/B 快照；reader 每次请求重新解析 marker，不缓存 collection pointer。
- `freshquant.market_data.xtdata.qfq` 以 XTData 日线 `preClose` 生成 Stock / ETF QFQ A/B 快照：
  - Stock：`stock_adj_qfq_a` / `stock_adj_qfq_b`
  - ETF：`etf_adj_qfq_a` / `etf_adj_qfq_b`
  - `quantaxis.qfq_ready` 以每个 `scope` 的单文档保存 `active_slot` 与两个槽位的快照元数据。
- writer 只构建 inactive slot，审计通过后再原子切换 `active_slot`；`worker`、人工 `build` 与 `rollback` 共用 `qfq_writer_locks` 的 scope 唯一 lease。回滚会先将仍需生效的 intraday override 重新绑定到目标 snapshot，再以 CAS 切换 marker；factor A/B 集合本身不改写。
- reader 要求 active slot 为 `ready`，并严格校验请求 bar 的日期覆盖、正因子、重复键、source exclusion 和 snapshot-bound intraday override；证明失败统一抛出 `QFQ_DATA_NOT_READY`，三条 Stock Kline API 统一返回 HTTP 503。
- Redis Kline key/payload 与 StrategyConsumer 常驻窗口绑定 effective adjustment version（active `snapshot_id` 加匹配的 override version）；版本变化时旧 cache miss、常驻窗口重载。
- 旧 `stock_adj` / `etf_adj` 不再是线上 reader 真值。
- 真实 Index 的日线、分钟线和实时合并固定使用 BFQ；Index 路径不读取 Stock / ETF 因子，实时数据读取 `freshquant.index_realtime`。

## 订单相关核心调用链

### 实时交易链

`XTData -> Guardian -> PositionManagement gate -> OrderManagement submit -> broker -> XT callback -> OrderManagement ingest -> Position/TPSL/Subject/Kline read models`

### 止盈止损链

`tick -> TpslTickConsumer -> TpslService -> OrderSubmitService -> broker -> XT callback -> OrderManagement ingest`

### 当前仓位链

`xt_account_sync.worker -> xt_positions -> pm_symbol_position_snapshots -> PositionManagement / SubjectManagement / TpslManagement / KlineSlim`

### 当前自动还款链

`xt_account_sync.worker -> pm_credit_asset_snapshots -> xt_auto_repay.worker -> query_credit_detail confirm -> XtQuantTrader.order_stock(CREDIT_DIRECT_CASH_REPAY, placeholder stock_code, LATEST_PRICE)`

### 当前持仓复盘链

`current xt_trades / OM ledger + om_execution_history_archive / position_review_evidence_archive -> position-review read model -> /api/position-review/* -> PositionReview / KlineSlim`

## 当前订单账本边界

### 券商真值层

- `xt_positions`
- `xt_orders`
- `xt_trades`

### 订单账本层

- `om_order_requests`
- `om_orders`
- `om_broker_orders`
- `om_order_events`
- `om_execution_fills`
- `om_trade_facts`

### 持仓解释层

- `om_position_entries`
- `om_entry_slices`
- `om_exit_allocations`

### 自动平账层

- `om_reconciliation_gaps`
- `om_reconciliation_resolutions`
- `om_ingest_rejections`

### 兼容层

- `om_buy_lots`
- `om_lot_slices`
- `om_sell_allocations`
- `freshquant.stock_fills`
- `freshquant.stock_fills_compat`

## 当前关键边界

- `xt_positions`
  - 定义当前券商仓位真值
- `xt_trades`
  - 定义当前可替换的券商成交快照
  - 读取时必须按 `symbol + side` 与内部执行事实交叉核对
- `om_execution_history_archive`
  - 持久保存复盘使用的规范化历史成交；成交基础身份固定为
    `broker_trade_id + symbol + side + trade_time + quantity + price`
  - 不同账户使用不可逆 `account_partition` 分开保存；不会因
    `broker_trade_id` 复用或 positions-only initialize 相互覆盖
- `position_review_evidence_archive`
  - 持久保存策略请求、订单关联、执行事实与持仓解释原始证据
  - 不参与 order-ledger purge，也不反向定义当前仓位
- `om_execution_fills + om_trade_facts`
  - 定义内部订单执行事实，并用于交叉核对 `xt_trades`
- `om_broker_orders`
  - 定义券商订单聚合视图，不单独作为历史成交数量真值
  - XT 回报归属优先使用严格 24 字符 `FQOM + 20 hex` correlation token；无
    token 时只接受完整 canonical identity：
    `account_id + trading_day + order_sysid`，或
    `account_id + trading_day + symbol + side + broker_order_id`
  - `broker_order_id`、`symbol/side` 或回报时间都不能单独证明内部订单归属；
    无法证明时创建 deterministic broker-only 记录或 fail closed
- `om_position_entries`
  - 定义系统可消费的持仓入口
- `om_reconciliation_*`
  - 只负责自动平账，不再伪造成 fake order / fake trade
- `stock_fills_compat`
  - 只做兼容投影，不再参与运行期真值判断

## 当前页面消费关系

- `OrderManagement`
  - 订单请求、内部订单、券商订单、成交事实
- `PositionManagement`
  - `券商仓位 / 账本仓位 / 对账状态`
- `SubjectManagement`
  - `entries + entry stoploss + must_pool + limit summary`
- `TpslManagement`
  - `entries + entry_slices + takeprofit + stoploss`
- `KlineSlim`
  - `entries + entry stoploss + guardian/takeprofit + 可选订单级交易复盘覆盖层`
  - CLX 左栏是完整选股工作区：读取选定 final/显式 partial scope，支持资产、模型、条件、方向、线关系、最少模型数和文本查询，并按服务端 cursor 追加结果
  - 点击左栏标的时更新当前 symbol/asset type，并把 `scope.tradeDate` 映射为 K 线与历史信号共同使用的 `endDate`
  - 左栏“筛选哪些标的”的模型/条件状态与右栏“显示哪些历史 marker”的模型/条件状态分别维护，切换任一侧都不静默改写另一侧
  - 中栏继续提供唯一 K 线主图；右侧工作台按 `production_v1` 历史响应控制 marker 可见性、时间轴和证据详情
  - CLX marker 由 renderer 生成独立 ECharts scatter series，并由 controller 处理点击、聚焦和 tooltip
  - `/clx-daily-screening` 兼容入口
  - 保留旧收藏和深链可达性，将 `scope_id / asset_types / model_keys / condition_keys / line_flags` 等兼容 query 映射为 `/daily-screening?tab=clx` 的 CLX 查询状态后重定向
  - 不挂载独立筛选页面，也不维护第二份 scope、筛选、选中标的或分页状态
  - 正式导航、人工操作和 Web 健康检查都以 `/daily-screening?tab=clx` 为准
- `PositionReview`
  - 当前 `xt_trades / OM ledger` 与两个只读历史档案的合并视图
  - 与 `KlineSlim` 共享订单级时间线投影：信号、订单聚合成交、数量对比和连续持仓使用同一口径
  - ClickHouse Trace 只作为可选判定上下文和运行观测跳转证据

## 当前持仓复盘口径

- `/position-review` 是只读工作台，覆盖所有存在可信历史成交的标的；当前持仓和已清仓标的不采用不同的成交真值口径。
- 复盘以策略请求或订单为判定单位；同一订单的逐笔成交只作为实际成交数量、价格和执行过程的下钻证据。
- 订单级时间线只输出聚合订单事件和连续 `position_series`：每个事件保留策略应有量、实际成交总量、加权成交均价、仓位前后值与数据质量；KlineSlim 不展示逐笔 fill。
- 信号到订单的可视关联只接受明确的 `request_id / internal_order_id / trace_id / intent_id` 键；缺少强关联时返回空信号并保留证据不足语义，不通过时间邻近推断。
- 订单判定固定为四态：
  - `PASS`：现有证据能够确认实际行为符合策略逻辑。
  - `FAIL`：现有证据能够确认实际行为偏离策略逻辑。
  - `INSUFFICIENT_EVIDENCE`：实际成交可确认，但策略上下文、持仓状态或关联证据不足以作确定判断。
  - `NOT_APPLICABLE`：人工、外部或其他不适用自动策略判定的交易。
- 证据置信度固定为 `HIGH / MEDIUM / LOW`，由券商成交、内部执行关联、策略上下文和持仓解释证据的完整程度共同决定；置信度不替代四态判定。
- ClickHouse Runtime Trace 不是成交或持仓账本真值。Trace 存在时可补充信号、门禁和链路上下文；Trace 缺失或 ClickHouse 不可用时，复盘 API 仍以 Mongo 中的成交与账本事实返回结果，并通过 `data_quality` 和置信度表达证据缺口。
- positions-only initialize 和 destructive order-ledger rebuild 在删除易失集合前先写两个历史档案；归档失败时清理中止。
- API 只返回不可逆账户分区，不返回原始券商账户号；无账户证据仅在唯一分区可确认时归并，多分区候选保持歧义而不伪造额外成交。
- 持仓复盘 API 不写入订单、持仓、策略配置或运行观测数据。

## 当前规则

- buy fill 默认按 broker order 聚合成一个 entry
- 对账补开的 `auto_reconciled_open` 若与相邻 open entry 满足同标的、同交易日、5 分钟内且价差不超过 0.3%，也会并入同一个 buy cluster
- stoploss 绑定对象是 `entry_id`
- odd-lot 不进入 `position_entries`
- odd-lot 进入 `om_ingest_rejections`
- XT 自动还款当前只处理普通融资负债；盘中低频巡检只把快照当候选信号，真正提交前始终再查一次实时 `credit_detail`

## 当前部署边界

- `freshquant/market_data/**`
  - 重启 XTData producer / consumer
  - 重启 `xtdata_adj_refresh_worker` 与 `fqnext_xtdata_qfq_worker`
- `morningglory/fqdagster/**` / `morningglory/fqdagsterconfig/**`
  - 重部署 Dagster webserver / daemon
- `freshquant/data/index.py` / `freshquant/quote/index.py` / `freshquant/chanlun_service.py` / `freshquant/chanlun_structure_service.py`
  - 重建 API Server
- `freshquant/order_management/**`
  - 重建 API Server
  - 重启 `xt_account_sync.worker`
  - 重启 `xt_auto_repay.worker`
  - 重启 `tpsl.tick_listener`
- `freshquant/position_management/**`
  - 重建 API Server
  - 重启 `xt_account_sync.worker`
- `freshquant/xt_auto_repay/**`
  - 重启 `xt_auto_repay.worker`
- `freshquant/tpsl/**`
  - 重建 API Server
  - 重启 `tpsl.tick_listener`
- `morningglory/fqwebui/**`
  - 重建 Web UI
- `freshquant/clx_daily_selection/**` 或 `freshquant/rear/clx_daily_selection/**`
  - 重建 API Server
  - 重启 Dagster Webserver / Daemon，使 partition job 与 finalizer 加载同一服务实现
- `morningglory/fqdagster/**`
  - 重启 Dagster Webserver / Daemon
- `morningglory/fqcopilot/**`
  - 重新构建并安装原生扩展
  - 重建/重启消费该扩展的 API 与 Dagster 运行面
