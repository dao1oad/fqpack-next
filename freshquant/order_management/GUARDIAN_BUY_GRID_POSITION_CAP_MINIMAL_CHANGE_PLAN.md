# Guardian 三档买入 Grid 按仓位上限控制——最终最小修改方案

> 本文为分项分析稿。2026-08-04 联合评审后的实施真值见
> `GUARDIAN_GRID_AND_TAKEPROFIT_FINAL_MINIMAL_CHANGE_PLAN.md`。

## 1. 目标

将 Guardian 当前的三档买入倍率：

```text
BUY-1 -> 2 倍
BUY-2 -> 3 倍
BUY-3 -> 4 倍
```

改为三条价格线对应的阶段仓位金额上限：

```text
CAP-1
CAP-2
CAP-3
```

三条价格线决定当前价格所属区间，三个 CAP 表示价格运行到对应区间时允许达到的
单标的最大仓位金额。每次实际买入仍以现有基础买入金额为准，不按倍率放大，也不
一次补满 CAP。

本方案基于 2026 年 8 月 4 日当前工作区代码和与 Devin Ultra 的联合评审结论，
只修改当前主链中直接相关的价格区间、数量计算、最终仓位门禁、配置和展示。

## 2. 最终产品规则

### 2.1 四个价格区间

假设：

```text
BUY-1 > BUY-2 > BUY-3 > 0
0 < CAP-1 <= CAP-2 <= CAP-3 <= global symbol limit
```

当前 Tick 价格对应规则如下：

| 当前价格 | 当前阶段 | 当前有效阶段上限 | 本阶段开关 |
| --- | --- | ---: | --- |
| `price > BUY-1` | BUY-1 前 | `CAP-1` | BUY-1 switch |
| `BUY-2 < price <= BUY-1` | BUY-1 至 BUY-2 | `CAP-2` | BUY-2 switch |
| `BUY-3 < price <= BUY-2` | BUY-2 至 BUY-3 | `CAP-3` | BUY-3 switch |
| `price <= BUY-3` | BUY-3 以下 | 全局单标的仓位上限 | BUY-3 switch |

这里的“BUY-N switch”沿用当前 `buy_enabled[N-1]`。

重要语义：

1. 价格区间由三条价格线固定决定；
2. `buy_enabled` 只决定当前价格阶段是否允许 Guardian 买入；
3. 关闭一条线不会改变价格区间，也不会把当前价格映射到其他 CAP；
4. `price <= BUY-3` 使用 Position Management 当前生效的全局单标的仓位上限，
   不再增加第四个标的级 CAP；
5. `new_open` 也受 `CAP-1` 控制。

### 2.2 CAP 是上限，不是目标仓位

例如：

```text
当前阶段 CAP = 300000
当前实时市值 = 220000
本次基础买入金额 = 50000
```

本次仍只买约 50000 元，而不是直接补到 300000 元。

如果：

```text
当前阶段 CAP = 300000
当前实时市值 = 280000
本次基础买入金额 = 50000
```

本次最多只允许使用剩余约 20000 元容量，并按 100 股整手向下取整。

## 3. 当前代码事实

### 3.1 当前主链

```text
Guardian 收到 Tick
-> freshquant/strategy/guardian.py
-> GuardianBuyGridService.build_holding_add_decision()
-> 生成 quantity 和 strategy_context
-> OrderSubmitService
-> PositionManagementService 最终门禁
-> 订单管理原提交链
```

新开仓数量由：

```text
must_pool.initial_lot_amount
-> must_pool.lot_amount
-> DEFAULT_INITIAL_LOT_AMOUNT
```

解析。

持仓加仓基础金额由当前：

```text
instrument_strategy.lot_amount
or guardian.stock.lot_amount
```

解析。

这些基础金额来源保持不变。

### 3.2 当前倍率

当前文件：

```text
freshquant/strategy/guardian_buy_grid.py
```

存在：

```python
BUY_LEVEL_MULTIPLIERS = {
    "BUY-1": 2,
    "BUY-2": 3,
    "BUY-3": 4,
}
```

