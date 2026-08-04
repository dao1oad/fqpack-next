# 三档止盈按仓位比例执行——最小修改方案

> 本文为分项分析稿。2026-08-04 联合评审后的实施真值见
> `GUARDIAN_GRID_AND_TAKEPROFIT_FINAL_MINIMAL_CHANGE_PLAN.md`。

## 1. 目标

在保留当前 TPSL 触发、下单和档位状态逻辑的基础上，只修改以下三件事：

1. 到达止盈价后，按当前总仓位比例计算卖出数量；
2. 将最终卖出数量匹配到现有订单管理支持的账本 Entry 来源；
3. 订单提交后，沿用当前逻辑关闭对应止盈档位。

本方案按以下业务前提设计：

- 止盈卖出按市场价执行；
- 不处理卖出失败、撤单、部分成交和重试；
- 不存在 pending；
- 订单提交后，本档即视为已经执行；
- 本档关闭后不会重复触发；
- 成交回报、成交事实入账和账本实际扣减完全沿用现有订单管理逻辑。

## 2. 明确不引入的设计

本次不新增：

- 止盈计划集合；
- `OPEN / WORKING / PARTIAL / COMPLETED` 等状态机；
- reservation 或预留仓位；
- pending sell；
- 成交回报驱动的档位完成状态；
- 新的成交回报字段或账本扣减协议；
- 失败重试和补单；
- 多订单串行编排；
- 新的后台任务或 worker。

原因是上述机制不属于当前已确认的业务模型，会扩大修改面并增加状态不一致风险。

## 3. 当前代码主链

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

当前已经具备：

1. 使用 `ask1 >= tier.price` 判断是否到达止盈线；
2. 只选择仍处于 armed 状态的档位；
3. 生成并提交卖单；
4. 提交后调用 `mark_level_triggered()`；
5. 将当前档位及更低档位设置为不触发。

因此档位状态不需要新模型。

## 4. 最终业务规则

### 4.1 止盈数量

每次触发时读取当前总仓位：

```text
total_position_quantity = xt_positions.volume
```

同时读取订单管理账本中的 open Slice 总量：

```text
ledger_total_quantity =
    sum(open_slice.remaining_quantity)
```

按触发时的当前总仓位计算比例目标：

```text
L1 ratio_target = total_position_quantity × 1/3
L2 ratio_target = total_position_quantity × 1/2
L3 ratio_target = total_position_quantity
```

其中 L2 的“剩余仓位一半”通过“触发时重新读取当前总仓位，再取一半”自然实现，
不保存首次触发时的基数。

券商仓位可能因历史数据、人工交易或同步时点大于订单管理账本数量，因此比例目标
必须先受 open Slice 总量截断：

```text
requested_quantity =
    min(ratio_target, ledger_total_quantity)
```

否则成交回报按指定 Entry 入账时可能出现：

```text
sell quantity exceeds open entry slices
```

最终提交数量继续复用现有可卖和整手约束：

```text
submit_quantity =
    floor_to_board_lot(
        min(requested_quantity, can_use_volume)
    )
```

也就是：

- `volume` 决定仓位比例基数；
- `ledger_total_quantity` 保证策略指定的账本来源足以覆盖卖量；
- `can_use_volume` 决定本次最多可提交多少；
- 继续沿用当前 100 股取整规则；
- 不增加仓位预留或 pending 扣减。

### 4.2 账本来源设置

卖出数量以仓位比例计算结果为第一优先级。

止盈策略在提交前仍可根据 Slice 判断本次希望优先使用哪些账本，但提交给订单管理
的合同保持现状：

```text
strategy_context.guardian_sell_sources.entries
```

不新增 `entry_slice_ids`，不修改成交回报入账逻辑。

策略侧候选 Slice 分成两组：

#### 第一组：已达到本档止盈条件的 Slice

判断条件沿用当前代码：

```text
guardian_price < tier_price
```

优先使用这些 Slice 所属 Entry 的可用数量。

排序沿用当前有利于止盈解释的顺序：

```text
guardian_price ASC
sort_key ASC
entry_slice_id ASC
```

#### 第二组：尚未达到本档止盈条件的 Slice

如果第一组数量不足以满足 `submit_quantity`，继续从其他 open Slice 中选择补足来源。

补足顺序：

```text
remaining_quantity DESC
sort_key ASC
entry_slice_id ASC
```

即策略侧优先选择当前剩余数量最大的账本 Slice，并把选择结果汇总成
`entry_id + quantity`。

实际成交后的 Slice 扣减顺序继续由现有
`allocate_sell_to_entry_slices()` 决定。本次只保证 Entry 级来源数量，不改变同一
Entry 内部的 Slice 扣减顺序。

