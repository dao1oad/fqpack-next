# 订单管理

## 职责

订单管理是交易链的账本与执行事实层，当前负责：

- 统一受理 API、CLI、Guardian、TPSL 的下单/撤单请求
- 维护 `request -> internal order -> broker order -> execution fill` 主链
- 基于成交聚合生成 `position entry / entry slice / exit allocation`
- 基于券商仓位差额维护 `reconciliation gap / resolution`
- 通过独立的 `xt_auto_repay.worker` 承接普通融资负债自动还款，并复用现有 broker 提交链
- 为 TPSL、SubjectManagement、KlineSlim、PositionManagement 提供 entry 级读模型
- 为旧接口保留 `stock_fills` 兼容投影，但兼容投影不再参与运行期真值判断

## 入口

- HTTP
  - `/api/order/submit`
  - `/api/order/cancel`
  - `/api/stock_order`
  - `/api/order-management/orders`
  - `/api/order-management/orders/<internal_order_id>`
  - `/api/order-management/entries/<entry_id>`
  - `/api/order-management/stats`
  - `/api/order-management/stoploss/bind`
- CLI
  - `python -m freshquant.cli om-order submit ...`
  - `python -m freshquant.cli om-order cancel ...`
  - `python -m freshquant.cli stock.fill rebuild --code <symbol>`
  - `python -m freshquant.cli stock.fill rebuild --all`
  - `python -m freshquant.cli stock.fill compare --code <symbol>`
  - `python -m freshquant.cli guardian.sell simulate --code <symbol> --signal-price <price>`
- 核心服务
  - `freshquant.order_management.submit.service.OrderSubmitService`
  - `freshquant.order_management.read_service.OrderManagementReadService`
  - `freshquant.order_management.tracking.service.OrderTrackingService`
  - `freshquant.order_management.ingest.xt_reports.OrderManagementXtIngestService`
  - `freshquant.order_management.reconcile.service.ExternalOrderReconcileService`

当前已经删除 `/api/order-management/buy-lots/<buy_lot_id>`；止损绑定接口只接受 `entry_id`。

## 当前账本边界

### 券商真值

- 当前仓位真值只认 `xt_positions`
- `xt_account_sync.worker` 对空快照或严重缩水且与同轮 `credit_detail.market_value` 明显冲突的 `xt_positions` 会先 quarantine；被隔离的快照不会覆盖 `xt_positions`，也不会进入自动平账
- 小账户（`1-2` 个 symbol）如果出现“symbol 没清空、但数量和估值同时严重缩水，而 `credit_detail.market_value` 仍显著为正”的快照，当前也会 quarantine
- `xt_account_sync.worker` 遇到 quarantine 的 `positions` 快照会显式打 warning，便于运行面第一时间发现真值冻结
- 当前委托/成交回报真值只认 XT callback 与 `xt_account_sync.worker` 增量刷新

### 破坏性 rebuild 治理

- 破坏性 `order-ledger rebuild` 只能由 broker truth 驱动，primary truth 只允许 `xt_orders`、`xt_trades`、`xt_positions`
- `om_*`、`stock_fills`、`stock_fills_compat` 只能作为迁移期兼容投影或排障线索，不能作为 rebuild 主输入
- rebuild 默认拒绝用空 `xt_positions` 快照去 flatten 非空账本；只有显式允许空快照 flatten 时，才会把空 `xt_positions` 视为券商已清仓
- 初始化向导的 runtime bootstrap 当前走 `xt_positions`-only destructive rebuild 变体：先 purge order-ledger rebuild 边界内的旧账本集合，再按券商当前持仓快照重建 V2 账本，并刷新 `stock_fills_compat`
- 这类破坏性 rebuild 在编码前必须先建立 GitHub Issue，写清影响面、验收标准与部署影响

### OM 主账本

- `om_order_requests`
  - 内部下单意图
  - `ledger_intent` 必填（buy/sell）：`base` / `t` / `mixed` / `-`，缺失
    fail-closed 拒单；TPSL（买入线/止盈→`base`、止损→`-`）、Guardian
    （`new_open`→`base`、`holding_add`→`t`、做T卖出→`t`）、手动/网页
    （买→`base`、卖→`-`）全写入方在提交时显式声明
- `om_orders`
  - 兼容期内部订单壳；`filled_quantity` 死字段已退役，成交数量真值统一在
    `om_broker_orders` 聚合
- `om_broker_orders`
  - 券商订单聚合，维护 `requested_quantity / filled_quantity / avg_filled_price / fill_count`
