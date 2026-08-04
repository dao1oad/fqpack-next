# Guardian 买入 Grid 与三档止盈——最终最小修改方案

> 状态：最终评审方案
> 评审日期：2026-08-04
> 依据：当前工作区代码事实、前序产品讨论、Codex 本地复核、Devin Ultra 单轮只读评审
> 本文是后续实施真值；两份分项方案仅保留分析过程，不再单独作为实施依据。

## 1. 最终目标

本次改造只处理两个直接相关的交易规则：

1. 三档止盈由“满足止盈价的 Slice 数量”改为“触发时当前仓位比例”；
2. Guardian 三档买入由“2/3/4 倍基础量”改为“价格阶段对应最大仓位金额”。

实施原则：

- 以当前代码为基础做最小修改；
- 不新增交易状态机、reservation、pending plan、补单 worker 或重复撤单链；
- 成交回报、成交事实、Entry/Slice 实际扣减和对账链保持原样；
- Guardian 只负责阶段 CAP 决策，Position Management 只负责全局单标的上限兜底；
- 报价模式与普通/信用账户的业务类型解耦；
- 每项行为都写入现有 `strategy_context` 和运行观测字段，便于排查。

## 2. 当前代码事实

### 2.1 止盈主链

```text
freshquant/tpsl/consumer.py
-> TpslService.evaluate_takeprofit()
-> choose_takeprofit_level()
-> resolve_takeprofit_sell_quantity()
-> TpslService.submit_takeprofit_batch()
-> TpslService._submit_batch()
-> OrderSubmitService.submit_order()
-> TakeprofitService.mark_level_triggered()
```

当前行为：

- `ask1 >= tier.price` 时触发；
- 同 Tick 命中多档时选择价格最高的已启用档；
- 卖出数量等于 `guardian_price < tier_price` 的 open Slice 总量；
- 提交订单后立即关闭当前档及更低档；
- 成交回报根据订单请求中的 Entry 来源执行实际账本扣减。

### 2.2 Guardian 买入主链

```text
freshquant/strategy/guardian.py
-> GuardianBuyGridService.build_holding_add_decision()
-> submit_guardian_order()
-> OrderSubmitService.submit_order()
-> PositionManagementService.evaluate_strategy_order()
-> 当前订单提交链
```

当前行为：

- `BUY-1 / BUY-2 / BUY-3` 对应 `2 / 3 / 4` 倍基础买入金额；
- `buy_active` 会让已消费价位在本轮中不再买入；
- 新开仓按 `initial_lot_amount` 计算，未执行阶段 CAP；
- Position Management 只判断当前市值是否已达到上限，没有判断本单后的预计市值；
- 系统已有单笔撤单查询、状态迁移、队列和 XTQuant 执行链，但 Guardian 下新买单前没有编排“撤旧买单”。

## 3. 三档止盈最终规则

### 3.1 档位选择

保持当前 `choose_takeprofit_level()` 不变：

```text
同 Tick 达到多个仍启用档位
-> 直接选择价格最高的档位
```

例如价格从 L1 以下直接跳到 L2 以上：

```text
选择 L2
-> 按触发时当前仓位的 1/2 卖出
-> 提交后关闭 L1、L2
```

不在同一个 Tick 内串行执行 L1 后再执行 L2。

### 3.2 比例基数

一次读取 `xt_positions` 中同一标的的：

```text
volume          = 当前券商总仓位
can_use_volume  = 当前券商可卖仓位
```

比例目标：

```text
L1 ratio_target = floor(volume × 1/3)
L2 ratio_target = floor(volume × 1/2)
L3 ratio_target = volume
```

L2 使用触发时重新读取的当前剩余总仓位，不保存 L1 的历史基数。

同时读取订单管理全部 open Entry Slice：

```text
ledger_total_quantity =
    sum(open_slice.remaining_quantity)
```

最终可提交上限：

```text
quantity_cap =
    min(ratio_target, ledger_total_quantity, can_use_volume)
```

L1、L2 继续沿用当前 100 股向下取整：

```text
submit_quantity = floor_to_board_lot(quantity_cap)
```

L3 的产品含义是“请求卖出当前全部仓位”，但本次仍沿用当前订单链的整手约束。
极端情况下若存在不足 100 股的异常余股，可能保留残余；该边界不在本次扩大共享卖出
约束的修改范围。

### 3.3 无订单时不消费档位