这是“保持成交回报和订单管理逻辑原样”带来的明确边界：

- 可以精确指定优先使用哪个 Entry、每个 Entry 使用多少；
- 同一个 Entry 下存在多个 Slice 时，不新增逐 Slice 指定能力；
- 若以后必须精确指定到 `entry_slice_id`，那将是订单管理协议的独立增强，不纳入
  本次止盈比例改造。

### 4.3 分配示例

当前总仓位：

```text
900 股
```

L1 触发：

```text
比例目标 = 900 × 1/3 = 300 股
```

达到 L1 止盈条件的 Slice 合计只有 200 股：

```text
先选择达到止盈条件的 Slice 所属 Entry，共 200 股
再从最大剩余 Slice 所属 Entry 补 100 股
最终生成现有 entries 来源列表
最终卖出 300 股
```

卖出后当前仓位变为 600 股。

L2 后续触发：

```text
比例目标 = 600 × 1/2 = 300 股
```

再次按同样的账本优先级分配 300 股。

L3 后续触发：

```text
比例目标 = 当前全部仓位
```

## 5. Tick 跳级规则

为了保持当前代码的最小修改，本次不改变
`choose_takeprofit_level()` 的选择规则。

当前规则是：

```text
同一个 Tick 同时达到多个仍启用的止盈档位
-> 直接选择价格最高的档位
```

例如当前仓位 900 股，价格从 L1 以下直接跳到 L2 以上：

```text
选择 L2
按当前 900 股的 1/2 卖出 450 股
提交后关闭 L1 和 L2
```

不会在同一个 Tick 中先卖 L1 的 1/3，再卖 L2 的剩余一半。

这是本次“最小修改、不增加订单串行状态”的明确取舍。若以后要求跳级时累计执行
L1、L2，则属于另一项产品规则，需要重新定义同 Tick 多单和仓位刷新时点。

## 6. 最小代码修改

### 6.1 `freshquant/tpsl/takeprofit_quantity.py`

调整 `resolve_takeprofit_sell_quantity()`：

当前职责：

```text
卖出数量 = 达到止盈条件的 Slice 数量合计
```

修改后职责：

```text
1. 根据 level 和 total_position_quantity 计算比例目标；
2. 使用 open Slice 总量截断比例目标；
3. 根据 tier_price 对全部 open Slice 排序；
4. 按最终提交数量计算 Entry 级来源；
5. 输出订单管理现有合同所需的 `entry_quantities`。
```

建议返回：

```python
{
    "requested_quantity": 300,
    "entry_quantities": {
        "ENTRY_A": 200,
        "ENTRY_B": 100,
    },
    "slice_details": [
        {
            "entry_slice_id": "ENTRY_SLICE_A",
            "entry_id": "ENTRY_A",
            "allocated_quantity": 200,
            "guardian_price": 10.0,
        },
        {
            "entry_slice_id": "ENTRY_SLICE_B",
            "entry_id": "ENTRY_B",
            "allocated_quantity": 100,
            "guardian_price": 11.0,
        },
    ],
}
```

`slice_details` 只用于解释策略如何生成 Entry 来源和触发事件记录，不作为成交回报
扣账的新协议。

不新增类或持久化对象。

### 6.2 `freshquant/order_management/sell_constraints.py`

最小扩展 `PositionVolumeReader`，一次读取：

```python
{
    "volume": total_position_quantity,
    "can_use_volume": sellable_quantity,
}
```

继续复用现有：

```python
resolve_sell_submission_quantity()
```

不改变其他卖出策略的数量约束。

### 6.3 `freshquant/tpsl/service.py`

`evaluate_takeprofit()` 只做以下调整：

1. 读取 `volume` 和 `can_use_volume`；
2. 读取全部 open Slice 并计算 `ledger_total_quantity`；
3. 按 Level 计算比例目标并受账本总量截断；
4. 先得到最终 `order_quantity`；
5. 再按最终数量生成 Entry 来源；
6. 将 Entry 来源写入 batch。

`_submit_batch()` 只增加 `strategy_context`：

```python
{
    "strategy_context": {
        "guardian_sell_sources": {
            "allocation_policy": "takeprofit_ratio_v1",
            "level": batch["level"],
            "tier_price": batch["tier_price"],
            "entries": [
                {
                    "entry_id": entry_id,
                    "quantity": quantity,
                }
                for entry_id, quantity
                in batch["entry_quantities"].items()
            ],
        }
    }
}
```

订单提交后继续使用当前代码：

```python
mark_takeprofit_triggered()
```

不移动到成交回调。

### 6.4 成交回报和账本扣减