- `om_execution_fills`
  - 真实券商成交 fill，以 `execution_identity` 原子幂等写入
  - XT canonical execution identity 固定包含
    `account_id + trading_day + symbol + side + broker_trade_id`；
    `broker_trade_id` 不能跨账户或跨交易日单独去重
- `om_trade_facts`
  - 兼容期成交事实镜像，仍保留给旧读链和部分排障
- `om_position_entries`
  - 系统持仓入口真值，供 TPSL/Subject/Kline/持仓解释层消费；当前 buy 侧默认落为保守聚合后的 `buy_cluster`
- `om_entry_slices`
  - entry 的 Guardian 切片；当前按聚合后的 entry 重新按 `50000` 口径切片
  - `arrange_entry` 按 `price × grid_interval` 乘法递增、单格股数
    `int(lot_amount / price / 100) * 100`（最小 100 股）切分；当整手（100 股）
    金额已超过 `lot_amount`（价格过高、网格不再有意义的细分粒度）时，剩余量
    全部并入最后一格，保证 `Σslice == entry` 守恒、价格有界且终止（避免低价
    高量持仓产生 ¥10^7~10^14 级幻影切片或 RecursionError）
  - 切片价格上限固定为 `round(entry_price * 20, 2)`（买入价 × 20）：当
    `grid_interval` 算出的下一档价格将超过该上限时，剩余数量全部并入当前格并
    终止递归，不再生成任何超过 20 倍买入价的切片；该上限与“整手金额超过
    `lot_amount` 即并入”规则独立，任一命中都执行 tail-merge
- `om_exit_allocations`
  - 卖出对 entry / slice 的分摊结果
  - 逐笔账本真值：`position_type`（base/t）；审计键 `internal_order_id`
    必填（broker-only 卖单也携带，`request_id` 可空），`exit_trade_fact_id`
    关联 `om_trade_facts.trade_fact_id` 做回溯
- `om_reconciliation_gaps`
  - 券商仓位与账本持仓解释之间的差额
- `om_reconciliation_resolutions`
  - 差额的自动收敛结果
- `om_entry_stoploss_bindings`
  - entry 级止损绑定
- `om_ingest_rejections`
  - 进入 XT ingest 但不允许进入主账本的拒绝记录

### legacy / 兼容集合

- `om_buy_lots`
- `om_lot_slices`
- `om_sell_allocations`
- `om_external_candidates`
- `om_stoploss_bindings`
- `freshquant.stock_fills`
- `freshquant.stock_fills_compat`

这些集合仍存在于迁移期，但不再定义运行期真值。`stock_fills_compat` 当前只作为 legacy mirror / adapter 输出，镜像口径已经切到 open `position_entries`。

## 当前数据流

### 下单

`submit_order -> credit mode resolve -> position gate -> om_order_requests / om_orders / om_broker_orders / om_order_events -> STOCK_ORDER_QUEUE -> broker`

内部订单在受理时生成并持久化严格 24 字符 `FQOM + 20 hex` correlation token；
broker 把该 token 放入既有 XT `order_remark` 参数槽。五档市价保护仍按买入
`price × 1.008`、卖出 `price × 0.992` 传入，`order_stock()` 参数及顺序不变。
XT 返回 `None/0/负订单号` 时订单标记为 `FAILED + submit_failed`，puppet 不
sleep、不重新入队，也不自动重复提交相同券商委托。

订单级账本归属只由 `LedgerResolver`
（`freshquant/order_management/ledger_resolver.py`）判定：读
`om_order_requests.ledger_intent`（+ broker-only 无请求买单显式归 `base`），
不读取 `guardian_sell_sources` / `guardian_buy_grid` / `buy_ledger` 参与归属
判断；跨 base/t 的分摊卖单订单级返回 `mixed`，逐笔真值在
`om_exit_allocations.position_type`。

订单列表/详情的 allocations 关联按 `request_id` 或 `internal_order_id`
两路批量读取（`repository.list_exit_allocations_for_requests(request_ids,
internal_order_ids)`，单次 `$or` 查询，避免 N+1）；broker-only 卖单的
allocations 只携带 `internal_order_id`，由该路命中。
订单详情响应中的 `exit_allocations` 与其余字段一致，全部经
`_sanitize_document` 清除 Mongo `_id`（`ObjectId` 不进入 JSON 响应）。

当前信用账户买单的运行期语义已经固定为：