`build_holding_add_decision()` 当前使用：

```text
amount = base_amount * multiplier
```

本次直接删除倍率参与数量计算的逻辑。

### 3.3 当前 `buy_active`

当前 `_resolve_hit_levels()` 同时检查：

```text
buy_enabled
buy_active
price <= level_price
```

订单被受理后，`mark_buy_order_accepted()` 会把命中的 `buy_active` 设置为
`false`，导致同一轮运行中对应价位只能买一次。

这与“价格阶段对应最大仓位、未达到上限可以继续按基础金额买入”的新语义冲突。

最终规则是：

- `_resolve_hit_levels()` 不再使用 `buy_active` 作为买入准入条件；
- `buy_active` 不再表示阶段容量，也不再阻止重复基础买入；
- 为降低迁移范围，可暂时保留字段、状态读写和 `last_hit_*` 记录；
- 前端删除“运行态 X/3”展示，避免继续赋予该字段业务含义。

### 3.4 当前 Position Management 门禁缺口

当前：

```text
freshquant/position_management/service.py
PositionManagementService._apply_single_symbol_position_limit()
```

只判断：

```python
market_value >= effective_limit
```

如果当前市值低于上限，但加上本单后超过上限，当前门禁仍会放行。

订单提交给 Position Management 的 payload 已经包含：

```text
price
quantity
```

因此修复 projected amount 不需要新增接口合同。

## 4. 数量计算

### 4.1 识别当前价格阶段

价格阶段必须按区间直接判断，不能继续使用“命中了多少条
`price <= BUY-N` 条件”来推断。

伪代码：

```python
if price > buy_1:
    stage = "PRE-BUY-1"
    stage_level = "BUY-1"
    stage_cap = cap_1
elif price > buy_2:
    stage = "BUY-1"
    stage_level = "BUY-2"
    stage_cap = cap_2
elif price > buy_3:
    stage = "BUY-2"
    stage_level = "BUY-3"
    stage_cap = cap_3
else:
    stage = "BUY-3"
    stage_level = "BUY-3"
    stage_cap = global_symbol_limit
```

随后检查：

```python
if not buy_enabled[index_of(stage_level)]:
    skip("grid_stage_disabled")
```

### 4.2 有效上限

前三个区间运行时仍需受全局上限兜底：

```text
effective_stage_cap =
    min(configured_stage_cap, global_symbol_limit)
```

BUY-3 以下：

```text
effective_stage_cap = global_symbol_limit
```

### 4.3 当前仓位金额

统一读取当前已有的：

```text
pm_symbol_position_snapshots.market_value
```

作为本次决策时的实时仓位市值。

不使用买入成本价计算阶段容量。三个 CAP 表达的是当前市场价格下的仓位金额上限，
与 Position Management 现有单标的仓位上限口径保持一致。

### 4.4 最终数量

```text
remaining_amount =
    effective_stage_cap - current_market_value

capacity_quantity =
    floor_to_board_lot(remaining_amount / decision_price)

base_quantity =
    floor_to_board_lot(base_amount / decision_price)

final_quantity =
    min(base_quantity, max(capacity_quantity, 0))
```

其中：

- `decision_price` 沿用 Guardian 当前用于生成订单数量的 Tick 价格；
- `floor_to_board_lot()` 沿用当前 100 股整手向下取整；
- `remaining_amount <= 0` 时不提交；
- `capacity_quantity < 100` 时不提交；
- 不使用 2/3/4 倍率；
- 不一次补满 CAP。

### 4.5 新开仓

当前新开仓路径不能绕过 CAP：

```text
base_amount = initial_lot_amount
stage = price 对应阶段
final_quantity = min(initial_base_quantity, stage_capacity_quantity)
```

通常未持仓时 `current_market_value = 0`，但仍必须执行同一套容量计算，以覆盖：

- 仓位快照存在而 Guardian 分支判断为新开仓；
- `initial_lot_amount > CAP-1`；
- 标的全局上限低于初始买入金额。

## 5. 下单前撤旧买单再重新计算

