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
  - `py -3.12 script/maintenance/targeted_order_ledger_repair.py --plan-path <plan.json>`
  - `py -3.12 script/maintenance/targeted_order_ledger_repair.py --restore-manifest <manifest.json>`
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

### 券商订单与成交身份

- 券商订单规范主键首选
  `account_id + trading_day + order_sysid`
- XT 未提供 `order_sysid` 时，回退主键固定为
  `account_id + trading_day + symbol + side + broker_order_id`
- `broker_order_id` 和 `order_sysid` 都不能脱离账户、交易日单独作为全局唯一键；历史数据中已确认存在 `6` 组 `order_sysid` 跨日复用
- 回报已知的 `account_id / trading_day / symbol / side / broker_order_id / order_sysid` 都是硬约束；唯一候选也必须逐维校验，冲突或歧义时 fail closed，不按时间最近或“只有一条候选”猜测归属
- XT 原始 `side` 是 canonical 执行方向；内部订单方向不能覆盖与其冲突的回报，未知方向不再默认成 `sell`
- 无法关联到内部请求但身份完整的 XT 回报使用规范 broker identity 派生稳定 broker-only `internal_order_id`，不再把裸 `broker_order_id` 冒充内部订单 ID
- execution fill 的幂等身份固定包含
  `account_id + trading_day + symbol + side + broker_trade_id`，避免不同账户、交易日或标的复用成交号时互相覆盖

### 破坏性 rebuild 治理

- 破坏性 `order-ledger rebuild` 只能由 broker truth 驱动，primary truth 只允许 `xt_orders`、`xt_trades`、`xt_positions`
- `om_*`、`stock_fills`、`stock_fills_compat` 只能作为迁移期兼容投影或排障线索，不能作为 rebuild 主输入
- rebuild 默认拒绝用空 `xt_positions` 快照去 flatten 非空账本；只有显式允许空快照 flatten 时，才会把空 `xt_positions` 视为券商已清仓
- 初始化向导的 runtime bootstrap 当前走 `xt_positions`-only destructive rebuild 变体：先归档将被替换的执行与持仓解释证据，归档成功后才 purge order-ledger rebuild 边界内的旧账本集合，再按券商当前持仓快照重建 V2 账本，并刷新 `stock_fills_compat`
- 这类破坏性 rebuild 在编码前必须先建立 GitHub Issue，写清影响面、验收标准与部署影响

### OM 主账本

- `om_order_requests`
  - 内部下单意图
- `om_orders`
  - 兼容期内部订单壳
- `om_broker_orders`
  - 券商订单聚合，保存 `account_id / trading_day / order_sysid / broker_order_key`，并维护 `requested_quantity / filled_quantity / avg_filled_price / fill_count`
- `om_execution_fills`
  - 真实券商成交 fill，按规范 execution identity 去重
- `om_trade_facts`
  - 兼容期成交事实镜像，仍保留给旧读链和部分排障
- `om_position_entries`
  - 系统持仓入口真值，供 TPSL/Subject/Kline/持仓解释层消费；当前 buy 侧默认落为保守聚合后的 `buy_cluster`
- `om_entry_slices`
  - entry 的 Guardian 切片；当前按聚合后的 entry 重新按 `50000` 口径切片
- `om_exit_allocations`
  - 卖出对 entry / slice 的分摊结果
- `om_reconciliation_gaps`
  - 券商仓位与账本持仓解释之间的差额
- `om_reconciliation_resolutions`
  - 差额的自动收敛结果
- `om_entry_stoploss_bindings`
  - entry 级止损绑定
- `om_ingest_rejections`
  - 进入 XT ingest 但不允许进入主账本的拒绝记录
- `om_targeted_repair_runs`
  - 定向修账的 `repair_id / plan_hash / preimage_hash / postimage_hash / manifest_hash / status` 审计收据

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

当前信用账户买单的运行期语义已经固定为：

- submit 阶段若解析出 `credit_trade_mode_resolved=finance_buy`，broker 执行桥会在真正发往 XT 前补查 `credit_detail`
- 运行期会把 `credit_available_bail_balance / credit_available_amount` 一并透传到 broker host，供执行前资金校验与排障使用
- `finance_buy` 的执行前资金校验当前只看 `available_bail_balance >= price * quantity + fee`
- 普通现金买入与信用担保品买入仍按 `asset.cash - asset.frozen_cash` 校验
- 若策略买单在 broker host 本地预提交阶段就被跳过或失败、没有形成真实 broker order，Guardian 之前写入的 `buy:{symbol}` 冷却会立即回收，不再保留误导性的 15 分钟冷却