当前代码在没有盈利 Slice 时会生成 `triggered_no_order` 并消费档位。比例止盈改造后，
档位关闭条件统一为：

```text
OrderSubmitService.submit_order() 成功返回
```

以下情况只返回 blocked/skipped，不关闭档位：

- `volume <= 0`；
- `ledger_total_quantity <= 0`；
- `can_use_volume <= 0`；
- 截断及整手处理后 `submit_quantity <= 0`；
- 订单提交抛出异常。

这不引入 pending 状态。后续 Tick 仍按现有 armed 状态重新判断。

### 3.4 账本来源分配

仓位比例决定最终卖出数量，账本价格只决定来源优先级。

第一组：

```text
guardian_price < tier_price
```

排序：

```text
guardian_price ASC
sort_key ASC
entry_slice_id ASC
```

第二组为其他 open Slice。第一组不足时，按下列顺序补足：

```text
remaining_quantity DESC
sort_key ASC
entry_slice_id ASC
```

分配直到合计达到 `submit_quantity`。

策略继续生成订单管理现有合同：

```json
{
  "strategy_context": {
    "guardian_sell_sources": {
      "allocation_policy": "takeprofit_ratio_v1",
      "level": 1,
      "tier_price": 10.5,
      "entries": [
        {"entry_id": "ENTRY_A", "quantity": 200},
        {"entry_id": "ENTRY_B", "quantity": 100}
      ]
    }
  }
}
```

精度边界：

- 策略可以精确决定优先使用哪个 Entry 及其数量；
- 当前订单合同不能指定 `entry_slice_id`；
- 同一 Entry 下有多个 Slice 时，实际扣减顺序仍由
  `allocate_sell_to_entry_slices()` 决定；
- `slice_details` 只作为决策解释和审计数据，不成为新的成交回报协议。

### 3.5 止盈报价模式

`order_type` 与 `price_type` 是两个独立维度：

- `order_type` 决定普通交易、担保品交易、融资买入或卖券还款；
- `price_type` 决定限价或五档即时成交剩余撤销。

最终规则：

```text
TPSL 保持 price_mode = auto
STOCK 与 CREDIT 的 auto 都调用现有 resolve_price_mode()
连续竞价 -> market_5_cancel
非连续竞价 -> limit
```

不在 TPSL `_submit_batch()` 中无条件写死 `market_5_cancel`。原因是该方法同时服务
止盈和止损，而且 Tick 消费者目前只过滤 09:30 前行情，没有过滤午间及 14:57 后；
在非连续竞价阶段写死五档市价会产生无效委托，并可能在订单受理后提前消费止盈档。

该修正会让普通账户的 `auto` 语义与信用账户一致。普通/信用账户的 `order_type`
选择保持原样。

## 4. Guardian 三档买入最终规则

### 4.1 配置语义

沿用 `guardian_buy_grid_configs`，新增：

```json
{
  "code": "TARGET",
  "BUY-1": 10.0,
  "BUY-2": 9.0,
  "BUY-3": 8.0,
  "max_position_amounts": [200000, 350000, 500000],
  "buy_enabled": [true, true, true],
  "enabled": true
}
```

对应关系：

```text
max_position_amounts[0] = CAP-1
max_position_amounts[1] = CAP-2
max_position_amounts[2] = CAP-3
```

保存校验：

1. `BUY-1 > BUY-2 > BUY-3 > 0`；
2. `max_position_amounts` 恰好为三个正数；
3. `CAP-1 <= CAP-2 <= CAP-3`；
4. 保存时三个 CAP 不高于当前可读取的全局单标的上限；
5. 价格、CAP 和 `buy_enabled` 原子保存。

运行时继续使用：

```text
min(stage_cap, current_global_symbol_limit)
```

### 4.2 四个价格区间

| 当前价格 | 当前阶段 | 有效上限 | 阶段开关 |
| --- | --- | ---: | --- |
| `price > BUY-1` | BUY-1 前 | `CAP-1` | `buy_enabled[0]` |
| `BUY-2 < price <= BUY-1` | BUY-1 至 BUY-2 | `CAP-2` | `buy_enabled[1]` |
| `BUY-3 < price <= BUY-2` | BUY-2 至 BUY-3 | `CAP-3` | `buy_enabled[2]` |
| `price <= BUY-3` | BUY-3 以下 | 当前全局/标的覆盖上限 | `buy_enabled[2]` |

`price <= BUY-3` 继续由 BUY-3 开关控制，不增加第四个开关或第四个 CAP。