为避免旧买单尚未成交、仓位快照尚未增加时再次提交基础买入量，Guardian 每次准备
提交某标的新买单前，先处理该标的已有的未完成买单。

### 5.1 当前已经存在的能力

当前项目已经具备完整的通用撤单链，本次直接复用，不再实现第二套撤单逻辑：

```text
OrderManagementReadService.list_orders()
-> 已支持按 symbol / side / state 查询订单

OrderSubmitService.cancel_order()
-> 创建 CANCEL_REQUESTED
-> 写入撤单 request 和 event
-> 将 cancel payload 推入 STOCK_ORDER_QUEUE

fqxtrade broker
-> dispatch_cancel_execution()
-> xt_trader.cancel_order_stock()

XT 订单回报 ingest
-> 将订单更新为 CANCELED / PARTIAL_FILLED / FILLED / FAILED
```

当前缺少的只有：

```text
Guardian 新买单提交前，没有调用现有订单查询和撤单服务。
```

因此本次只增加 Guardian 的调用编排：

```text
查现有活动买单
-> 调现有 cancel_order()
-> 当前 Tick 结束
-> 后续 Tick 复用现有订单状态判断是否可以重新挂单
```

不新增撤单 API、撤单队列、撤单执行器、撤单状态或 XTQuant 撤单适配。

仓库中的旧 `fqpuppet.cancel_buy(symbol)` 属于旧 GUI 交易客户端能力；当前正式运行链
使用 `fqxtrade + XTQuant + Order Management`，本方案不重新接回旧客户端。

这里的“所有未成交订单”精确定义为：

```text
同一账户
+ 同一标的
+ side = buy
+ Order Management 中仍处于活动状态的订单
+ source_type 不是 external_reported / external_inferred
```

活动状态包括：

```text
ACCEPTED
QUEUED
SUBMITTING
SUBMITTED
PARTIAL_FILLED
CANCEL_REQUESTED
```

不撤销该标的卖单。止盈、止损和人工卖出可能承担风险控制作用，不能因为 Guardian
准备加仓而被一并撤销。

券商侧或人工产生、由系统识别为 `external_reported` / `external_inferred` 的活动
买单也不自动撤销；检测到这类买单时直接阻止 Guardian 新买单，并记录
`external_active_buy_order`。这样既避免覆盖人工操作，也不会让 Guardian 再增加一笔
并行买单。

### 5.2 最小执行顺序

```text
Guardian 买入信号
-> 原有 15 分钟买入冷却检查
-> 调用现有 OrderManagementReadService 查询该标的全部活动买单

存在尚未发起撤单的活动买单
-> 调用现有 OrderSubmitService.cancel_order()
-> 本 Tick 只撤单，不提交新买单

存在 CANCEL_REQUESTED 买单
-> 本 Tick 跳过，等待现有成交回报更新终态

存在外部/人工活动买单
-> 不自动撤单
-> 本 Tick 跳过

不存在活动买单
-> 重新读取最新仓位市值
-> 重新识别价格阶段
-> 重新计算阶段容量和基础买入量
-> Position Management 执行 projected market value 门禁
-> 提交一笔新买单
```

“重新挂单”不是沿用旧订单的价格和数量，而是在旧单退出活动状态后，使用最新 Tick、
最新仓位和最新 CAP 完整重算。

查询必须读取全部匹配订单，不能受 `list_orders()` 默认 20 条分页截断。

### 5.3 为什么当前 Tick 只撤单

撤单请求提交成功只表示：

```text
CANCEL_REQUESTED
```

不代表券商已经确认撤单。旧订单可能在撤单到达前发生部分成交或全部成交。

因此不能采用：

```text
发送撤单请求
-> 同一个 Tick 立即提交新买单
```

否则旧单和新单仍可能同时成交。

最小实现不增加等待线程或新的状态机，而是直接复用现有订单状态：

- 本 Tick 发起撤单后结束；
- 后续 Tick 看到 `CANCEL_REQUESTED` 时继续跳过；
- 收到 `CANCELED`、`FILLED` 或 `FAILED` 等终态后，活动订单查询自然为空；
- 再按最新事实重新计算并提交新单。