Guardian 卖出请求当前会把本次卖量对应的来源入口计划一起写入 `om_order_requests.strategy_context.guardian_sell_sources`：

- `requested_quantity / submit_quantity`
- `profitable_fill_count`
- `entries[] = { entry_id, quantity }`

这组来源入口语义当前同时用于两条卖出落账链：

- XT `trade` 回报正常进入 ingest 时，sell fill 优先按这组来源入口做 `exit_allocation`
- XT `trade` 回报缺失、系统只能退回 `xt_positions delta` 自动平账时，sell gap 也优先按这组来源入口扣减

这样“本次卖出实际是按哪些买入入口算出来的”会在正常成交链和差额收敛链保持同一套 entry 语义。

### 撤单

`cancel_order -> om_order_requests(cancel) -> om_orders / om_broker_orders state update -> STOCK_ORDER_QUEUE -> broker`

### XT order callback

`XT order callback -> normalize_xt_order_report -> OrderTrackingService.ingest_order_report_with_meta -> om_orders / om_broker_orders / om_order_events`

### XT trade callback

`XT trade callback -> normalize_xt_trade_report -> OrderTrackingService.ingest_trade_report_with_meta -> om_execution_fills / om_trade_facts / om_broker_orders aggregate refresh -> om_position_entries / om_entry_slices / om_exit_allocations -> stock_fills_compat mirror sync`

当前写链规则：

- XT order/trade callback 进入 tracking 前先建立账户、交易日、标的、方向和券商订单身份；已绑定内部订单仍要做同一套硬校验
- 若规范身份冲突、候选歧义或聚合成员出现 mixed-account / mixed-symbol / mixed-side，回报不进入该订单聚合和持仓账本
- 若券商订单已在 submit 成功阶段绑定到内部订单，trade callback 当前仍会继续进入 `ingest_trade_report()`；`ExternalOrderReconcileService` 只负责补齐 trace/request/internal order 上下文与 reconcile 侧 runtime event，不再把这类回报提前短路
- `om_broker_orders` 的 `filled_quantity / avg_filled_price / fill_count` 从该规范 broker identity 下已接受的 canonical fills 确定性重算，不在旧聚合数值上盲目累加
- buy fill 先按 `broker_order_key` 收口成 buy execution group，再按保守规则归并进 `buy_cluster` entry
- `buy_cluster` 归并规则当前固定为：
  - 同一 `symbol`
  - 同一北京时间交易日
  - `buy` 侧
  - 与 cluster 首成员时间差 `<= 5 分钟`
  - 成交均价偏差 `<= 0.3%`
  - 已发生卖出扣减的 entry 不再接受新的 buy order 合并
- 同一 broker order 的多笔 fill 会更新同一个聚合成员，而不是继续生成多条 entry
- sell fill 先尝试按 `om_order_requests.strategy_context.guardian_sell_sources.entries` 对齐来源入口，再回退默认 `entry_slice` 顺序扣减，最后写 `exit_allocations`
- XT 成交碎片只要求 `quantity` 为正整数；单笔 execution 可以不是 `100` 股整数倍，所有碎片按规范 execution identity 分别入账后再汇总
- entry slice 以 `entry_slice_id` 做定向更新；运行期和 reconcile 都不得用 open slice 子集覆盖某个 entry 的完整历史切片
- 每条 `exit_allocation.entry_id / entry_slice_id` 都必须引用现存且归属一致的 V2 entry/slice；entry 与 slice 的已扣减数量必须分别与 allocation 合计守恒
- legacy `buy_lot / lot_slice / sell_allocation` 仍同步写入，供迁移期兼容链使用
- 若 sell fill 已成功写入 V2 `om_position_entries / om_entry_slices / om_exit_allocations`，但 legacy `buy_lot / lot_slice` 镜像缺失或数量落后，trade callback 当前会跳过 legacy sell allocation，并依赖后续 `stock_fills_compat` 镜像刷新，不再把整笔成交回报记为失败

当前读侧检查语义：