- submit 阶段若解析出 `credit_trade_mode_resolved=finance_buy`，broker 执行桥会在真正发往 XT 前补查 `credit_detail`
- 运行期会把 `credit_available_bail_balance / credit_available_amount` 一并透传到 broker host，供执行前资金校验与排障使用
- `finance_buy` 的执行前资金校验当前只看 `available_bail_balance >= price * quantity + fee`
- 普通现金买入与信用担保品买入仍按 `asset.cash - asset.frozen_cash` 校验
- 若策略买单在 broker host 本地预提交阶段就被跳过或失败、没有形成真实 broker order，Guardian 之前写入的 `buy:{symbol}` 冷却会立即回收，不再保留误导性的 15 分钟冷却

Guardian 卖出请求当前会把本次卖量对应的来源入口计划一起写入 `om_order_requests.strategy_context.guardian_sell_sources`：

- `version = 2`
- `requested_quantity / submit_quantity / profitable_fill_count`
- `slices[] = { entry_id, entry_slice_id, quantity, guardian_price, threshold_price }`
  - 精确执行合同：每个来源 slice 一行，携带 `entry_slice_id`，只包含达到独立
    止盈阈值的 slice
- `entries[] = { entry_id, quantity }`
  - 按 entry 聚合后的唯一行（同一 `entry_id` 只出现一次），供旧读链/复盘使用
- 守恒：`sum(slices.quantity) == sum(entries.quantity) == submit_quantity`

这组来源入口语义当前同时用于两条卖出落账链：

- XT `trade` 回报正常进入 ingest 时，sell fill 按请求级剩余来源预算做 `exit_allocation`
- XT `trade` 回报缺失、系统只能退回 `xt_positions delta` 自动平账时，sell gap 也优先按这组来源入口扣减

这样“本次卖出实际是按哪些买入入口算出来的”会在正常成交链和差额收敛链保持同一套 entry 语义。
`guardian_sell_sources` 当前只作为分配书签/审计快照，不再参与账本归属判定。

历史 `version=1` 请求（只有 `entries[]`、无 `entry_slice_id`）仍被兼容：按
entry 级剩余预算分配，不回退到全量 open slice 猜测。

`相关订单` 列表/详情的账本列统一走 `LedgerResolver`：

- 买：`ledger_intent`（`base` / `t`）；broker-only 手动买入显式 `base`
- 卖：`ledger_intent`（`base` / `t` / `-` / `mixed`）；分摊卖单（分配证据
  跨 base/t）订单级返回 `mixed`，禁止单值；stoploss 声明 `-`
- 存量缺失 `ledger_intent` 的请求行显式标记 `ledger_intent_missing`，不做
  隐式推断（回填工具：
  `script/maintenance/backfill_ledger_intent.py`）
- `om_orders.filled_quantity` 死字段已清除（回填工具 `$unset`）；
  `om_broker_orders.state` 由回填按对应 `om_orders` 终态 +
  `filled_quantity/requested_quantity` 经 `OrderStateService` 收敛
  （终态不回退；如 filled=requested → FILLED）
- 存量 exit allocations 缺失 `internal_order_id` 时，回填经
  `exit_trade_fact_id` 唯一关联 `om_trade_facts.trade_fact_id` 回填，
  无法唯一关联则 fail-closed 停止

### 撤单

`cancel_order -> om_order_requests(cancel) -> om_orders / om_broker_orders state update -> STOCK_ORDER_QUEUE -> broker`

### XT order callback

`XT order callback -> normalize_xt_order_report -> OrderTrackingService.ingest_order_report_with_meta -> om_orders / om_broker_orders / om_order_events`

### XT trade callback

`XT trade callback -> normalize_xt_trade_report -> OrderTrackingService.ingest_trade_report_with_meta -> om_execution_fills / om_trade_facts / om_broker_orders aggregate refresh -> om_position_entries / om_entry_slices / om_exit_allocations -> stock_fills_compat mirror sync`

当前写链规则：

- XT 回报归属优先按 FQOM token，其次按完整 canonical broker identity；
  `broker_order_id`、价格、数量或时间邻近都不能作为猜测归属依据
- 无法匹配内部订单、但 canonical identity 完整的 XT order/trade 使用稳定的
  `ord_broker_*` broker-only owner；身份不完整则 fail closed
- 首笔成交固定按 `claim/move -> execution fence -> trade fact/execution fill -> broker aggregate CAS`
  写入；broker-only owner promotion 与首笔成交在同一
  `om_broker_orders` fence/CAS 上竞争
- existing-owner claim 的重领/合并只更新 owner 与不可变身份，不覆盖既有订单状态或
  成交聚合；状态更新保持 owner 不变，成交聚合使用 `aggregate_revision`
  compare-and-set，旧回报不能回滚新聚合
