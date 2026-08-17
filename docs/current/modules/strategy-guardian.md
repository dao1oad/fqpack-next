# Guardian 策略

## 职责

Guardian 是当前 A 股实时策略层。它负责把 XTData consumer 产生的结构信号转换成“是否提交买卖单”的策略意图，但它本身不是订单事实层，也不负责直接和 broker 交互。

Guardian 当前会把“本次卖量实际由哪些 entry 贡献出来”一起写入卖单请求，供 Order Management 在正常成交链和差额自动平账链里保持同一套卖出入口语义。

## 双账本（base / t，GitHub Issue #549）

当前订单账本（`om_position_entries` / `om_entry_slices`）按来源拆分为两个逻辑账本。
账本归属唯一入口是 `LedgerResolver`
（`freshquant/order_management/ledger_resolver.py`），Guardian 在提交时显式写
`om_order_requests.ledger_intent`：

- **底仓（base）**：首次开仓（`new_open`）、固定买入线（BUY-1/2/3）触发补仓、
  手动加仓（manual source，非首开）；Guardian 买入路径按
  `new_open`→`base`、`holding_add`→`t`、缺省 `base` 声明
  `ledger_intent`（#8）。
- **做T（t）**：Guardian 信号加仓（`holding_add`）、破线区（p ≤ BUY-3）深档
  买入；Guardian 做T卖出声明 `ledger_intent=t`。

entry 打标（`xt_reports.py::_resolve_entry_position_type`）只读请求
`ledger_intent`；broker-only（无请求，QMT 终端手动买入）显式归 base；缺失
fail-closed。先解析归属后聚类，禁止跨账本聚合，聚合成员携带
`position_type`。`strategy_context.buy_ledger` 已退役，不参与判定。

- 卖出分流：**TPSL 只卖 base**（比例基数 = Σ base remaining），**Guardian 只卖 t**（逐 slice 统一盈利谓词 + mount 过滤）。
- 手动/外部卖单（无 source plan）分摊三段分桶：① T 盈利低成本（卖单 `avg_filled_price` ≥ `guardian_price × (1 + percent/100)`，`guardian_price` 升序）→ ② 底仓 → ③ T 非盈利兜底；`om_exit_allocations` 记录被扣 slice 的 `position_type`。
- D/C 占用金额最简实现 = 该账本剩余股数 × 当前市场价（不按成本价聚合、无 cost_price 字段）。
- 历史回填：`script/maintenance/backfill_position_type.py`（flatten 幂等重建，
  已有标记保留、缺失 → base）与
  `script/maintenance/backfill_ledger_intent.py`（`ledger_intent` /
  `position_type` / 聚合成员归一回填 + L1/S1/D1 守恒校验 + 幂等复验；
  dry-run → execute）。存量止盈档批量激活为部署后的独立步骤
  `--activate-takeprofit`（新代码部署并重启后、非交易时段执行，天然幂等可重跑）。

### 固定价格触发买入线（对称阶梯状态机）

买入线执行器挂在 TPSL tick worker（`freshquant/tpsl/consumer.py`），universe = **当前持仓 ∩ 有 `guardian_buy_grid_configs`**（与 TP/SL universe 双集合隔离，不混入）。

- 触发：实时价格（bid1，无则 last）≤ BUY-N 且该线 armed 且 `buy_enabled[N]`；只补仓不建仓（空仓首开走 must_pool/手动）。
- 数量：`R_N = cap_N − max(D+C, MV) − 在途买单金额`（占用取大；MV 缺失 fail-closed 不买）；`B = R_N`；`B < min_buy_amount` 或不足一手不买（不消耗冷却）；独立冷却键 `base_buy:<code>`（15 分钟，与 T 侧 `buy:<code>` 隔离）。
- 对称阶梯状态机（`freshquant/strategy/guardian_ladder.py`，字段级原子 `$set` + 事件幂等 + 条件更新，不做整份读改写）：
  - 买入线触发（提交买单时）→ 关 BUY-N 及以上 + **全开止盈档**；
  - 止盈卖出成交 → 关 TP-1..TP-N + **全开买入线**（重激活后不当场评估，下一 tick）；
  - 零成交终态（撤单/废单/部分撤单未成交部分）→ 重开对应档位，按 `broker_order_id`/`intent_id`/`internal_order_id` 幂等；
  - 事件冲突：事件键已 claim，同键不重复处理；tick 路径下一 tick 以新
    `intent_id` 作为新事件键重试；XT ingest 路径当前事件内以 terminal 键
    有限重试并记录告警（A5 口径）。