- `SubjectManagement` detail 会把 `om_position_entries` 上的 `aggregation_members / aggregation_window` 与 `om_entry_slices` 一并下发
- `KlineSlim` 继续只消费 entry 摘要，不展开完整切片表
- entry 级“剩余市值”优先按 symbol snapshot 最新价乘剩余数量；缺失最新价时才回退到持仓均价

### 自动平账

`xt_positions delta -> om_reconciliation_gaps -> stable observation -> om_reconciliation_resolutions -> auto_open_entry / auto_close_allocation`

自动平账不再伪造成 fake order / fake trade。收敛结果直接体现在：

- `auto_open_entry`
- `auto_close_allocation`
- `board_lot_rejected`
- `matched_execution_fill`

自动平账成功写入 `auto_open_entry / auto_close_allocation` 后，当前也会同步：

- 刷新 stock holdings projection cache
- 刷新 `stock_fills_compat` 镜像，避免 legacy 兼容视图滞后于 OM 主账本

sell-side 自动平账当前在 gap 上保留最近一笔 Guardian 卖出请求携带的 `sell_source_entries`。当正常成交回报缺失、只能走 `auto_close_allocation` 时，当前会优先按这组来源入口扣减，再回退到默认 slice 顺序，避免把卖出剩余数量错扣到未参与本次卖量计算的历史入口上。

历史上已经形成的 Guardian 卖出错配，当前正式修复入口是：

```powershell
py -3.12 script/maintenance/repair_guardian_sell_entry_allocations.py
py -3.12 script/maintenance/repair_guardian_sell_entry_allocations.py --execute --backup-dir <artifacts_dir>
```

当前修复脚本只会改写“跨 entry 错配”的 `auto_close_allocation` 历史账本，不会为了同一 entry 内部的 slice 重排去改写账本，避免单入口标的出现无业务收益的重复 repair。

当前内部仓位累计规则：

- 若某个 symbol 已存在 open `om_position_entries`，对账只以 V2 entry remaining quantity 作为内部仓位真值
- 某 symbol 只要存在过 V2 position entry，包括全部 entry 已 `CLOSED`，读侧和 reconcile 就不再回退 legacy remaining；CLOSED V2 同样是 authoritative history
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

当前 external reconcile 对 XT 外部回报也支持部分匹配：

- 若内部在途单的请求数量大于 XT 回报数量，但 symbol / side / 价格匹配，当前允许挂回同一 internal order
- 这样 `intent=600`、`external_reported=300` 这类场景不会再一律 externalize
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

### 手工导入

`manual import/reset -> om_trade_facts -> om_position_entries / om_entry_slices -> stock_fills_compat mirror sync`

手工入口当前也强制执行 `100` 股整数倍校验。

## Order Ledger V2 Rebuild

当前正式重建入口：

```powershell
py -3.12 -m uv run script/maintenance/rebuild_order_ledger_v2.py --dry-run
py -3.12 -m uv run script/maintenance/rebuild_order_ledger_v2.py --execute --backup-db <backup_db_name>
```

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

这两个 archive 是 append-only 复盘证据，不是 rollback backup：它们不包含 broker
order、event、gap、resolution、rejection、compat 与 legacy 全闭包，不能用于恢复一次
定向修账或 destructive rebuild 的完整 preimage。

重建后的运行期读侧：

- `holding.py` / `/api/stock_fills` 把 OM 主链返回的空列表视为 authoritative，不再因此掉回 compat/raw legacy
- `entry_adapter` 在存在 v2 entry / binding 时不再混读 legacy `buy_lot / stoploss_binding`
- `SubjectManagement`、`TPSL` 现在可以在没有 legacy `buy_lots` 的情况下直接读取 v2 `position_entries`
- 当前 rebuild 生成的 buy-side `position_entries` 已切到 `buy_cluster / broker_execution_cluster` 语义

## 定向 Repair / Restore

跨标的、跨账户或跨交易日串单的正式修复入口是：

```powershell
$preview = .venv\Scripts\python.exe script/maintenance/targeted_order_ledger_repair.py `
  --plan-path <repair-plan.json> --dry-run | ConvertFrom-Json

.venv\Scripts\python.exe script/maintenance/targeted_order_ledger_repair.py `
  --plan-path <repair-plan.json> `
  --execute `
  --expected-preimage-hash $preview.preimage_hash `
  --manifest-path <immutable-preimage-manifest.json>