- broker-order key move 的 source delete CAS 失败时会有界重读、合并并收敛到
  单条 target；这里是数据库收敛重试，不是重复券商委托
- 若 `broker_order_id` 已在 submit 成功阶段绑定到内部订单，trade callback 当前仍会继续进入 `ingest_trade_report()`；`ExternalOrderReconcileService` 只负责补齐 trace/request/internal order 上下文与 reconcile 侧 runtime event，不再把这类回报提前短路
- buy fill 先按 `broker_order_key` 收口成 buy execution group，再按保守规则归并进 `buy_cluster` entry
- `OrderStateService`（`freshquant/order_management/tracking/order_state.py`）
  收敛订单状态写入口：`FILLED` / `CANCELED` 终态后状态不回退，迟到 order /
  trade 回报只吸收状态并写 `late_order_report_after_terminal` /
  `late_trade_after_terminal` 告警事件；迟到成交事实照常落账不丢弃；broker
  聚合不再被 trade 回调无条件覆写为 `PARTIAL_FILLED`（终态单不回退，避免
  `_PENDING_BUY_STATES` 卡死占用买入容量）
- `buy_cluster` 归并规则当前固定为：
  - 同一 `symbol`
  - 同一北京时间交易日
  - `buy` 侧
  - 与 cluster 首成员时间差 `<= 5 分钟`
  - 成交均价偏差 `<= 0.3%`
  - 已发生卖出扣减的 entry 不再接受新的 buy order 合并
  - `#571`：先解析归属（`ledger_intent` / broker-only→`base`）再聚类，
    禁止跨账本聚合；`aggregation_members[]` 逐成员携带
    `position_type`（A6 可审计）
- 同一 broker order 的多笔 fill 会更新同一个聚合成员，而不是继续生成多条 entry
- `#582`：buy entry 聚合以 **canonical `broker_order_key`**（trade_fact 携带）为
  整单锚点——entry 数量取 `om_broker_orders.filled_quantity` 整单口径，多笔 fill
  只刷新同一聚合成员；找不到 broker order 聚合时 fail-closed 写
  `om_ingest_rejections.reason_code=broker_order_missing`，不生成 entry（由
  reconcile gap + auto-open 收敛）；历史 entry 聚合成员键若为
  `internal_order_id`（canonical 迁移前），命中后自动迁移为 canonical，避免同单
  后续 fill 落成第二个成员导致数量双计数
- sell fill 按 `guardian_sell_sources`（v2/v1 兼容）解析请求级来源计划；处理新
  fill 前先按 `request_id / internal_order_id` 查询已写入的
  `om_exit_allocations` 累计本请求已分配量，计算 `remaining_plan =
  original_plan - already_allocated`，本次 fill 只允许消费剩余计划内的
  entry/slice（跨 fill 共享同一份剩余预算；乱序 / 重复 callback / 部分成交后
  撤单均收敛到同一守恒结果）
- broker-only 卖出（无 request）同样保留 `internal_order_id` 传给 allocation
  与 `already_allocated` 累计（按 `internal_order_id`），保证新 allocations
  可按订单审计、列表/详情账本判定可批量关联
- 正常链路**禁止静默跨计划 fallback**：剩余来源计划不足以解释 broker fill 时
  抛 `SellAllocationPlanExhaustedError`，不扣减计划外 entry/slice，而是写
  `om_ingest_rejections.reason_code=allocation_source_plan_exhausted` 与
  `xt_report_ingest` `sell_allocation` degraded runtime event，把 degraded /
  reconciliation 证据留给运行面与 Position Review；只有无来源计划（非
  Guardian 卖单）才回退稳定默认顺序
- 所有 slice 查询与分配使用显式稳定排序（`guardian_price ASC, trade_time ASC,
  slice_seq ASC, entry_slice_id ASC`），不依赖 Mongo natural order
- sell fill 的 entry/slice read-modify-write 在
  `OrderManagementXtIngestService` 内按 symbol 串行锁保护，配合
  `om_execution_fills.execution_identity` 幂等，避免并发 fill 互相覆盖
- legacy `buy_lot / lot_slice / sell_allocation` 仍同步写入，供迁移期兼容链使用
- 若 sell fill 已成功写入 V2 `om_position_entries / om_entry_slices / om_exit_allocations`，但 legacy `buy_lot / lot_slice` 镜像缺失或数量落后，trade callback 当前会跳过 legacy sell allocation，并依赖后续 `stock_fills_compat` 镜像刷新，不再把整笔成交回报记为失败