### 5.4 部分成交和撤单失败

旧单已经部分成交时：

```text
保留已成交部分
-> 撤销未成交余量
-> 等待订单退出活动状态
-> 用更新后的仓位重新计算新单
```

撤单失败或旧单仍处于活动状态时：

```text
不提交新买单
```

这使买入控制保持 fail-closed，不会因为撤单异常产生第二笔并行买单。

### 5.5 最终三层控制

```text
第一层：同标的活动买单只能保留一笔，换单前先撤旧单
第二层：Guardian 按最新仓位快照计算阶段剩余容量
第三层：Position Management 检查本单后的 projected market value
```

本方案继续复用现有 15 分钟冷却、撤单接口、订单状态和成交回报，不增加仓位预留
集合、活动委托金额计算、分布式锁或新的订单生命周期。

## 6. Position Management 最终门禁

仅修改当前单标的仓位上限判断：

```text
projected_market_value =
    current_market_value + price * quantity
```

判断规则：

```text
current_market_value is None
-> 拒绝

projected_market_value > effective_limit
-> 拒绝

projected_market_value <= effective_limit
-> 放行
```

允许本单执行后恰好等于上限。

Position Management 只兜底当前生效的全局单标的仓位上限，不识别
CAP-1/CAP-2/CAP-3。阶段 CAP 仍由 Guardian 决策，避免把 Guardian 的价格策略
侵入通用仓位管理模块。

## 7. 配置合同

沿用当前 Guardian Grid 配置记录，增加三个金额：

```json
{
  "code": "TARGET",
  "BUY-1": 10.0,
  "BUY-2": 9.0,
  "BUY-3": 8.0,
  "max_position_amounts": [
    200000,
    350000,
    500000
  ],
  "buy_enabled": [
    true,
    true,
    true
  ],
  "enabled": true
}
```

字段对应关系：

```text
max_position_amounts[0] = CAP-1
max_position_amounts[1] = CAP-2
max_position_amounts[2] = CAP-3
```

保存校验：

1. `BUY-1 > BUY-2 > BUY-3 > 0`；
2. `max_position_amounts` 必须恰好包含三个正整数；
3. `CAP-1 <= CAP-2 <= CAP-3`；
4. 三个 CAP 不高于保存时可读取到的全局单标的上限；
5. 价格、CAP 和 `buy_enabled` 在同一次更新中保存。

运行时仍执行：

```text
min(stage_cap, current_global_symbol_limit)
```

因此后续降低全局上限时无需批量改写已有标的配置。

旧记录缺少 `max_position_amounts` 时，不从旧倍率反推 CAP，也不静默使用
2/3/4 倍基础金额。当前价格阶段缺少所需 CAP 时跳过买入，并记录：

```text
grid_position_cap_unconfigured
```

## 8. `strategy_context` 最小调整

继续使用现有：

```text
strategy_context.guardian_buy_grid
```

删除倍率的业务含义，增加本次决策需要的解释字段：

```json
{
  "guardian_buy_grid": {
    "path": "holding_add",
    "grid_level": "BUY-2",
    "stage": "BUY-1",
    "source_price": 9.5,
    "base_amount": 50000,
    "effective_stage_cap": 350000,
    "current_market_value": 280000,
    "remaining_amount": 70000,
    "base_quantity": 5200,
    "capacity_quantity": 7300,
    "final_quantity": 5200,
    "buy_prices_snapshot": {
      "BUY-1": 10.0,
      "BUY-2": 9.0,
      "BUY-3": 8.0
    }
  }
}
```

为兼容已有消费者，`multiplier` 可在一个版本内固定写为 `1`，但不再参与任何计算；
若检索确认没有外部依赖，可直接删除该字段。

`last_hit_level` 可继续记录本次使用的阶段开关/价位，仅作为审计信息。

## 9. 最小代码修改范围

### 9.1 核心策略

```text
freshquant/strategy/guardian_buy_grid.py
```

