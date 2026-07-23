# 当前架构

## 总体分层

- 行情层
  - `freshquant.market_data.xtdata.*`
- 策略层
  - `freshquant.strategy.*`
  - `freshquant.signal.*`
- 研究回测层
  - `freshquant.backtest.clx.*`
  - `freshquant.rear.clx_backtest.*`
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

## CLX 研究回测层

### 主链

`quantaxis Mongo -> immutable snapshot -> causal prefix signal facts -> event outcomes -> TRAIN search -> VALIDATION frozen ranking -> one-time HOLDOUT reveal -> RAW portfolio matching -> artifact projector -> freshquant_clx_backtest -> API / Web UI`

### 计算边界

- `S0000`～`S0017` 统一使用前复权 OHLC + 原始成交量识别信号。
- 信号按逐日 from-zero prefix 计算，`reveal_date` 是研究与交易时钟；历史 `signal_date` 不代表当时已经可见。
- 事件收益、涨跌停、费用、现金和持仓撮合统一使用原始价格。
- 单模型候选先经过 TRAIN 门槛；多模型共振/序列只从通过 TRAIN beam 的不同 `independence_root` 生成。
- VALIDATION 生成不可变完整顺序；HOLDOUT 在冻结前保持物理未读取，成功揭示由 persistent ledger 限制为一次，揭示后不重排。

### 运行边界

- `fq_apiserver` 只读 artifact，并查询派生库 `freshquant_clx_backtest`。
- `fq_clx_backtest_worker` 通过 Mongo lease 承担长任务、HOLDOUT 和导出，对 artifact 根目录可写。
- `ClxArtifactProjector` 只投影已经过 manifest、文件哈希和 lineage 校验的 artifact；既有相同身份的不同内容会被拒绝。
- 页面 2～4 项比较选择只影响展示；正式冻结选择来自服务端 manifest 发布的 VALIDATION 正向前 20（不足时取全部）。

详细合同见 [CLX 大规模回测](./modules/clx-backtest.md)。

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

`current xt_trades / OM ledger + om_execution_history_archive / position_review_evidence_archive -> position-review read model -> /api/position-review/* -> PositionReview`

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
  - XT 回报进入订单账本时，`broker_order_id` 只作为候选检索键；重复券商订单号需要结合 `symbol`、`side/order_type` 与回报时间确定内部订单
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
  - `entries + entry stoploss + guardian/takeprofit`
- `PositionReview`
  - 当前 `xt_trades / OM ledger` 与两个只读历史档案的合并视图
  - ClickHouse Trace 只作为可选判定上下文和运行观测跳转证据

## 当前持仓复盘口径

- `/position-review` 是只读工作台，覆盖所有存在可信历史成交的标的；当前持仓和已清仓标的不采用不同的成交真值口径。
- 复盘以策略请求或订单为判定单位；同一订单的逐笔成交只作为实际成交数量、价格和执行过程的下钻证据。
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
- `freshquant/backtest/clx/**` 或 `freshquant/rear/clx_backtest/**`
  - 重建 API Server
  - 重建 `fq_clx_backtest_worker`
- `morningglory/fqwebui/**`
  - 重建 Web UI