当前读侧检查语义：

- `SubjectManagement` detail 会把 `om_position_entries` 上的 `aggregation_members / aggregation_window` 与 `om_entry_slices` 一并下发
- `KlineSlim` 继续只消费 entry 摘要，不展开完整切片表
- entry 级“剩余市值”优先按 symbol snapshot 最新价乘剩余数量；缺失最新价时才回退到持仓均价
- `#582`：订单详情读侧按 `om_broker_orders.internal_order_id` 索引反查
  （`find_broker_order_by_internal_order_id`，非 unique partial 索引
  `ix_om_broker_orders_internal_order_id`），不再把 internal_order_id 当
  `broker_order_key` 直查，也不再全表扫描兜底；broker_order_id 兜底与
  `om_orders` 回退保留

### 自动平账

`xt_positions delta -> om_reconciliation_gaps -> stable observation -> om_reconciliation_resolutions -> auto_open_entry / auto_close_allocation`

自动平账不再伪造成 fake order / fake trade。收敛结果直接体现在：

- `auto_open_entry`
- `auto_close_allocation`
- `board_lot_rejected`
- `matched_execution_fill`

`auto_open_entry` 无对应订单请求（broker-only 语义），账本归属由
`LedgerResolver` 显式解析为 `base`（`position_type=base`）；先解析归属再
做 buy cluster，只并入同账本（base）聚类，禁止并入 t 账本聚类。

自动平账成功写入 `auto_open_entry / auto_close_allocation` 后，当前也会同步：

- 刷新 stock holdings projection cache
- 刷新 `stock_fills_compat` 镜像，避免 legacy 兼容视图滞后于 OM 主账本

sell-side 自动平账当前在 gap 上保留最近一笔 Guardian 卖出请求携带的 `sell_source_entries`。当正常成交回报缺失、只能走 `auto_close_allocation` 时，当前会优先按这组来源入口扣减，再回退到默认 slice 顺序，避免把卖出剩余数量错扣到未参与本次卖量计算的历史入口上。

`#571`：TPSL 止盈卖出请求（`source=tpsl_takeprofit` /
`scope_type=takeprofit_batch`）永不进入 reconcile gap 候选；`auto_close`
resolve 前置检查近窗口 TP 请求的成交回报，缺失时落
`tpsl_takeprofit_return_lost` 告警事件（不阻断自动平账）；无任何可用候选
（V2 open slice 与 legacy 均空）时落 `empty_candidate_fallback=true` 的
resolution，不再抛错中断整轮对账。

历史上已经形成的 Guardian 卖出错配，当前正式修复入口是：

```powershell
py -3.12 script/maintenance/repair_guardian_sell_entry_allocations.py
py -3.12 script/maintenance/repair_guardian_sell_entry_allocations.py --execute --backup-dir <artifacts_dir>
```

当前修复脚本只会改写“跨 entry 错配”的 `auto_close_allocation` 历史账本，不会为了同一 entry 内部的 slice 重排去改写账本，避免单入口标的出现无业务收益的重复 repair。

当前内部仓位累计规则：

- 若某个 symbol 已存在 open `om_position_entries`，对账只以 V2 entry remaining quantity 作为内部仓位真值
- 同 symbol 的 legacy `om_buy_lots` 仅保留给兼容读链与排障，不再额外叠加进对账 internal remaining，避免 mixed-state 双计数后误生成 `sell gap`
自动平账在检测到“同一轮快照对账户内多只持仓同时形成大比例 sell-gap、且近期缺少足够卖出成交证据”时，当前会熔断该轮 sell reconcile，不新建 sell gap，也不推进 sell-side gap 自动确认。

自动平账在解析运行期辅助元数据失败时，当前会优先收敛 broker truth：

- `grid_interval` 解析失败时回退 `1.03`
- `lot_amount` 解析失败时回退 `50000`

自动平账对 buy-side `gap` 当前采用“冻结首次价格、持续记录最新观测”的双快照语义：

- `initial_price_*` 记录首次发现时的价格快照
- `latest_price_*` 记录最近一次观测到的价格快照
- `chosen_price_*` 当前默认冻结为首次快照，并继续兼容映射到 `price_estimate / price_source / price_asof`
- `chosen_price_policy` 当前固定为 `freeze_initial`

`AUTO_OPENED` 当前已经拆成“真值确认优先、切片排布随后”的两阶段行为：