`buy_enabled` 只控制固定价格区间是否允许买入。关闭某档不会改变区间，也不会让价格
映射到其他 CAP。

### 4.3 CAP 是上限，不是目标仓位

读取：

```text
current_market_value =
    pm_symbol_position_snapshots.market_value
```

计算：

```text
effective_stage_cap =
    min(configured_stage_cap, current_global_symbol_limit)

remaining_amount =
    effective_stage_cap - current_market_value

base_quantity =
    floor_to_board_lot(base_amount / decision_price)

capacity_quantity =
    floor_to_board_lot(remaining_amount / decision_price)

final_quantity =
    min(base_quantity, max(capacity_quantity, 0))
```

每次仍只按基础金额买入，不按倍率放大，也不一次补满 CAP。

新开仓使用相同公式，其中 `base_amount = initial_lot_amount`。

### 4.4 无配置与旧配置迁移

为避免把所有尚未配置 Grid 的标的意外关停，最终区分三种情况：

1. 完全没有 Guardian Grid 配置：
   - 保持当前兼容行为；
   - 单次按基础金额买入；
   - 只受 Position Management 全局/标的覆盖上限约束。
2. 已存在有效 BUY 价格，但缺少 `max_position_amounts`：
   - 不从旧 `2/3/4` 倍率反推 CAP；
   - 当前 Grid 买入 fail-closed；
   - 记录 `grid_position_cap_unconfigured`。
3. 配置存在但价格、CAP 顺序或数值无效：
   - 保存接口拒绝；
   - 对历史脏记录运行时 fail-closed；
   - 记录 `grid_position_config_invalid`。

部署前应提供一次只读 inventory，列出第二、三类标的，由用户补齐配置后再启用。

### 4.5 `buy_active`

新语义允许在阶段 CAP 未满时多次按基础金额买入，因此：

- `_resolve_hit_levels()` 不再使用 `buy_active` 作为准入条件；
- `mark_buy_order_accepted()` 不再把命中档位设置为不可买；
- `buy_active`、`last_hit_*` 可暂时保留用于兼容旧读模型和审计；
- 前端删除“运行态 X/3”业务展示；
- 本次不做状态集合迁移或删除，避免扩大修改范围。

## 5. 下单前撤旧买单

### 5.1 边界

“取消该标的所有未成交订单”在 Guardian 买入场景收敛为：

```text
同一账户
+ 同一标的
+ side = buy
+ 系统内部可撤的活动订单
```

不撤：

- 该标的卖单；
- `external_reported` / `external_inferred` 外部或人工订单；
- 无法映射到系统内部订单生命周期的订单。

存在外部/人工活动买单时，Guardian 当前 Tick 跳过并记录
`external_active_buy_order`，避免覆盖人工操作或再增加并行买单。

### 5.2 复用现有撤单链

不实现第二套撤单能力，直接复用：

```text
OrderSubmitService.cancel_order()
-> OrderTrackingService.cancel_order()
-> CANCEL_REQUESTED
-> STOCK_ORDER_QUEUE
-> fqxtrade dispatch_cancel_execution()
-> xt_trader.cancel_order_stock()
-> XT order report ingest
```

Guardian 只新增活动买单查询和调用编排。

查询使用 `OrderManagementRepository.list_broker_orders()` 或等价的无分页内部查询，
不使用 `OrderManagementReadService.list_orders()` 默认 20 条分页结果。

当前正式 Guardian 运行实例只绑定一个 `xtquant.account`，而
`om_broker_orders` 当前只持久化 `account_type`，没有稳定的 `account_id`
分区字段。因此本次“同一账户”依赖现有单账户部署事实，并在该边界内按标的查询。
若未来一个运行实例承载多个券商账户，应先把 `account_id` 写入
`om_order_requests / om_orders / om_broker_orders` 并扩展 repository 查询，
再启用多账户 Guardian；不能在缺少账户分区时跨账户复用当前撤单编排。

### 5.3 活动订单分类

至少覆盖当前状态机中的：

```text
ACCEPTED
QUEUED
SUBMITTING
SUBMITTED
PARTIAL_FILLED
BROKER_BYPASSED
CANCEL_REQUESTED
INFERRED_PENDING
```

处理规则：

1. `CANCEL_REQUESTED`
   - 等待订单回报；
   - 不重复调用 `cancel_order()`；
   - 当前 Tick 不下新单。