以下文件保持原样：

```text
freshquant/order_management/ingest/xt_reports.py
freshquant/order_management/guardian/allocation_policy.py
```

现有成交回报链继续：

```text
XT 成交回报
-> 读取 strategy_context.guardian_sell_sources.entries
-> allocate_sell_to_entry_slices()
-> 更新 Entry / Slice
-> 写入 om_exit_allocations
```

止盈策略只负责提供现有链路已经支持的 `entries`，不修改成交回报处理、成交事实、
幂等、对账或账本落库逻辑。

## 7. 止盈档位状态

档位状态完全沿用当前实现：

```text
订单提交成功
-> mark_takeprofit_triggered(level)
-> 当前 Level 及更低 Level 的 armed_levels = False
```

对应关系：

| 触发档位 | 提交后状态 |
| --- | --- |
| L1 | L1 关闭 |
| L2 | L1、L2 关闭 |
| L3 | L1、L2、L3 全部关闭 |

新买入价格低于最低止盈线时，继续沿用当前
`on_new_buy_trade()` 重新启用三档的逻辑。

## 8. 报价模式深入分析

### 8.1 两个容易混淆但彼此独立的概念

XTQuant `order_stock()` 同时接收：

```text
order_type
price_type
```

它们的职责不同。

#### `order_type`：交易业务类型

普通账户：

```text
STOCK_BUY
STOCK_SELL
```

信用账户：

```text
CREDIT_BUY
CREDIT_FIN_BUY
CREDIT_SELL
CREDIT_SELL_SECU_REPAY
```

它决定的是普通交易、担保品交易、融资买入还是卖券还款。

#### `price_type`：报价方式

当前项目使用：

```text
FIX_PRICE = 11
MARKET_SH_CONVERT_5_CANCEL = 42
MARKET_SZ_CONVERT_5_CANCEL = 47
```

它决定的是限价还是最优五档即时成交剩余撤销。

所以从接口模型看：

```text
账户/信用交易模式 != 报价模式
```

信用账户和普通账户都需要分别决定 `order_type` 和 `price_type`。

### 8.2 当前 TPSL 请求

当前 TPSL `_submit_batch()` 没有显式传入 `price_mode`，因此请求默认是：

```text
price_mode = auto
```

### 8.3 当前执行桥的实际矩阵

当订单没有预先指定 `broker_price_type` 时：

| 账户类型 | 请求模式 | 连续竞价 | 当前解析结果 |
| --- | --- | --- | --- |
| `CREDIT` | `auto` | 是 | `market_5_cancel` |
| `CREDIT` | `auto` | 否 | `limit` |
| `CREDIT` | `market_5_cancel` | 不要求探测 | `market_5_cancel` |
| `CREDIT` | `limit` | 不要求探测 | `limit` |
| `STOCK` | `auto` | 任意 | `limit` |
| `STOCK` | `market_5_cancel` | 任意 | 仍被解析为 `limit` |
| `STOCK` | `limit` | 任意 | `limit` |

原因在 `_resolve_runtime_execution()`：

```python
if account_type == "CREDIT":
    price_resolution = resolve_price_mode(...)
else:
    price_resolution = _limit_price_resolution(...)
```

普通账户分支没有调用通用的 `resolve_price_mode()`。

### 8.4 为什么会形成 CREDIT 与 STOCK 的差异

从 Git 历史看，这段逻辑在 2026 年 3 月 8 日提交
`c6a9fca0 feat: add runtime sell repay and auto quote resolution` 中引入。

当时对应的是“信用账户订单支持”任务，目标同时包括：

1. 信用卖出时选择 `CREDIT_SELL` 或 `CREDIT_SELL_SECU_REPAY`；
2. 信用账户在连续竞价时自动选择五档市价；
3. 让 broker/puppet 消费解析后的 `broker_order_type` 和
   `broker_price_type`。

普通账户在该改造之前一直默认使用 `FIX_PRICE`。为了保持旧行为，提交只把新的自动
报价解析接到了 `CREDIT` 分支，`STOCK` 分支继续固定限价。

因此当前差异属于：

```text
历史改造范围 + 普通账户旧行为兼容
```

而不是：

```text
XTQuant 要求信用账户使用市价、普通账户只能使用限价
```

项目当前也没有测试证明普通账户不能使用五档市价；相反，现有
`resolve_price_mode()` 本身只依赖市场、买卖方向、请求模式和连续竞价状态，并不
依赖账户类型。

### 8.5 对本次止盈的结论

2026 年 8 月 4 日在当前工作区使用正式设置加载器读取到：

```text
xtquant.account_type = CREDIT
```