- entry truth 会先落 `om_position_entries`
- Guardian 切片排布随后尝试生成
- 若 `grid_interval / lot_amount / arrange_entry_slices` 任一环节异常，entry 仍保持 `OPEN`
- 降级状态通过 `arrange_status / arrange_degraded / arrange_error_* / arrange_runtime_errors` 落在 entry 上
- 降级时仍会写 compat mirror 与 holdings cache，避免真值已确认但视图长期滞后
- `#582`：auto-open 确认时发 `status=warning`、`reason_code=auto_open_entry`
  的 runtime 事件（payload 含 gap_id/quantity_delta/价格快照来源/观察次数/
  resolution_id）——账本与券商真值失配后的自动补记不再静默，运行面可直接定位

当前 external reconcile 不按同价、同量、部分数量或时间邻近猜测 XT 回报归属。
FQOM 或完整 canonical identity 能证明归属时才挂回内部订单；完整 canonical
身份无法关联时进入 deterministic broker-only，身份不完整时 fail closed。
自动平账与 XT 回报补录路径里，凡是由 `trade_time / confirmed_at` 回填 `date/time` 的订单域记录，当前统一按北京时间（`Asia/Shanghai`）落地，避免同一笔成交在不同读模型里出现跨日漂移。

排障查看口径也保持同一套时间语义：`xt-order list`、`xt-trade list` 以及依赖成交 epoch 时间的 fill 查看命令，当前统一按北京时间展示；其中 `--date` 过滤使用北京时间自然日边界，而不是宿主机本地时区。

手工 fill 导入命令传入的 `dt` 文本，当前也统一按北京时间解析成 epoch，避免“查看是北京时间、导入却按宿主机本地时区”导致同一笔记录前后漂移。

### XT 自动还款

`xt_account_sync.worker -> pm_credit_asset_snapshots -> xt_auto_repay.worker -> query_credit_detail confirm -> broker direct cash repay`

当前运行语义：

- 只处理普通融资负债，不处理专项负债
- `/system-settings -> XTQuant` 当前直接控制 `xtquant.auto_repay.enabled` 与 `xtquant.auto_repay.reserve_cash`
- 盘中默认每 30 分钟只读一次已同步的 `credit_detail` 快照做候选判断
- 只有候选命中后，才会即时调用 `query_credit_detail()` 二次确认
- 真实提交当前通过 `XtQuantTrader.order_stock(..., stock_code='000001.SZ', order_type=CREDIT_DIRECT_CASH_REPAY, price_type=LATEST_PRICE, price=0)` 发起；空 `stock_code` 会被 XT 直接拒绝
- 固定 `14:55` 做日终硬结算，固定 `15:05` 做一次补偿重试
- `broker_submit_mode=observe_only` 时只记录事件，不真实提交还款
- XT 柜台处于非交易状态时会拒绝直接还款；worker 当前会把这类拒单记成 `failed`，而不是误判为 `submitted`
- 自动还款冷却锁当前只用于防并发，不再把同一轮 `run_pending()` 内串行执行的 `hard_settle -> retry` 互相挡成 `lock_unavailable`
- `system_settings` 读取失败时当前会先重试；若进程内已经存在上一版有效配置，则保留上一版，不再回退成空 `xtquant.path/account`
- `xt_auto_repay.worker` 启动后下一次盘中巡检当前按 `last_checked_at + 30 分钟` 对齐；若已错过应跑时间，会在 1 秒级快速补跑，而不是从重启时刻重新整等 30 分钟

### Broker 提交模式

`xtquant.broker_submit_mode`（`normal` / `observe_only`，缺省 `normal`）当前语义：

- `broker` 主循环启动时读取一次作为启动快照，切换模式需要重启 broker。
- `xt_auto_repay.worker` 每轮刷新该设置，`observe_only` 时只记录事件不真实提交还款。
- `normal`：Guardian 信号链运行并真实提交券商。
- `observe_only`：Guardian 信号链运行，订单演练但不提交券商。

observe-only 买卖路径当前先执行 `prepare_submit_execution`（解析价格模式、
信用订单类型、可用额度与关联 token 并落库），再跳过 `submit_executor`，
由 `finalize_submit_execution` 落 `BROKER_BYPASSED`；prepare 校验失败按正常
失败路径处理，不伪装成成功演练。`BROKER_BYPASSED` 不清理策略 buy 冷却键，
避免同一信号在演练环境持续重复生成演练订单；normal 提交失败仍沿用现有清理逻辑。

`freshquant/order_management/submit/execution_bridge.py` 的
`finalize_submit_execution` / `dispatch_cancel_execution` 当前要求
`broker_submit_mode` 为 keyword-only 必传参数，不再提供隐式 `normal` 默认值；
broker 与 execution_bridge 必须同批部署。