- 幂等/并发契约（路线步骤 4，根④）：
  - `stock_signals` 建立唯一索引 `uq_stock_signals_signal_key`
    `(symbol, code, period, fire_time, position)`；建索引前自动清理历史重复
    （`$sort _id` 后分组，保留每组 `_id` 最小的一条，`allowDiskUse`）；
    建索引遇并发新重复时清重复后有限重试（3 次），最终失败仅告警放行；
    并发 upsert 的 DuplicateKeyError 按已存在处理，同一条信号只触发一次 `on_signal`
  - `guardian_ladder_events` 增加 `created_at_dt` 字段与 TTL 索引
    `ttl_guardian_ladder_events`（7 天过期，无界增长防护）；阶梯事件键来自
    当前 XT trade report/终态回调与当次 intent_id（非历史全量重扫），
    7 天窗口覆盖业务重试上界
  - `on_takeprofit_trigger` 的 `last_triggered_price` 并入主条件更新同一次
    `$set`（不再二次 update，消除竞态窗口）
- rearm 门控：仅 base 买入事件（首开 + buy 线触发 + 手动加仓）全开止盈档；**T 买入不触发状态机**。
- 配置校验：`TP1 > BUY-1`（及 BUY/TP 线序单调、caps 递增）倒挂 → fail-closed + 告警。
- 状态存储：`guardian_buy_grid_states.buy_line_armed`（缺省 `[true,true,true]`）+ `om_takeprofit_states.armed_levels`；`guardian_buy_grid_state` GET/POST/reset 暴露并保留该两字段，reset 语义 = 回缺省态（安全方向：最坏多买一次，受 R/冷却/min_buy_amount 约束）。

### 做T买入（四段走廊金字塔）

Guardian 持仓加仓数量（`build_holding_add_decision`）按价格四段走廊出量：

1. 回补走廊 `(最近止盈线, BUY-1]`：cap1（上界 = 最近高于当前价的止盈线，下界 = BUY-1）；
2. `[BUY-1, BUY-2]`：cap2；
3. `[BUY-2, BUY-3]`：cap3；
4. 破线区 `p ≤ BUY-3`：`global_cap` 基数、`B = R × 1/2` 收敛、冷却用 T 侧 `buy:<code>`。

`t = (上界 − p)/(上界 − 下界)`；`B = R × t^n`（`n = params.guardian.stock.buy_amount_exponent`，全局参数，默认 3，范围 [1, 5]，系统设置页可改；`n=2` 时按 `t×t` 快路径计算，与历史行为逐位一致）；`Q = floor(B/p/100)×100`；`B < min_buy_amount`（`params.guardian.stock.min_buy_amount`，默认/下限 10000）不买（不消耗冷却）；`p > 上界`（含 p > TP3 不买入区）不买；触线 `t=1` 归属抄底线 base 补仓，T 侧不重复。

做T买入门槛基准（`_resolve_guardian_buy_fill_reference`）：最近一笔 execution fill 成交价 → 全部持仓（base+T）剩余股数加权平均成本 → `xt_positions.avg_price` 兜底 → 三者皆无不买；无 fill_time 基准时跳过时序校验。已删除 `guardian_slice_next_level` 回退（情况2）及其函数。

## 入口

- 策略实现
  - `freshquant.strategy.guardian.StrategyGuardian`
- 事件驱动入口
  - `python -m freshquant.signal.astock.job.monitor_stock_zh_a_min --mode event`

当前正式运行口径只有 `--mode event`。

## 依赖

- XTData consumer 推送的 1 分钟与 5 分钟 bar 更新
- `must_pool`
- `xt_positions`
- Guardian buy grid 状态
- Position Management 门禁
- Order Management 提交服务
- Redis 冷却键

## 数据流

`bar update -> calculate_guardian_signals_latest -> save_a_stock_signal -> stock_signals -> StrategyGuardian.on_signal -> buy/sell decision -> submit_guardian_order -> OrderSubmitService`

