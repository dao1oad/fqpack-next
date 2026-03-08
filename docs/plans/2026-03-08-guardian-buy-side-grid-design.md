# Guardian Buy-Side Grid Design

**目标**：为 Guardian 策略补齐 buy-side 三层价格配置与最小状态机，在不回退 legacy 的前提下，把“首次新开仓”和“持仓加仓”的数量规则稳定下来，并将配置、状态、订单决策上下文暴露给现有 API/CLI 与订单域。

## 1. 设计结论

- Guardian 普通买单数量继续由策略层计算，不下沉到仓位管理模块。
- 新开仓不看 `BUY-1/2/3`，只依赖 `must_pool`、Guardian 信号与仓位管理准入。
- 新开仓金额优先使用 `must_pool.initial_lot_amount`，默认 `150000`，缺失时回退 `lot_amount`。
- 持仓加仓才读取 `BUY-1/2/3`，层级判定使用事件模式信号里的 `signal.price`。
- 命中多个层级时取最深命中层级，倍率固定为 `BUY-1/2/3 -> 2/3/4`。
- 订单域成功受理后，失活所有命中的层级；卖出成交事实落地后，重置该标的全部 `buy_active=True`。
- 未配置三层价格时，Guardian 持仓加仓退化为基础金额，新开仓仍允许执行。
- `near_pattern:*` 与旧 `position_pct` 缩量规则从 Guardian 买单数量链路移除。
- 三层价格配置、当前状态和状态重置通过现有 stock API / CLI 暴露。
- 订单域与日志上下文必须保留 `grid_level`、`hit_levels`、`multiplier`、`source_price`、`buy_prices_snapshot`、`buy_active_before/after`、`path`。

## 2. 方案范围

### In Scope

- Guardian buy-side 配置与状态的数据模型。
- Guardian 主流程的新开仓 / 持仓加仓数量计算重构。
- 成功受理后的层级失活与卖出成交后的状态重置。
- stock blueprint / CLI 的 Guardian buy-side grid 配置与状态入口。
- 订单上下文补齐与测试。

### Out of Scope

- Guardian 卖出数量重构。
- 仓位管理第三层级强制卖出算法实现。
- 旧 Grid sell-side 配置、卖出层级状态机与完整双向交易引擎。
- 轮询模式 Guardian 进场逻辑。

## 3. 模块落点

- `freshquant/strategy/guardian.py`
  - 接入 Guardian buy-side grid 服务。
  - 删除旧的 `position_pct` / `near_pattern` 买入数量缩放。
  - 新开仓与持仓加仓都统一改为“订单受理成功后才写冷却 key”。
- `freshquant/strategy/guardian_buy_grid.py`
  - Guardian buy-side grid 的配置、状态、命中层级、数量计算与受理后状态更新逻辑。
- `freshquant/order_management/ingest/xt_reports.py`
  - 在卖出成交事实落地后重置 Guardian buy-side 状态。
- `freshquant/rear/stock/routes.py`
  - 暴露 `GET/POST` Guardian buy-side grid 配置、状态与 reset 接口。
- `freshquant/command/stock.py`
  - 暴露 `stock.guardian-grid` 子命令。

## 4. 数据模型

建议沿用 RFC 0019 的集合名：

- `guardian_buy_grid_configs`
- `guardian_buy_grid_states`

`guardian_buy_grid_configs` 最小字段：

- `code`
- `buy_1`
- `buy_2`
- `buy_3`
- `enabled`
- `updated_at`
- `updated_by`

`guardian_buy_grid_states` 最小字段：

- `code`
- `buy_active`
- `last_hit_level`
- `last_hit_price`
- `last_hit_signal_time`
- `last_reset_reason`
- `updated_at`
- `updated_by`

## 5. 关键行为

### 5.1 新开仓

- 条件：`must_pool`、Guardian 买点信号、仓位管理允许开新仓。
- 数量：
  - `initial_amount = initial_lot_amount ?? lot_amount ?? 150000`
  - `quantity = floor(initial_amount / signal.price / 100) * 100`
- 不读取、不消费 grid 层级状态。

### 5.2 持仓加仓

- 条件：标的当前属于持仓股。
- 基础金额：
  - `base_amount = get_trade_amount(symbol)`
- 层级命中：
  - 读取 `buy_1/buy_2/buy_3`
  - 用 `signal.price` 判断所有命中层级
  - 只在 `buy_active[level-1]` 为 `True` 时视为有效命中
  - 有多个命中时取最深层级
- 数量：
  - `quantity = floor((base_amount * multiplier) / signal.price / 100) * 100`
- 受理成功后：
  - 失活所有命中的层级

### 5.3 卖出成交后重置

- 任意卖出成交事实落地后：
  - 将该标的 `buy_active=[True, True, True]`
  - 清理或覆盖最近命中信息
  - 记录 `last_reset_reason=sell_trade_fact`

## 6. 测试策略

- 单元测试：
  - 无配置回退基础金额。
  - 最深命中优先。
  - 受理成功后失活所有命中层级。
  - 已失活层级不重复生效。
  - 卖出成交后重置全部 `buy_active`。
- 集成测试：
  - Guardian 持仓加仓命中 `BUY-3` 时数量按 `4x` 计算。
  - 新开仓使用 `initial_lot_amount`。
  - API/CLI 可读写配置与状态。
  - 订单上下文包含 grid 相关字段。

## 7. 风险

- Guardian 当前逻辑集中在单文件，数量规则变动会牵动冷却、日志与订单提交路径，必须先由测试锁住。
- buy-side 状态更新分散在“受理成功”和“卖出成交”两个节点，若实现不统一，容易出现状态漂移。
- 旧仓 grid 逻辑语义较多，本轮只迁移最小 buy-side 状态机，必须严格防止 sell-side 语义被顺手带入。