### 手工导入

`manual import/reset -> om_trade_facts -> om_position_entries / om_entry_slices -> stock_fills_compat mirror sync`

手工入口当前也强制执行 `100` 股整数倍校验。

## Order Ledger V2 Rebuild

当前正式重建入口：

```powershell
py -3.12 -m uv run script/maintenance/rebuild_order_ledger_v2.py --dry-run
py -3.12 -m uv run script/maintenance/rebuild_order_ledger_v2.py --execute --backup-db <backup_db_name>
```

`rebuild_order_ledger_v2.py` 当前支持两种模式：

- `--mode replay`（默认）：既有逐笔重建语义；
- `--mode flatten-cost-price`：成本价拍平重建（Guardian 卖出账本重建方案 v4）。
  按 `(account_id, symbol)` 从 `xt_positions` 生成 1 条
  `source_ref_type=position_snapshot_flatten` 的 entry（`entry_price =
  avg_price` 保留原始精度、`aggregation_members=[]` 阻止后续聚类并入），再用
  该标的配置网格（`lot_amount` + `grid_interval`）重新切分
  `om_entry_slices`；脚本内硬不变量（Σentry == Σxt volume、Σslice ==
  Σentry、全 OPEN）失败即 abort；dry-run 输出“旧锚点全集 → 新切片全集”对照与
  `acceptance.old_anchor_prices_still_present` 查询结果。

flatten 模式执行时的归档/清理边界：

- 归档：先写 `position_review_evidence_archive` / `om_execution_history_archive`
  （沿用既有 history backfill），并把 `om_entry_stoploss_bindings` /
  `om_takeprofit_states` 快照进 `order_ledger_flatten_auxiliary_archive`；
- 清理：在 `ORDER_LEDGER_REBUILD_PURGE_COLLECTIONS` 基础上追加 purge
  `om_takeprofit_states`；
- 执行破坏性 flatten 仍要求显式 `--backup-db` 且不允许 `--account-id`；
  dry-run 允许 `--account-id` 单账户演练。

初始化向导 `python -m freshquant.initialize` 的运行态 bootstrap 当前会直接执行 destructive rebuild：先把将被替换的 `xt_trades` 和将被 purge 的订单请求、订单、成交、position entries / slices / allocations 幂等写入 `om_execution_history_archive / position_review_evidence_archive`；归档成功后才 purge order-ledger rebuild 边界内的旧账本集合，再仅用刚同步的 `xt_positions` 生成新的 `om_position_entries / om_entry_slices / om_exit_allocations` 等主账本结果，并在完成后重建 `stock_fills_compat` 镜像，同时把同账户的 `xt_orders / xt_trades` 快照清空，避免旧委托/成交残留继续被误当成 broker truth，而不是走 runtime `auto_open_entry` 平账链路。归档失败时初始化会在删除前中止。

当前约束：

- dry-run 允许配合 `--account-id` 做单账户演练
- destructive execute 不允许 `--account-id`
- destructive execute 必须显式提供 `--backup-db`
- `--backup-db` 不能和当前订单账本数据库同名
- dry-run / execute 汇总当前额外给出：
  - `clustered_entries`
  - `mergeable_entry_gap`
  - `non_default_lot_slices`

当前重建输入只允许：

- `xt_orders`
- `xt_trades`
- `xt_positions`

当前重建输出会覆盖：

- `om_order_requests / om_order_events / om_orders`
- `om_broker_orders / om_execution_fills / om_trade_facts`
- `om_position_entries / om_entry_slices / om_exit_allocations`
- `om_buy_lots / om_lot_slices / om_sell_allocations`
- `om_external_candidates / om_reconciliation_gaps / om_reconciliation_resolutions`
- `om_stoploss_bindings / om_entry_stoploss_bindings / om_ingest_rejections`

`om_execution_history_archive / position_review_evidence_archive` 不在重建 purge
边界内。正式 `rebuild_order_ledger_v2.py --execute` 会在数据库备份和 purge
之前自动写入这两个档案；同一 `execution_key` 下的请求、订单、fill、trade fact
冲突关联以候选数组保留，不用后到单值覆盖先到证据。

重建后的运行期读侧：

- `holding.py` / `/api/stock_fills` 把 OM 主链返回的空列表视为 authoritative，不再因此掉回 compat/raw legacy
- `entry_adapter` 在存在 v2 entry / binding 时不再混读 legacy `buy_lot / stoploss_binding`
- `SubjectManagement`、`TPSL` 现在可以在没有 legacy `buy_lots` 的情况下直接读取 v2 `position_entries`
- 当前 rebuild 生成的 buy-side `position_entries` 已切到 `buy_cluster / broker_execution_cluster` 语义