```

repair plan 当前固定包含：

- 唯一且不可复用到其他计划的 `repair_id`
- `account_id + symbols[] + broker_order_ids[]/order_sysids[]` 目标边界
- request、internal order、execution、entry、slice、allocation、gap、resolution、rejection 等显式闭包身份
- 每个逻辑 selector 分支都必须同时具有 `account_id`（账户字段缺失时使用已声明的精确 `_id`）和稳定 order/execution/document 闭包键；symbol-only selector 会被拒绝
- 每个 `mode=replace` change 只允许一个原子 insert/update/delete；同集合多文档修复拆成多个互不重叠 change，restore 按相反顺序执行
- `mode=snapshot`：只纳入完整 preimage/postimage hash 门槛，不执行写入
- `mode=replace`：声明该稳定 selector 下最多一个修复后文档
- 每个 replace 集合精确到文档身份的 `allowed_diff.inserted / updated / deleted`

dry-run 不连接额外数据源、不写账本，只计算完整闭包的 preimage、postimage、diff
和 hash。execute 必须提交同一次 dry-run 的 `preimage_hash`，并在任何数据库写入前先把
完整 BSON preimage manifest 落盘；当前闭包发生漂移、allowed diff 多一条或少一条都会
fail closed。

`repair_id` 的运行收据写入 `om_targeted_repair_runs`。每个原子 change 会单独判定为
preimage/postimage/unchanged；进程在多集合之间中断时，只要没有 change 漂移到第三种状态，
后续相同 repair 可以继续尚未应用的 change，restore 也可按反向顺序继续。同一 plan 和同一已应用状态重复
执行会返回 `already_applied`；同一 `repair_id` 绑定不同 plan 会拒绝。中断时只有当前闭包
仍精确等于 preimage 或 postimage 才允许确定性续跑/收口。

restore 使用同一 manifest：

```powershell
$restore = .venv\Scripts\python.exe script/maintenance/targeted_order_ledger_repair.py `
  --restore-manifest <immutable-preimage-manifest.json> --dry-run | ConvertFrom-Json

.venv\Scripts\python.exe script/maintenance/targeted_order_ledger_repair.py `
  --restore-manifest <immutable-preimage-manifest.json> `
  --execute `
  --expected-current-hash $restore.current_hash
```

只有当前闭包仍精确等于 repair postimage 时 restore 才会恢复 preimage；后续任何业务写入
导致 hash 漂移都会阻断回滚。执行定向 repair/restore 前必须停止相关 API order-write、
Guardian、Position Management、TPSL 与 Order Management 写入面。定向事故修复期间不得
运行 `python -m freshquant.initialize` 或全库 `rebuild_order_ledger_v2.py --execute`。

## Board Lot 规则

系统当前把下单意图与外部成交事实分开校验：

- 普通 A 股策略/API 下单意图仍要求 `100` 股整数倍
- 手工 import/reset 仍要求 `100` 股整数倍
- XT order/trade callback 是已经发生的外部事实，任何正整数 execution quantity 都必须入账
- 同一订单由多个非整百 execution fragment 组成时，按 fragment 幂等保存，再从 accepted fills 重算订单聚合与 entry/allocation
- `om_ingest_rejections.reason_code=non_board_lot_quantity` 不再用于拒绝 XT 已成交碎片；历史这类 rejection 只作为待修复证据

## 读模型口径

- `/api/order-management/orders`
  - 订单列表与详情优先围绕 `internal_order_id` 展示
  - 对于 broker rebuild / broker-only 订单，列表和详情当前允许回退使用 `broker_order_id / broker_order_key` 作为详情查找键
  - 缺失 `internal_order_id` 时，右侧详情仍可继续打开
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

- 一般改动 `freshquant/order_management/**` 后：
  - 重建 API Server
  - 重启 `order_management` surface（broker、`xt_account_sync.worker`、`xt_auto_repay.worker`）
- 改动共享 `freshquant/order_management/repository.py` 或 `entry_adapter.py` 后：
  - 重建 API Server
  - 同时重启 Guardian、Position Management、TPSL、Order Management 四个宿主机 surface
- 涉及账本修复正式上线后：
  - 先完成最新远程 `main` formal deploy 与 runtime health check
  - 再停相关写入面执行定向 repair
  - repair 验收完成后恢复并验证全部命中 surface
- 改动 `freshquant/xt_account_sync/**` 后：
  - 重启 `xt_account_sync.worker`
- 改动 `freshquant/tpsl/**` 后：
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