当前正式 Guardian 事件链复用一个 `BarEventListener` 监听 `1min / 5min`，listener filter 使用 prefixed code，scope 判断与 `StrategyGuardian` 使用 base code。监听范围是当前持仓与 enabled `must_pool` 的并集，每 30 秒刷新。

- 1 分钟只处理当前持仓，沿用既有 Guardian 买卖行为，不附加首开 tag。
- 1 分钟入口继续过滤 `buy_zs_huila`。该信号底层仍可被 `calculate_guardian_signals_latest` 计算，但不会继续写入 `stock_signals`、页面展示或 `guardian_strategy` runtime trace。
- 5 分钟只处理 enabled `must_pool` 中的当前非持仓标的，只接受 `buy_v_reverse` 与 `macd_bullish_divergence`；`buy_zs_huila` 和全部卖点直接忽略。
- 5 分钟允许信号会在原 tags 后追加 `must_pool_5m_new_open`，再复用 `save_a_stock_signal -> StrategyGuardian.on_signal`。

`/stock-control` 的「must_pools买入信号」面板与上述 5 分钟监控产出口径一致（`period=5m` + `must_pool_5m_new_open` tag + enabled `must_pool`），避免口径再次分叉。

买入路径分为两类：

- 持仓加仓
  - `_handle_holding_buy`
  - 数量决策由 `GuardianBuyGridService.build_holding_add_decision()` 完成（#549 做T四段走廊，见「做T买入（四段走廊金字塔）」）：`R = cap − max(D+C, MV) − 在途`，`B = R × t^n`（`n` 为全局 `params.guardian.stock.buy_amount_exponent`，默认 3；破线区 `R × 1/2` 固定），受 `min_buy_amount` 与整手约束
- `_handle_holding_buy` 的 `timing_check` / `price_threshold_check` 以最近一笔 execution fill 成交价为基准（无 execution fill 时按全部持仓剩余股数加权平均成本、再兜底 `xt_positions.avg_price`），价格阈值沿用 `threshold` 配置；`fill_reference_source` 在 Trace 中标注（`execution_fill` / `ledger_average_cost` / `broker_position_avg_price`）
- 无 execution fill 基准时无 `fill_time` → 跳过时序校验（timing_check 仅在 fill_time 存在时执行）
- must_pool 新开仓
  - `_handle_new_open_buy`
  - 只有带 `must_pool_5m_new_open` tag、仍在 enabled `must_pool` 且当前非持仓的买点才能进入该分支
- `StrategyGuardian.on_signal` 的最终 scope gate 会跳过：带首开 tag 但已经持仓、带首开 tag 但已经移出/禁用 `must_pool`、以及未带首开 tag 的 must-pool-only 买点

卖出路径：

- 持仓内 `SELL_SHORT` 触发 `_handle_sell`
- **只扫 T 账本**（`position_type == "t"`）：纯底仓标的直接跳过（`no_t_position`，由 TPSL 止盈卖出）；无 arranged fills 时继续走既有 arrangement 降级检查（`arrangement_degraded` / `entry_without_slices`）
- `_handle_sell` 依赖 order management arranged fill 的最近 `date/time` 判断切片先后；对 `external_inferred` 历史 lot / slice，当前投影会在读路径按 `trade_time` 回填缺失时间，避免 Trace 在 `timing_check` 后因为 `last_fill date/time=None` 直接中断
- `_handle_sell` 的 `timing_check` / `price_threshold_check` 仍以 arranged fill 作为 Guardian 切片基准；Trace 同样会在 `decision_context.*.fill_reference_source` 标明该来源
- 卖出数量判定统一走 `freshquant.order_management.guardian.slice_evaluation.evaluate_guardian_sell_slices`：对每个 open slice 独立计算止盈阈值
  - percent 模式：`threshold = guardian_price * (1 + percent / 100)`
  - ATR 模式：`threshold = guardian_price + threshold_delta`（同一历史 ATR 参数逐 slice 使用）
  - 可卖判定：`normalized_signal_price >= threshold_price`；信号价先按 `0.01` 最小价位规范化（`Decimal` + `ROUND_HALF_UP`），阈值保留 `0.0001` 精度，不再依赖二进制 float 的 `>` 处理 `21.580000000000002 > 21.58` 边界
  - 返回值含 `raw_quantity / eligible_slices / threshold_evidence`，逐 slice 证据写入 `price_threshold_check` / `quantity_check` 的 Trace