## Board Lot 规则

系统当前把普通 A 股 `100` 股整数倍视为硬约束：

- odd-lot XT 回报会写 `om_execution_fills / om_trade_facts` 审计事实
- odd-lot 不会生成 `position_entry / entry_slice / exit_allocation`
- odd-lot 会写入 `om_ingest_rejections.reason_code=non_board_lot_quantity`
- 手工导入与手工 reset 直接拒绝 odd-lot 数量

## 读模型口径

- `/api/order-management/orders`
  - 订单列表与详情优先围绕 `internal_order_id` 展示
  - 对于 broker rebuild / broker-only 订单，列表和详情当前允许回退使用 `broker_order_id / broker_order_key` 作为详情查找键
  - canonical broker-only 订单总是持久化 deterministic `ord_broker_*` `internal_order_id`；
    `broker_order_id / broker_order_key` 回退只服务于历史 rebuild/legacy 记录
  - 详情中成交、券商订单聚合和运行态说明都来自 V2 账本
- `/api/order-management/stoploss/bind`
  - 当前只绑定 `entry_id`
- `/api/stock_fills`
  - 名称仍保留给旧页面/脚本
  - 底层优先读 `om_position_entries + om_entry_slices`
  - `freshquant.stock_fills_compat` 仅作为兼容镜像兜底

## 页面语义

- `/position-management -> 相关订单`
  - 当前是唯一正式订单排障入口
  - 继续展示 request / order / event / trade 主线
  - 订单列表当前会优先显示 `updated_at`，若 broker-only 行缺失该字段，则回退 `last_fill_time / first_fill_time`
  - 订单列表、顶部摘要、详情 badge、timeline 当前统一通过 shared `orderStateMeta` 输出状态 label / chip variant / severity
  - 状态筛选仍使用 raw enum value，但前端展示 label 已统一为中文语义
  - 订单详情中的成交解释已经基于 `broker_order + execution_fill`

当前共享订单状态集合：

- `ACCEPTED`
- `QUEUED`
- `SUBMITTING`
- `SUBMITTED`
- `BROKER_BYPASSED`
- `CANCEL_REQUESTED`
- `PARTIAL_FILLED`
- `FILLED`
- `CANCELED`
- `FAILED`
- `REJECTED`
- `INFERRED_PENDING`
- `INFERRED_CONFIRMED`
- `MATCHED`
- `OPEN`
- `subject-management` 读模型 / 组件语义
  - 止损对象已经是 `entry`
- `/kline-slim`
  - 标的设置中的止损对象也是 `entry`，并与 `subject-management` 读模型共享同一套 entry 摘要字段
- `/position-management`
  - 当前承载 symbol 级统一排障工作区
  - `单标的仓位上限覆盖` 列表不再承担独立对账展示
  - broker truth / ledger / reconciliation 与订单链已统一收口到 `/position-management`

## 部署

- 改动 `freshquant/order_management/**` 后：
  - 重建 API Server
  - 重启 `xt_account_sync.worker`
  - 重启 `xt_auto_repay.worker`
  - 重启 `tpsl.tick_listener`
- 改动 `freshquant/xt_auto_repay/**` 后：
  - 重启 `xt_auto_repay.worker`
- 改动 `morningglory/fqwebui/**` 中订单相关页面后：
  - 重建 Web UI

## 排障

### submit 成功但 broker 没响应

- 查 `om_order_requests`
- 查 `om_orders`
- 查 `om_broker_orders`
- 查 Redis `STOCK_ORDER_QUEUE`

### 成交已到但页面没有持仓入口

- 查 `om_execution_fills`
- 查 `om_trade_facts`
- 查 `om_broker_orders.filled_quantity`
- `om_orders.filled_quantity` 是退役死字段（submit 不再写入）；成交数量真值
  统一读 `om_broker_orders.filled_quantity`
- 查 `om_position_entries / om_entry_slices`
- 若成交数量不是 `100` 股整数倍，再查 `om_ingest_rejections`

### 券商仓位与账本仓位不一致

- 先看 `xt_positions`
- 再看 `om_position_entries`
- 最后看 `om_reconciliation_gaps / om_reconciliation_resolutions`

### 旧接口显示碎片化持仓

- 查 `om_position_entries`
- 查 `freshquant.stock_fills_compat`
- 若 compat 镜像仍旧异常，再查 legacy `om_buy_lots`