2. `INFERRED_PENDING` 或外部来源活动买单
   - 只阻止 Guardian 新单；
   - 不自动撤单。
3. 其他系统内部可撤活动买单
   - 逐笔调用现有 `cancel_order()`；
   - 当前 Tick 只撤单，不下新单。
4. `BROKER_BYPASSED`
   - 先按当前订单是否具有可撤 broker 标识分类；
   - 不具备 broker 标识时只阻止新单并记录原因，避免发送无效撤单。
5. 缺少 `internal_order_id` 的活动买单
   - 归类为 `unmapped` 等待项；
   - 只阻止 Guardian 新单，不发送无法映射到内部生命周期的撤单；
   - 运行结果同时计入 `waiting` 与 `unmapped`，避免被误判为可继续。

### 5.4 与 15 分钟冷却的顺序

最终顺序：

```text
Guardian 买入信号
-> 原有信号、价格、结构检查
-> 原有 15 分钟 buy cooldown 检查
-> 查询同标的活动买单

存在活动买单
-> 撤销系统内部可撤买单
-> 或等待 CANCEL_REQUESTED / 阻止外部单
-> 当前 Tick 结束

不存在活动买单
-> 重新读取最新 Tick 对应价格阶段
-> 重新读取 current_market_value 和全局/标的上限
-> 重新计算 CAP 与基础买入量
-> Position Management 最终门禁
-> 提交一笔新买单
-> 设置现有 15 分钟 cooldown
```

撤单不会清除现有 cooldown。若旧单在 cooldown 结束后仍活动，后续 Tick 仍继续等待或
撤单；若撤单已完成，则使用最新事实重新挂单。

本方案不承诺“撤单后立即在同 Tick 换单”，以避免旧单和新单同时成交。

## 6. Position Management 最终门禁

只修改全局单标的上限判断：

```text
projected_market_value =
    current_market_value + payload.price * payload.quantity
```

规则：

```text
current_market_value is None
-> 拒绝

projected_market_value > effective_limit
-> 拒绝

projected_market_value <= effective_limit
-> 放行
```

Position Management 不识别 CAP-1/2/3。

已接受边界：

- projected value 使用订单 payload 中的决策价格；
- 普通账户 `auto` 在执行桥中可能转换为五档市价并使用现有价格参数调整；
- 仓位快照存在同步时延；
- 本方案通过“同标的活动买单先退出，再重算”降低重复占用，不新增委托金额 reservation
  或分布式仓位锁。

## 7. 最小代码范围

### 7.1 止盈

生产代码：

```text
freshquant/tpsl/takeprofit_quantity.py
freshquant/tpsl/service.py
freshquant/order_management/sell_constraints.py
freshquant/order_management/submit/execution_bridge.py
```

修改内容：

- `PositionVolumeReader` 一次返回 `volume` 与 `can_use_volume`；
- 按 L1/L2/L3 计算比例目标；
- 受账本总量和可卖量截断；
- 按“达价优先、最大 Slice 补足”生成 Entry 来源；
- `_submit_batch()` 写入现有 `guardian_sell_sources.entries`；
- 只有订单提交成功才关闭档位；
- STOCK 与 CREDIT 的 `auto` 统一复用现有报价解析。

保持不变：

```text
freshquant/order_management/ingest/xt_reports.py
freshquant/order_management/guardian/allocation_policy.py
freshquant/order_management/reconcile/**
```

### 7.2 Guardian 买入

核心：

```text
freshquant/strategy/guardian_buy_grid.py
freshquant/strategy/guardian.py
freshquant/position_management/service.py
```

配置与读写：

```text
freshquant/rear/stock/routes.py
freshquant/rear/subject_management/routes.py
freshquant/subject_management/write_service.py
freshquant/subject_management/dashboard_service.py
```

前端按实际调用检索修改：

```text
morningglory/fqwebui/src/views/KlineSlim.vue
morningglory/fqwebui/src/views/subjectManagement.mjs
morningglory/fqwebui/src/views/js/kline-slim-price-panel.mjs
morningglory/fqwebui/src/views/js/subject-price-guides.mjs
```

修改内容：

- 删除倍率参与数量计算；
- 增加三档 CAP 配置、校验、读取和展示；
- 四区间决策；
- `buy_active` 退出准入；
- 新开仓和持仓加仓统一执行容量计算；
- 复用现有撤单链编排撤旧买单；
- PM 检查本单后的 projected market value；
- 前端删除倍率及“运行态 X/3”展示。