- `_handle_sell` 只有至少一个 slice 达到独立阈值（`raw_quantity > 0`）才进入后续流程；随后统一按 `xt_positions.can_use_volume` 截断并按一手向下取整；只有 `sellable_volume_check` 通过后才继续冷却判断和下单提交
- mount 过滤：可卖金额（Σ 可卖 T slice 剩余 × 当前信号价）<
  `get_trade_amount`（mount，默认 50000）→ 本次不卖，可卖 slices 保留，
  不消耗 `sell:<code>` 冷却（A1 以代码为真值：金额按当前价而非买入成本价）
- `_handle_sell` 提交卖单时写入 `guardian_sell_sources` **version=2** 来源计划：`slices[]`（精确执行合同，每 slice 一行，携带 `entry_slice_id / guardian_price / threshold_price`）+ `entries[]`（按 entry 聚合唯一行）；来源计划只包含达到独立阈值的 slice，`sum(slices.quantity) == sum(entries.quantity) == submit_quantity`
- 历史 v1 请求（只有 `entries[]`，无 `entry_slice_id`）由 Order Management 按 entry 级剩余预算兼容处理

ATR 计算（总收口 PR7 收敛）：

- `freshquant/strategy/toolkit/threshold.py` 为唯一实现：
  `_compute_atr_last_stock / _compute_atr_last_index` 均返回
  `(atr_last, close_last)`，数据窗口锚定 `anchor_date` 前一交易日（前 60 日）
- index 版带 900s 内存缓存，缓存键含 `anchor_date`（交易日），避免跨日串值；
  stock 版不加缓存（qfq 调整输出禁止无版本感知缓存，治理测试约束）
- `eval_stock_threshold_price` 的 atr 模式取 `atr_last` 分量计算上下阈值，
  行为与收敛前一致
- `freshquant/data/astock/holding.py` 的同构拷贝已删除，`_query_grid_interval`
  委托 threshold 实现（`atr` 模式传入 `date_str` 作为 anchor）

## 存储

Guardian 自身不维护订单账本，但依赖以下状态：

- `must_pool`
  - enabled base-code 查询使用 60 秒进程缓存 TTL
- `xt_positions`
- `stock_signals`
  - 信号文档落库包含原始 `signal_type`（如 `macd_bullish_divergence`），
    Guardian 事件链保存时写入，供复盘读模型恢复真实信号类型（做T加仓订单
    不再被一律标成 `buy_zs_huila`）；旧调用方不传时不写该字段。
- Guardian buy grid 集合
  - `guardian_buy_grid_configs`
  - `guardian_buy_grid_states`
  - `audit_log`

Guardian buy grid 当前区分两类语义：
- `guardian_buy_grid_configs.buy_enabled`
  - 手工配置态，表示某层级是否允许参与 Guardian 买入层级判断
- `guardian_buy_grid_states.buy_active`
  - 只读审计态，不再作为买入准入条件；`_resolve_hit_levels()` 只按 `buy_enabled` 与 `price <= BUY-N` 判断命中，`buy_active=false` 不会阻止符合条件的买入

当前正式真义是 fail-closed：
- 缺失或非法 `max_position_amounts` 时跳过本次 Grid 买入（`grid_position_cap_unconfigured` / `grid_position_config_invalid`）
- 当前阶段开关 `buy_enabled[N]` 关闭时不买入，也不改变价格阶段映射（`grid_stage_disabled`）
- 实时仓位或全局单标的上限读不到时跳过（`position_capacity_unavailable`）
- 容量读取失败语义（路线步骤 3，根②）：账本占用、在途买单金额、TPSL 止盈价、
  仓位快照任一读不到即跳过买入并落 runtime event，不再静默按 0/空列表放行：
  - 账本占用读失败 → `ledger_occupancy_unavailable`（`guardian_buy_grid.load_ledger_occupancy`）
  - 在途买单读失败 → `pending_buy_amount_unavailable`（`guardian_buy_grid.load_pending_buy_amount`）
  - TPSL profile 读失败 → `takeprofit_prices_unavailable`（回补走廊跳过）
  - 仓位快照读失败 → `position_capacity_read_failed`（与「确认 MV 缺失」区分）
