# 订单管理

## 职责

订单管理是交易链的账本与执行事实层，当前负责：

- 统一受理 API、CLI、Guardian、TPSL 的下单/撤单请求
- 维护 `request -> internal order -> broker order -> execution fill` 主链
- 基于成交聚合生成 `position entry / entry slice / exit allocation`
- 基于券商仓位差额维护 `reconciliation gap / resolution`
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
- 这类破坏性 rebuild 在编码前必须先建立 GitHub Issue，写清影响面、验收标准与部署影响

### OM 主账本

- `om_order_requests`
  - 内部下单意图
- `om_orders`
  - 兼容期内部订单壳
- `om_broker_orders`
  - 券商订单聚合，维护 `requested_quantity / filled_quantity / avg_filled_price / fill_count`
- `om_execution_fills`
  - 真实券商成交 fill，`broker_trade_id` 去重
- `om_trade_facts`
  - 兼容期成交事实镜像，仍保留给旧读链和部分排障
- `om_position_entries`
  - 系统持仓入口真值，供 TPSL/Subject/Kline/持仓解释层消费
- `om_entry_slices`
  - entry 的 Guardian 切片
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

### 撤单

`cancel_order -> om_order_requests(cancel) -> om_orders / om_broker_orders state update -> STOCK_ORDER_QUEUE -> broker`

### XT order callback

`XT order callback -> normalize_xt_order_report -> OrderTrackingService.ingest_order_report_with_meta -> om_orders / om_broker_orders / om_order_events`

### XT trade callback

`XT trade callback -> normalize_xt_trade_report -> OrderTrackingService.ingest_trade_report_with_meta -> om_execution_fills / om_trade_facts / om_broker_orders aggregate refresh -> om_position_entries / om_entry_slices / om_exit_allocations -> stock_fills_compat mirror sync`

当前写链规则：

- buy fill 默认按 `broker_order_key` 聚合成一个 `position_entry`
- 同一 broker order 的多笔 fill 会更新同一个 entry，而不是继续生成多条 entry
- sell fill 先扣减 `entry_slices`，再写 `exit_allocations`
- legacy `buy_lot / lot_slice / sell_allocation` 仍同步写入，供迁移期兼容链使用

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

当前内部仓位累计规则：

- 若某个 symbol 已存在 open `om_position_entries`，对账只以 V2 entry remaining quantity 作为内部仓位真值
- 同 symbol 的 legacy `om_buy_lots` 仅保留给兼容读链与排障，不再额外叠加进对账 internal remaining，避免 mixed-state 双计数后误生成 `sell gap`

自动平账在检测到“同一轮快照对账户内多只持仓同时形成大比例 sell-gap、且近期缺少足够卖出成交证据”时，当前会熔断该轮 sell reconcile，不新建 sell gap，也不推进 sell-side gap 自动确认。

自动平账在解析运行期辅助元数据失败时，当前会优先收敛 broker truth：

- `grid_interval` 解析失败时回退 `1.03`
- `lot_amount` 解析失败时回退 `3000`

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

### 手工导入

`manual import/reset -> om_trade_facts -> om_position_entries / om_entry_slices -> stock_fills_compat mirror sync`

手工入口当前也强制执行 `100` 股整数倍校验。

## Order Ledger V2 Rebuild

当前正式重建入口：

```powershell
py -3.12 -m uv run script/maintenance/rebuild_order_ledger_v2.py --dry-run
py -3.12 -m uv run script/maintenance/rebuild_order_ledger_v2.py --execute --backup-db <backup_db_name>
```

当前约束：

- dry-run 允许配合 `--account-id` 做单账户演练
- destructive execute 不允许 `--account-id`
- destructive execute 必须显式提供 `--backup-db`
- `--backup-db` 不能和当前订单账本数据库同名

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

重建后的运行期读侧：

- `holding.py` / `/api/stock_fills` 把 OM 主链返回的空列表视为 authoritative，不再因此掉回 compat/raw legacy
- `entry_adapter` 在存在 v2 entry / binding 时不再混读 legacy `buy_lot / stoploss_binding`
- `SubjectManagement`、`TPSL` 现在可以在没有 legacy `buy_lots` 的情况下直接读取 v2 `position_entries`

## Board Lot 规则

系统当前把普通 A 股 `100` 股整数倍视为硬约束：

- odd-lot XT 回报会写 `om_execution_fills / om_trade_facts` 审计事实
- odd-lot 不会生成 `position_entry / entry_slice / exit_allocation`
- odd-lot 会写入 `om_ingest_rejections.reason_code=non_board_lot_quantity`
- 手工导入与手工 reset 直接拒绝 odd-lot 数量

## 读模型口径

- `/api/order-management/orders`
  - 订单列表与详情继续围绕 `internal_order_id` 展示
  - 详情中成交、券商订单聚合和运行态说明都来自 V2 账本
- `/api/order-management/stoploss/bind`
  - 当前只绑定 `entry_id`
- `/api/stock_fills`
  - 名称仍保留给旧页面/脚本
  - 底层优先读 `om_position_entries + om_entry_slices`
  - `freshquant.stock_fills_compat` 仅作为兼容镜像兜底

## 页面语义

- `/order-management`
  - 继续展示 request / order / event / trade 主线
  - 订单详情中的成交解释已经基于 `broker_order + execution_fill`
- `/subject-management`
  - 止损对象已经是 `entry`
- `/tpsl`
  - “单笔止损”实际是 `entry stoploss`
- `/kline-slim`
  - 标的设置中的止损对象也是 `entry`
- `/position-management`
  - 不再对比 `stock_fills` 仓位真值，只展示 `券商仓位 / 账本仓位 / 对账状态`

## 部署

- 改动 `freshquant/order_management/**` 后：
  - 重建 API Server
  - 重启 `xt_account_sync.worker`
  - 重启 `tpsl.tick_listener`
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