修改：

1. 删除 `BUY_LEVEL_MULTIPLIERS`；
2. 将价格命中逻辑改为四区间识别；
3. `_resolve_hit_levels()` 不再以 `buy_active` 作为准入；
4. 根据阶段 CAP、实时市值和基础金额计算最终数量；
5. 新开仓路径也执行 CAP 计算；
6. `mark_buy_order_accepted()` 只保留 `last_hit_*` 审计作用，不再消费
   `buy_active`。

```text
freshquant/strategy/guardian.py
```

修改：

1. 为买入决策提供当前 `market_value` 和全局单标的上限，或调用现有读取服务；
2. 原有 15 分钟冷却通过后，调用现有 `OrderManagementReadService.list_orders()`
   查询同标的活动买单；
3. 对尚未撤单的活动买单直接调用现有 `OrderSubmitService.cancel_order()`；
4. 存在活动买单时当前 Tick 不提交新单；
5. 活动买单全部终结后重新读取仓位并重新计算；
6. 数量为 0 时记录明确 reason code；
7. 调整 `strategy_context`，去除倍率含义并记录 CAP 决策数据；
8. 保留现有订单提交和异常处理。

实现时应优先让 `GuardianBuyGridService` 完成纯数量决策，避免在
`guardian.py` 再写第二套区间和容量公式。

### 9.2 Position Management

```text
freshquant/position_management/service.py
```

只将当前：

```text
market_value >= effective_limit
```

改为：

```text
market_value + price * quantity > effective_limit
```

并保留快照缺失时的现有拒绝行为。

### 9.3 配置、API 和读模型

按现有调用链精确修改：

```text
freshquant/rear/stock/routes.py
freshquant/rear/subject_management/routes.py
freshquant/subject_management/write_service.py
freshquant/subject_management/dashboard_service.py
```

职责仅包括：

- 接收和保存 `max_position_amounts`；
- 校验价格与 CAP 顺序；
- 返回三个配置 CAP 和当前有效上限；
- 不增加新的状态集合。

### 9.4 前端

按现有使用点精确修改：

```text
morningglory/fqwebui/src/views/KlineSlim.vue
morningglory/fqwebui/src/views/subjectManagement.mjs
morningglory/fqwebui/src/views/js/kline-slim-price-panel.mjs
```

修改：

- 三条买入线各增加“最大仓位金额”输入；
- 删除倍率展示；
- 删除“运行态 X/3”展示；
- 保留三条价格线和三个 `buy_enabled` 开关；
- 展示当前价格阶段、当前阶段 CAP、实时市值和剩余容量时，只使用后端返回值，
  前端不重复实现决策公式。

最终文件范围以实施前的调用检索为准；未实际使用上述字段的文件不做改动。

## 10. 明确保持不变

以下主链保持原逻辑：

```text
freshquant/order_management/submit/guardian.py
freshquant/order_management/submit/service.py
freshquant/order_management/tracking/**
freshquant/order_management/ingest/**
```

具体包括：

- 订单受理；
- 下单队列；
- broker/puppet；
- `OrderManagementReadService` 的现有订单查询；
- `OrderSubmitService.cancel_order()`；
- `dispatch_cancel_execution()`；
- `xt_trader.cancel_order_stock()`；
- 现有撤单和委托状态；
- 成交回报；
- 买入成交后的账本入账；
- 现有 15 分钟买入冷却。

本次不增加：

- 新的买入状态机；
- 新的订单生命周期；
- 仓位预留集合；
- 活动委托容量模型；
- 分布式锁；
- 快照年龄协议；
- tracking 或 ingest 改造。

## 11. 最小测试范围

### 11.1 Guardian Grid

重点文件：

```text
freshquant/tests/test_guardian_buy_grid.py
freshquant/tests/test_guardian_strategy.py
```

至少覆盖：