- 做T 买入链成交参照读失败（execution fills / OM entries / `xt_positions.avg_price`
  三级兜底任一读异常）→ 跳过买入并落 `fill_reference_unavailable`
  （`broker_position_reference_unavailable` 为 broker 级读失败细分码），
  与「确认无历史成交」区分
- 阶段剩余容量（按 `capacity_ratio` 折算后）不足一手时不买入（`grid_position_capacity_exhausted`）
- `guardian_buy_grid_states` 保留字段与 `last_hit_*` 审计记录；`reset_after_sell_trade` 或价格配置更新仍会把 `buy_active` 重置为全激活，仅作审计信息
- `guardian_buy_grid_states.buy_line_armed` 与 `om_takeprofit_states.armed_levels` 由 `guardian_ladder` 阶梯状态机统一读写（字段级原子 `$set`）

## 配置

- `params.guardian.stock.min_buy_amount`
  - 所有买入路径（买入线 / 破线区 / 做T）最小买入金额门槛，默认 10000、下限钳制 10000
- `monitor.xtdata.trading_mode`
  - 事件模式必须启用交易模式（默认 true）
  - `screening_mode` 不影响 Guardian 交易主链
- `monitor.xtdata.max_symbols`
- buy grid 初始金额与层级配置
- Redis 冷却键
  - `base_buy:<code>`（买入线，与 T 侧隔离）
  - `buy:<code>`
  - `sell:<code>`

15 分钟全局首开冷却已随 Issue #604 删除（路线步骤 7，D2）；
新开仓只受单标的 `buy:<code>` 冷却约束。

整手规则（路线步骤 7，根⑤/S3）：交易参数调用点统一走
`freshquant.trading.board_lot` helper——科创板（688/689）按上交所规则
买入 ≥200 股、1 股递增；其余 A 股 100 股整手。卖出侧对 <200 股科创板
余量按保守 0 处理（与 A 股不足一手余量行为对称；当前 OM 账本无科创板持仓）。

Guardian 对旧信号有 30 分钟时间窗限制；信号太旧会直接跳过。

## Runtime Observability 口径

Guardian 会把关键判断路径写入 `guardian_strategy` runtime event，不只依赖普通日志。当前结构化字段口径：

- 信号摘要：`signal_summary`
  - `code`
  - `name`
  - `position`
  - `period`
  - `price`
  - `fire_time`
  - `discover_time`
  - `remark`
  - `tags`
- 判断依据：`decision_branch`、`decision_expr`、`decision_context`
- 判断结果：`decision_outcome`、`reason_code`、`status`

当前关键节点：

- `receive_signal`
- `holding_scope_resolve`
- `timing_check`
- `price_threshold_check`
- `signal_structure_check`
- `cooldown_check`
- `quantity_check`
- `sellable_volume_check`
- `position_management_check`
- `submit_intent`
- `finish`

`price_threshold_check` / `quantity_check` 的 `decision_context.threshold` /
`decision_context.quantity` 当前会输出 `threshold_mode`、
`eligible_slice_count`、`eligible_slice_ids` 与逐 slice `threshold_evidence`
（每项含 `entry_id / entry_slice_id / guardian_price / threshold_price /
signal_price_normalized / eligible / eligible_quantity`），供 Position Review
与 `guardian.sell simulate` 共用同一份逐切片语义。

## 中枢隔离检查（signal_structure_check，A8 接线）

- 1min 持仓补仓线在信号生成时从 OM 读模型加载真实 arranged fills
  （`get_arranged_stock_fill_list`）注入 `stock_signals` 触发链：
  - 读不到（账本读异常）→ 信号不进交易链，`guardian_event.signal_gate`
    发 `reason_code=structure_context_unavailable`，不产生下单
  - 确认无历史成交（fills 为空）→ 放行（`no_fill_history`）
  - 有成交 → 按最近成交时间/价格与 payload `zsdata` 做分离中枢判断，
    语义与 `_evaluate_signal_structure` 原三条件一致
- 5min must_pool 首开线不加载 fills（首开无历史成交语义）
- 信号计算链失败语义（根②）：fqcopilot/fq_clxs 读不到或失败 → 对应 model
  不产生信号并落 `signal_calc_unavailable`；bi 列表读不到 → 本 bar 不产生
  Guardian 信号并落 `bi_list_unavailable`（合法全零 bi 列表不阻断）
