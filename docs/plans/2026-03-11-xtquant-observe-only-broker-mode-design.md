# XTQuant Observe-Only Broker Mode Design

## 背景

当前完整交易链已经具备以下能力：

- `Guardian / API / CLI` 调用 `OrderSubmitService`
- 订单主账本写入、运行观测埋点、Redis 队列派发
- `fqxtrade.xtquant.broker` 消费队列并向券商执行 `buy / sell / cancel`
- XT 回报再进入 `xt_report_ingest / order_reconcile`

但当前只有两种运行结果：

- 真实提交到券商
- 不启动完整链路，只保留部分 XTData / broker 观察进程

缺少一种安全演练模式：

- 上游链路完整运行
- 运行观测可见 `Guardian -> Position -> OrderSubmit -> Broker`
- 最后一跳不与券商发生任何交互
- 不伪造成交，不污染真实持仓、真实仓位、真实 TPSL 事实

## 目标

- 在 `freshquant.params(code="xtquant").value` 下增加 `broker_submit_mode`
- 让宿主机能切到完整交易链模式，并保留 `observe_only` 的安全边界
- 在 `observe_only` 下，`buy / sell / cancel` 全部止步于 broker，不与券商交互
- 用显式订单状态和运行观测事件表达“已跑到 broker，但被演练模式拦截”

## 非目标

- 不生成 synthetic 成交、委托或 XT 回报
- 不引入模拟持仓、模拟仓位、模拟对账分支
- 不新增独立的 `order_management.worker`
- 不改变缺省真实下单语义；参数缺失时仍按现有真实提交流程运行

## 设计

### 1. 参数位置与缺省语义

- Mongo 文档：`freshquant.params`
- 文档 `_id`：`69ab8178dc99511db870d74e`
- 文档 `code`：`xtquant`
- 新字段位置：`value.broker_submit_mode`
- 与 `total_position` 同级

示例：

```json
{
  "_id": "69ab8178dc99511db870d74e",
  "code": "xtquant",
  "value": {
    "account": "068000076370",
    "path": "D:\\迅投极速策略交易系统交易终端 东海证券QMT实盘\\userdata_mini",
    "account_type": "CREDIT",
    "total_position": 7000000,
    "broker_submit_mode": "observe_only",
    "daily_threshold": {},
    "is_force_stop": false
  }
}
```

合法值：

- `normal`
- `observe_only`

缺省语义：

- 字段缺失、空值、非法值：按 `normal`
- `normal`：保持当前真实提交行为
- `observe_only`：broker 消费订单，但不与券商交互

### 2. 完整交易链 Supervisor 运行面

要看到完整链路，宿主机 Supervisor 需要从当前“XTData + broker + reference-data”模式切到完整交易链模式。

保留现有进程：

- `fqnext_realtime_xtdata_producer`
- `fqnext_realtime_xtdata_consumer`
- `fqnext_xtquant_broker`
- `fqnext_credit_subjects_worker`
- `fqnext_xtdata_adj_refresh_worker`

新增常驻进程：

- `python -m freshquant.signal.astock.job.monitor_stock_zh_a_min --mode event`
- `python -m freshquant.position_management.worker`
- `python -m freshquant.tpsl.tick_listener`

同时要求：

- `freshquant.params(code="monitor").value.xtdata.mode = guardian_1m`

明确不新增：

- `order_management.worker`

原因是订单管理主链仍然是被 `Guardian / API / CLI` 直接调用的领域服务，独立常驻 worker 只有已存在的 `credit_subjects.worker`。

### 3. Broker 执行边界

`observe_only` 的安全边界收口在 `fqxtrade.xtquant.broker`。

#### `normal`

- 保持当前行为不变
- 正常初始化 XTQuant / XTTrader
- 正常执行 `puppet.buy / puppet.sell / cancel_order_stock`
- 正常执行 `sync_positions / sync_orders / sync_trades / sync_summary`

#### `observe_only`

- broker 仍启动并消费订单队列
- 仍产出 `broker_gateway` 运行观测事件
- 不初始化真实券商执行路径
- 不调用 `puppet.buy`
- 不调用 `puppet.sell`
- 不调用 `xt_trader.cancel_order_stock`
- 不执行 `sync_positions / sync_orders / sync_trades / sync_summary`
- 不进入 `xt_report_ingest / order_reconcile`

为满足“完全不跟券商交互”，`broker_submit_mode` 以 broker 进程启动时解析为准。修改该参数后，需要重启 `fqnext_xtquant_broker` 才能生效。

### 4. 订单状态与事件语义

为了避免把演练单误显示成“已真实提交”，新增显式状态与事件：

- 订单状态：`BROKER_BYPASSED`
- 订单事件：`broker_submit_bypassed`
- 订单事件：`broker_cancel_bypassed`

行为：

- `buy / sell` 在 `observe_only` 下消费成功后，订单推进到 `BROKER_BYPASSED`
- `cancel` 在 `observe_only` 下不向券商发起撤单，并记录 `broker_cancel_bypassed`
- 不生成 synthetic `broker_order_id`
- 不推进到 `SUBMITTED`

### 5. 运行观测语义

`observe_only` 下仍应出现完整上游链路：

- `guardian_strategy`
- `position_gate`
- `order_submit`
- `broker_gateway`

其中 `broker_gateway` 新增关键节点：

- `execution_bypassed`

建议 payload 至少包含：

- `broker_submit_mode`
- `reason=observe_only`
- `action`
- `symbol`
- `request_id`
- `internal_order_id`

运行观测的终点应停在 `broker_gateway.execution_bypassed`，而不是继续出现这笔订单对应的：

- `xt_report_ingest`
- `order_reconcile`

### 6. 运维切换步骤

切到完整演练链路时，需要同时满足：

1. Mongo `monitor.xtdata.mode = guardian_1m`
2. Mongo `xtquant.broker_submit_mode = observe_only`
3. 宿主机 Supervisor 增加 `guardian / position_management / tpsl` 三个常驻进程
4. 重启 `fqnext_xtquant_broker`

回切到真实模式时：

1. 删除 `broker_submit_mode`，或设置为 `normal`
2. 重启 `fqnext_xtquant_broker`

### 7. 验收标准

- `broker_submit_mode` 缺失时，真实提交行为不变
- `broker_submit_mode=observe_only` 时，策略单仍能从 `Guardian` 跑到 `broker_gateway`
- 订单状态落到 `BROKER_BYPASSED`
- 运行观测出现 `broker_gateway.execution_bypassed`
- 不出现对应订单的真实券商委托、真实成交、XT 回报、对账推进
- 不改变真实持仓、真实仓位、真实 TPSL 事实
- 宿主机不需要新增独立 `order_management.worker`

## 风险

- `observe_only` 不产生 XT 回报，因此依赖真实回报的下游链路不会继续推进；这是设计预期，不是缺陷
- 若只改 Mongo 参数但未重启 broker，不能保证“完全不与券商交互”
- 新增 `BROKER_BYPASSED` 后，订单状态机、查询接口和前端文案需要同步兼容，避免把它误归类为失败或已提交