## 8. 实施顺序

为降低联动风险，按以下纵向切片实施：

1. **止盈纯函数与账本来源**
   - 比例、截断、整手、来源排序；
   - 不接真实提交。
2. **止盈服务接线与报价**
   - 写入现有 Entry 来源；
   - 提交成功后关闭档位；
   - STOCK/CREDIT auto 报价一致。
3. **买入配置合同**
   - CAP 后端校验、API、读模型和前端编辑；
   - 先不启用新决策。
4. **买入纯决策**
   - 四区间、CAP、无配置兼容、脏配置 fail-closed；
   - 新开仓与加仓统一。
5. **撤旧买单与 PM 门禁**
   - 复用撤单链；
   - projected market value；
   - 端到端接线。
6. **部署前 inventory 与配置补齐**
   - 列出旧 Grid 配置缺 CAP 的标的；
   - 补齐后启用。

## 9. 测试与验收

### 9.1 止盈

1. 900 股触发 L1，目标 300 股；
2. 当前剩余 600 股触发 L2，目标 300 股；
3. 当前剩余 300 股触发 L3，目标 300 股；
4. 比例目标高于账本总量时按账本截断；
5. 账本总量高于 `can_use_volume` 时按可卖量截断；
6. L1/L2 按 100 股向下取整；
7. 达价 Slice 足够时只选择达价来源；
8. 达价 Slice 不足时优先从最大剩余 Slice 补足；
9. Entry 来源合计等于提交数量；
10. 同 Entry 多 Slice 的实际扣减继续走原分配顺序；
11. 没有可提交数量时不关闭档位；
12. 提交成功后 L1/L2/L3 分别关闭对应及更低档；
13. 同 Tick 跨档继续直选最高档；
14. CREDIT/STOCK 的 `auto` 在连续竞价解析为五档市价，其他时段回退限价；
15. stoploss、成交回报和对账测试保持通过。

### 9.2 Guardian 买入

1. 四个价格区间边界全部覆盖；
2. `price > BUY-1` 受 CAP-1 控制；
3. `price <= BUY-3` 受全局/标的覆盖上限和 BUY-3 开关控制；
4. 单次买入不超过基础金额；
5. 单次买入不超过阶段剩余容量；
6. 不一次补满 CAP；
7. 新开仓执行相同 CAP 计算；
8. 完全无 Grid 配置时保持基础量兼容行为；
9. 有 BUY 价格但缺 CAP 时 fail-closed；
10. 非法价格或 CAP 顺序被保存接口拒绝；
11. `buy_active=false` 不再阻止阶段内继续按基础量买入；
12. PM 按 projected market value 拒绝越界订单；
13. 系统内部活动买单先调用原撤单链；
14. `CANCEL_REQUESTED` 不重复撤单；
15. 外部/人工活动买单只阻止 Guardian 新单；
16. 当前 Tick 发起撤单后不提交新单；
17. 旧单终结后按最新 Tick、仓位和 CAP 重算；
18. 卖单不受 Guardian 撤旧买单逻辑影响；
19. 原有 cooldown、订单回报、成交入账和运行观测测试保持通过。

## 10. Codex 与 Devin 最终一致意见

双方一致认为，该需求不需要新的交易状态机。

最终最小方案是：

```text
止盈：
现有档位触发
-> 读取当前总仓位、可卖量和 open Slice
-> 按触发档位计算仓位比例
-> 达价 Slice 优先，最大 Slice 补足
-> 写入现有 Entry 来源
-> auto 报价提交
-> 提交成功后立即关闭对应档位
-> 成交回报按原链扣减账本

买入：
现有 Guardian 买入信号
-> 原有 cooldown
-> 复用原撤单链处理同标的活动买单
-> 活动单退出后读取最新仓位
-> 按四个价格区间选择 CAP
-> 单次基础量与剩余容量取小
-> PM 检查本单后的全局仓位上限
-> 提交一笔新买单
```

双方共同否定：

- 止盈 pending/reservation/成交驱动档位状态；
- 同 Tick 串行执行多个止盈档；
- 新增逐 Slice 成交协议；
- 买入倍率；
- CAP 目标仓位一次补满；
- 重复实现撤单接口、队列或 XTQuant 适配；
- 撤单后同 Tick 立即换单；
- 将 Guardian 阶段 CAP 下沉到通用 Position Management；
- 为本次改造引入新的后台 worker、分布式锁或通用交易编排框架。