1. `price > BUY-1` 使用 CAP-1 和 BUY-1 switch；
2. `BUY-2 < price <= BUY-1` 使用 CAP-2 和 BUY-2 switch；
3. `BUY-3 < price <= BUY-2` 使用 CAP-3 和 BUY-3 switch；
4. `price <= BUY-3` 使用全局单标的上限和 BUY-3 switch；
5. 关闭当前阶段开关后跳过，不映射到其他阶段；
6. 删除 2/3/4 倍率后始终以基础金额计算；
7. 基础数量小于容量时使用基础数量；
8. 容量小于基础数量时按容量截断；
9. 容量不足 100 股时不提交；
10. `new_open` 也受 CAP-1/当前阶段 CAP 控制；
11. `buy_active=false` 不再阻止符合条件的买入；
12. 缺少当前阶段 CAP 时跳过并记录明确原因；
13. 无活动买单时正常提交一笔新买单；
14. 存在 `SUBMITTED` 买单时只发起撤单，当前 Tick 不提交新单；
15. 存在 `PARTIAL_FILLED` 买单时撤销余量，保留已成交数量；
16. 存在 `CANCEL_REQUESTED` 买单时不重复撤单、不提交新单；
17. 旧单转为 `CANCELED` 后，下一 Tick 按最新 Tick 和仓位重新计算；
18. 旧单在撤单前转为 `FILLED` 时，下一 Tick 按成交后的仓位重新计算；
19. 撤单失败且旧单仍活动时不提交新单；
20. 同标的卖单不会被 Guardian 买入换单逻辑撤销。
21. 外部/人工活动买单不会被自动撤销，并会阻止 Guardian 提交新买单。

### 11.2 Position Management

重点文件：

```text
freshquant/tests/test_position_management_submit_gate.py
```

至少覆盖：

1. 当前市值低于上限，但 projected value 超限时拒绝；
2. projected value 恰好等于上限时放行；
3. projected value 低于上限时放行；
4. 快照缺失时保持当前拒绝；
5. 卖出和非 Guardian 买入的既有行为不被意外改变。

### 11.3 配置与前端

至少覆盖：

1. 三个 CAP 可保存和回读；
2. CAP 缺失、非正数、非递增时拒绝；
3. BUY 价格非严格递减时拒绝；
4. 页面不再显示倍率和 `buy_active` 运行态；
5. 页面正确展示三个 CAP；
6. 旧记录缺少 CAP 时显示“未配置”，不显示推导值。

## 12. 验收标准

1. 三条买入 Grid 价格只负责识别当前价格阶段；
2. 三个可配置 CAP 分别控制前三个价格区间的最大仓位金额；
3. `price <= BUY-3` 由当前全局单标的仓位上限控制；
4. 每次买入仍以现有基础金额为上限，不再存在买入倍率；
5. `new_open` 和 `holding_add` 均受阶段容量约束；
6. 当前阶段开关关闭时不买入，也不改变阶段映射；
7. `buy_active` 不再参与准入；
8. 提交新买单前先撤销同标的全部活动买单；
9. 撤单尚未确认时不提交新买单；
10. 旧单退出活动状态后按最新价格、仓位和 CAP 重算，不复用旧数量；
11. Guardian 买入换单不撤销任何卖单；
12. 外部/人工活动买单不自动撤销，但会阻止新的 Guardian 买单；
13. Position Management 使用本单后的 projected market value 做最终全局门禁；
14. 成交回报和订单管理生命周期保持原逻辑；
15. 不引入额外状态机或并发基础设施。

## 13. 联合评审结论

Codex 与 Devin Ultra 最终一致意见是：

```text
Guardian：
活动买单检查 -> 必要时撤旧单并结束当前 Tick
-> 无活动买单后按价格区间识别阶段
-> 阶段 CAP -> 实时市值剩余容量 -> 基础买入量截断

Position Management：
current market value + 本单金额 -> 全局单标的上限最终门禁

Order Management：
复用现有撤单、订单状态和成交回报
```

这是满足当前产品规则的最小纵向修改。它修复倍率语义、`buy_active` 一次性消费和
单笔 projected amount 越限三个直接问题，并通过“撤单确认后再重算挂单”消除同一
标的多笔活动买单并行占用仓位的问题。