因此当前机器上的 TPSL 默认 `auto` 在连续竞价时已经使用五档市价。

当前连续竞价判断窗口是：

```text
09:30-11:30
13:00-14:57
```

集合竞价、午间和收盘集合竞价阶段会回退为限价。

另外，当前 `_market_5_cancel_resolution()` 会同时设置：

```text
卖出 price_to_use = 输入价格 × 0.992
```

真正决定五档市价语义的是 `broker_price_type=42/47`；`0.992` 是项目在引入自动
报价时同时加入的价格参数调整。现有提交记录和测试没有说明该系数是信用账户专属
要求，它对买卖方向生效，与 `CREDIT/STOCK` 无关。

最终产品规则是：

```text
止盈单无论 CREDIT 还是 STOCK，都使用五档市价
```

最小且更一致的修正是：

1. TPSL 提交时显式设置：
   ```python
   "price_mode": "market_5_cancel"
   ```
2. `execution_bridge.py` 对 `STOCK` 也调用现有
   `resolve_price_mode()`，使显式 `market_5_cancel` 得到尊重；
3. `order_type` 的普通/信用分支保持不变；
4. 不修改 broker、puppet、成交回报和账本逻辑。

这只是解除“报价模式被账户类型错误耦合”的小修改，不需要增加新的报价状态机。

## 9. 最小测试范围

### 9.1 数量测试

1. 900 股触发 L1，目标为 300 股；
2. 600 股触发 L2，目标为 300 股；
3. 300 股触发 L3，目标为 300 股；
4. 券商比例目标高于 open Slice 总量时先按账本总量截断；
5. 账本截断后的数量高于 `can_use_volume` 时再按可卖数量截断；
6. 最终数量继续按现有 100 股规则取整。

### 9.2 账本分配测试

1. 达到止盈条件的 Slice 足够时，只扣这些 Slice；
2. 数量不足时，从其他 Slice 补足；
3. 补足优先扣 `remaining_quantity` 最大的 Slice；
4. 生成的 `entries` 数量合计等于最终提交数量；
5. 成交回报继续使用原有 Entry/Slice 分配逻辑。

### 9.3 档位状态测试

1. L1 提交后关闭 L1；
2. L2 提交后关闭 L1、L2；
3. L3 提交后关闭全部档位；
4. 已关闭档位不会再次生成卖单；
5. 同 Tick 命中多档时继续选择最高档。

### 9.4 报价模式测试

1. TPSL 请求显式携带 `price_mode=market_5_cancel`；
2. `CREDIT` 连续竞价仍解析为五档市价；
3. `STOCK + market_5_cancel` 解析为五档市价；
4. `STOCK + auto` 继续解析为限价；
5. 普通/信用账户的 `order_type` 选择保持原逻辑。

## 10. 文件范围

生产代码预计只涉及：

```text
freshquant/tpsl/takeprofit_quantity.py
freshquant/tpsl/service.py
freshquant/order_management/sell_constraints.py
freshquant/order_management/submit/execution_bridge.py
```

TPSL 显式请求 `market_5_cancel`；`execution_bridge.py` 只让 `STOCK` 账户在显式
请求该模式时调用现有 `resolve_price_mode()`。`STOCK + auto` 继续保持当前限价
行为，避免扩大其他普通账户订单的行为变化。

成交回报和账本分配文件不在修改范围：

```text
freshquant/order_management/ingest/xt_reports.py
freshquant/order_management/guardian/allocation_policy.py
```

测试文件按现有目录补充，不新增基础设施。

## 11. 验收标准

1. L1、L2、L3 的比例目标由触发时当前总仓位决定；
2. 最终请求数量不超过 open Slice 总量；
3. 策略生成现有订单管理合同支持的 Entry 来源；
4. 达到止盈条件的 Slice 所属 Entry 优先；
5. 数量不足时选择最大剩余 Slice 所属 Entry 补足；
6. Entry 来源数量合计等于最终提交数量；
7. 提交后对应止盈档位立即关闭；
8. 已关闭档位不重复触发；
9. TPSL 明确使用五档市价，普通账户的显式模式得到尊重；
10. 不新增 plan、reservation、pending 或成交状态机；
11. 成交回报、账本实际扣减和其他卖出策略保持原逻辑。

## 12. 结论

本需求不需要“最小状态机”。

最合适的实现是：

```text
现有价格触发
-> 按当前总仓位计算比例
-> 按最终卖出数量生成现有 Entry 来源
-> 提交订单
-> 立即关闭对应止盈档位
-> 成交回报与账本扣减继续走订单管理原链路
```

核心变化只有“数量基准”和“策略提供的 Entry 来源”，其余继续复用当前代码。