- bar 时间非法（`_bar_time<=0`）的 bar 直接丢弃并计数，每个统计周期
  落 `guardian_event.signal_gate` `reason_code=invalid_bar_time_dropped`

#549 阶梯/双账本运行时事件载荷（复用既有节点，不新增页面结构）：
- `tpsl_worker.trigger_eval`：TP 命中/跳过携带 `ledger_filter`（base/t 切片数与
  剩余数量）与 `skip_reason`（`no_base_position` / `no_submittable_quantity`）；
  base-buyline 评估携带 `ledger_occupancy`、`pending_buy_amount`、
  `current_market_value`、`remaining_amount`、`min_buy_amount` 与 `skip_reason`；
  提交侧 `submit_intent` 携带 `ladder_triggered` / `ladder_event_key`。
- `xt_report_ingest.trade_match`：载荷携带 `ladder`（止盈成交阶梯重算的
  `kind / level / event_key / result{ok,attempts}`）与买入打标 `position_type`；
  `order_match` 携带零成交终态重开结果（`processed / kind /
  level_index|level / event_key / result`）。

首次开仓 scope 的关键 `decision_branch / reason_code` 为：

- 允许首开：`decision_branch=must_pool_5m_new_open_buy`，reason 为空
- 已经持仓：`must_pool_5m_new_open_already_holding`
- 已移出或禁用池：`must_pool_5m_new_open_not_in_pool`
- must-pool-only 买点缺少来源 tag：`must_pool_5m_new_open_tag_missing`

`finish` 用于表达 Guardian 自身未继续提交策略单时的终止结论；成功进入下单链时，以 `submit_intent` 作为 Guardian 侧最终节点。

如果 Guardian 在顶层 scope/timing 判断、buy/sell 具体分支或 `submit_intent` 后续执行中出现 unexpected exception，当前会直接在真实失败节点发 `status=error`、`reason_code=unexpected_exception` 的 runtime event，并保留 `payload.error_type/error_message`。不会再补一个兜底 `finish` 去掩盖异常出口节点。

## 部署/运行

- 正式运行在宿主机。
- 修改 `freshquant/strategy/**` 或 `freshquant/signal/**` 后，至少重启：

```powershell
python -m freshquant.signal.astock.job.monitor_stock_zh_a_min --mode event
```

## 排障点

### 有信号但完全不触发

- 检查是否跑在 `--mode event`
  - 检查 `monitor.xtdata.trading_mode` 是否为 true
  - `screening_mode=true` 且 `trading_mode=false` 只运行 CLX 实时模型，不运行 Guardian event

### BUY_LONG 信号没有下单

- 普通买点检查目标 code 是否在 `xt_positions`；must-pool-only 首开检查信号是否为 5 分钟允许类型并带 `must_pool_5m_new_open`
- 检查目标 code 当前是否仍在 enabled `must_pool`，或是否已成为持仓；对应 scope skip reason 会写入 `guardian_strategy`
- 检查 `buy:<code>` 冷却键
- 检查 Position Management 是否拒绝
- 检查 `guardian_buy_grid_states`
  - 若缺失 state，Guardian buy grid 当前会按运行态未激活处理，不会命中 `BUY-1/2/3`
- 在 `/runtime-observability` 选中 `guardian_strategy` 看板，直接看 recent trace 的信号摘要与最终结论
- 打开对应节点详情，优先看 `decision_expr`、`decision_context`、`decision_outcome`

### 新开仓长期不生效

- 检查 `queryMustPoolCodes` 60 秒 TTL 到期后的 enabled 池结果
- 检查单标的 `buy:<code>` 是否还在冷却窗口
- 检查该成员是否已过期/被 disabled（`must_pool` 的 `expire_at` / `memberships.expire_at`
  与 `disabled` 字段，步骤 7 D1/S4：非 active 成员不可 5m 首开）
- 检查 buy grid 计算出的 `quantity` 是否为 0

### 卖出后继续沿用旧层级

- 检查 XT 回报 ingest 是否已经调用 Guardian buy grid reset
- 检查卖出成交是否真正进入 `om_trade_facts`
