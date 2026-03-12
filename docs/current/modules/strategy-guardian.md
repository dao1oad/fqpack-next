# Guardian 策略

## 职责

Guardian 是当前 A 股实时策略层。它负责把 XTData consumer 产生的结构信号转换成“是否提交买卖单”的策略意图，但它本身不是订单事实层，也不负责直接和 broker 交互。

## 入口

- 策略实现
  - `freshquant.strategy.guardian.StrategyGuardian`
- 事件驱动入口
  - `python -m freshquant.signal.astock.job.monitor_stock_zh_a_min --mode event`
- 旧轮询入口
  - 同模块 `--mode poll`

当前正式运行口径是 `--mode event`。

## 依赖

- XTData consumer 推送的 1 分钟 bar 更新
- `must_pool`
- `xt_positions`
- Guardian buy grid 状态
- Position Management 门禁
- Order Management 提交服务
- Redis 冷却键

## 数据流

`bar update -> calculate_guardian_signals_latest -> save_a_stock_signal -> StrategyGuardian.on_signal -> buy/sell decision -> submit_guardian_order -> OrderSubmitService`

买入路径分为两类：

- 持仓加仓
  - `_handle_holding_buy`
- must_pool 新开仓
  - `_handle_new_open_buy`

卖出路径：

- 持仓内 `SELL_SHORT` 触发 `_handle_sell`

## 存储

Guardian 自身不维护订单账本，但依赖以下状态：

- `must_pool`
- `xt_positions`
- Guardian buy grid 集合
  - `guardian_buy_grid_configs`
  - `guardian_buy_grid_states`
  - `audit_log`

## 配置

- `monitor.xtdata.mode`
  - 事件模式必须是 `guardian_1m`
- `monitor.xtdata.max_symbols`
- buy grid 初始金额与层级配置
- Redis 冷却键
  - `buy:<code>`
  - `sell:<code>`
  - `fq:xtrade:last_new_order_time`

Guardian 对旧信号有 30 分钟时间窗限制；信号太旧会直接跳过。

## 部署/运行

- 正式运行在宿主机。
- 修改 `freshquant/strategy/**` 或 `freshquant/signal/**` 后，至少重启：

```powershell
python -m freshquant.signal.astock.job.monitor_stock_zh_a_min --mode event
```

## 排障点

### 有信号但完全不触发

- 检查是否跑在 `--mode event`
- 检查 `monitor.xtdata.mode=guardian_1m`

### BUY_LONG 信号没有下单

- 检查目标 code 是否在 `must_pool` 或 `xt_positions`
- 检查 `buy:<code>` 冷却键
- 检查 Position Management 是否拒绝

### 新开仓长期不生效

- 检查 `fq:xtrade:last_new_order_time` 是否还在冷却窗口
- 检查 buy grid 计算出的 `quantity` 是否为 0

### 卖出后继续沿用旧层级

- 检查 XT 回报 ingest 是否已经调用 Guardian buy grid reset
- 检查卖出成交是否真正进入 `om_trade_facts`
