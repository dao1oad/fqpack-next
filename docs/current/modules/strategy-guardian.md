# Guardian 策略

## 职责

Guardian 是当前 A 股实时策略层。它负责把 XTData consumer 产生的结构信号转换成“是否提交买卖单”的策略意图，但它本身不是订单事实层，也不负责直接和 broker 交互。

## 入口

- 策略实现
  - `freshquant.strategy.guardian.StrategyGuardian`
- 事件驱动入口
  - `python -m freshquant.signal.astock.job.monitor_stock_zh_a_min --mode event`

当前正式运行口径只有 `--mode event`。

## 依赖

- XTData consumer 推送的 1 分钟 bar 更新
- `must_pool`
- `xt_positions`
- Guardian buy grid 状态
- Position Management 门禁
- Order Management 提交服务
- Redis 冷却键

## 数据流

`bar update -> calculate_guardian_signals_latest -> save_a_stock_signal -> stock_signals -> StrategyGuardian.on_signal -> buy/sell decision -> submit_guardian_order -> OrderSubmitService`

当前正式 Guardian 事件链会在入口直接过滤 `buy_zs_huila`。该信号底层仍可被 `calculate_guardian_signals_latest` 计算，但不会继续写入 `stock_signals`、页面展示或 `guardian_strategy` runtime trace。

买入路径分为两类：

- 持仓加仓
  - `_handle_holding_buy`
- must_pool 新开仓
  - `_handle_new_open_buy`

卖出路径：

- 持仓内 `SELL_SHORT` 触发 `_handle_sell`
- `_handle_sell` 依赖 order management arranged fill 的最近 `date/time` 判断切片先后；对 `external_inferred` 历史 lot / slice，当前投影会在读路径按 `trade_time` 回填缺失时间，避免 Trace 在 `timing_check` 后因为 `last_fill date/time=None` 直接中断

## 存储

Guardian 自身不维护订单账本，但依赖以下状态：

- `must_pool`
- `xt_positions`
- `stock_signals`
- Guardian buy grid 集合
  - `guardian_buy_grid_configs`
  - `guardian_buy_grid_states`
  - `audit_log`

## 配置

- `monitor.xtdata.mode`
  - 事件模式必须启用 Guardian 能力
  - 正式值：
    - `guardian_1m`
    - `guardian_and_clx_15_30`
- `monitor.xtdata.max_symbols`
- buy grid 初始金额与层级配置
- Redis 冷却键
  - `buy:<code>`
  - `sell:<code>`
  - `fq:xtrade:last_new_order_time`

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
- `position_management_check`
- `submit_intent`
- `finish`

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
- 检查 `monitor.xtdata.mode` 是否是 `guardian_1m` 或 `guardian_and_clx_15_30`

### BUY_LONG 信号没有下单

- 检查目标 code 是否在 `must_pool` 或 `xt_positions`
- 检查 `buy:<code>` 冷却键
- 检查 Position Management 是否拒绝
- 在 `/runtime-observability` 选中 `guardian_strategy` 看板，直接看 recent trace 的信号摘要与最终结论
- 打开对应节点详情，优先看 `decision_expr`、`decision_context`、`decision_outcome`

### 新开仓长期不生效

- 检查 `fq:xtrade:last_new_order_time` 是否还在冷却窗口
- 检查 buy grid 计算出的 `quantity` 是否为 0

### 卖出后继续沿用旧层级

- 检查 XT 回报 ingest 是否已经调用 Guardian buy grid reset
- 检查卖出成交是否真正进入 `om_trade_facts`
