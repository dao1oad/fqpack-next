# XT Auto Repay Worker Design

## 背景

- `xtquant` 底层已经提供信用“直接还款”委托类型：
  - `xtconstant.CREDIT_DIRECT_CASH_REPAY = 32`
  - `xtconstant.CREDIT_DIRECT_CASH_REPAY_SPECIAL = 45`
- 当前仓库只把信用买入/卖出相关模式接进了订单执行链，尚未提供“自动现金还款”能力。
- 用户侧真实目标不是高频盘中还款，而是：
  - 盘中低频巡检即可
  - 当天必须在日终做一次“总还款”
  - 以降低当日普通融资负债的计息基数

## 目标

- 新增一个独立宿主机进程 `xt_auto_repay_worker`，只负责普通融资负债的自动还款。
- `/system-settings -> XTQuant` 新增自动还款开关与留底现金阈值：
  - `xtquant.auto_repay.enabled`
  - `xtquant.auto_repay.reserve_cash`
- 盘中降低自动还款频率；固定在 `14:55` 做一次硬结算，在 `15:05` 做一次补偿重试。
- 真正提交还款前，始终再查一次实时 `credit_detail` 做二次确认。

## 非目标

- 不把自动还款塞进 `fqnext_xt_account_sync_worker` 主循环。
- 不处理专项融资负债/专项直接还款。
- 不把 `14:55 / 15:05` 放进前端配置。
- 第一版不做复杂策略，例如按负债合约逐笔优化还款或自定义多时间窗。

## 当前实现事实

### 1. XT 查询链已经具备信用明细真值

- `freshquant.xt_account_sync.worker` 默认每 `15` 秒同步一次：
  - `assets`
  - `credit_detail`
  - `positions`
  - `orders`
  - `trades`
- `credit_detail` 已落库为仓位管理快照，并保留原始 XT 字段。
- 当前系统已经在多个地方使用：
  - `m_dAvailable`
  - `m_dEnableBailBalance`
  - `m_dFinDebt`

### 2. `xt_account_sync.worker` 的职责边界不适合混入自动下单

- 文档已明确仓位管理“不负责下单，也不负责账本修复”。
- `xt_account_sync.worker` 当前承担“券商真值主动查询统一 worker”的角色；它的异常会波及仓位/订单/成交同步链。
- 当前 `XtAccountQueryClient` 只有 `query_*` 方法，没有 submit 责任。

### 3. `xtquant` 直接还款接口是“通过通用报单入口 + 特殊 order_type”

- `XtQuantTrader` 没有单独的 `cash_repay()` 高层函数。
- 直接还款通过 `order_stock(..., order_type=xtconstant.CREDIT_DIRECT_CASH_REPAY, ...)` 走通用报单口。
- 本地源码和文档确认了该 order type 存在，但没有提供完整的“直接还款”示例参数，因此提交参数需要隔离在专门的 executor 内部，便于后续按券商侧实测收敛。

## 方案选择

### 方案 A：把自动还款塞进 `xt_account_sync.worker`

优点：

- 少一个宿主机进程。

缺点：

- 查询真值 worker 变成“查询 + 自动下单”混合体，职责边界变脏。
- 自动还款异常会直接影响当前最关键的 XT 主动同步链。
- 后续 deploy / runtime verify / troubleshooting 的影响面更大。

结论：不采用。

### 方案 B：新增独立 `xt_auto_repay_worker`，平时读快照，真正还款前再实时确认

优点：

- 与 `xt_account_sync.worker` 解耦，职责清晰。
- 盘中不必高频打 XT；真正候选命中时才补一跳实时确认。
- 出问题时不会把 `xt_positions / xt_orders / xt_trades` 主同步链拖垮。

缺点：

- 需要接入一条新的宿主机进程、deploy surface 与健康检查。

结论：采用。

### 方案 C：挂到 broker / order submit 主链

优点：

- 天然具备下单能力。

缺点：

- broker / submit 主链是事件响应型，不适合做账户级低频巡检和固定时点日终结算。

结论：不采用。

## 总体设计

新增包：

- `freshquant/xt_auto_repay/`

新增宿主机入口：

- `python -m freshquant.xt_auto_repay.worker`

核心职责拆分为四层：

1. 配置层
   - 从 `system_settings.xtquant.auto_repay.*` 读取开关与留底现金阈值。
2. 读模型层
   - 读取 `xt_account_sync` 已落库的最新信用快照作为盘中候选信号。
3. 决策层
   - 判断是否需要盘中巡检还款 / `14:55` 硬结算 / `15:05` 重试。
4. 执行层
   - 真正提交前实时 `query_credit_detail()`
   - 按二次确认结果决定是否执行 `CREDIT_DIRECT_CASH_REPAY`

## 配置契约

### Mongo / `system_settings`

配置继续挂在 `params.xtquant` 下，不新增顶层 section：

```json
{
  "code": "xtquant",
  "value": {
    "path": "D:/miniqmt/userdata_mini",
    "account": "068000076370",
    "account_type": "CREDIT",
    "broker_submit_mode": "normal",
    "auto_repay": {
      "enabled": true,
      "reserve_cash": 5000
    }
  }
}
```

### 默认值

- `xtquant.auto_repay.enabled = true`
- `xtquant.auto_repay.reserve_cash = 5000`

### 前端暴露范围

仅新增这两项到 `/system-settings -> XTQuant`：

- 自动还款开关
- 留底现金

不把以下运行时参数放进前端：

- `14:55`
- `15:05`
- cooldown
- lock TTL
- 最小盘中还款额

## 运行行为

### 1. 盘中低频巡检

默认每 `30` 分钟执行一轮。

行为：

- 只读最新信用快照，不直接查 XT。
- 如果快照显示：
  - `m_dFinDebt > 0`
  - `m_dAvailable > reserve_cash`
  则进入候选。
- 候选金额：
  - `candidate_amount = min(m_dAvailable - reserve_cash, m_dFinDebt)`
- 若 `candidate_amount < 1000`，盘中默认跳过。
- 只有盘中候选命中时，才即时 `query_credit_detail()` 二次确认。

### 2. `14:55` 硬结算

固定在 `Asia/Shanghai 14:55` 触发。

行为：

- 不依赖快照，直接实时 `query_credit_detail()`。
- 目标是尽量完成当日普通融资负债总还款。
- 日终硬结算不受盘中 `min_repay_amount = 1000` 约束；只要还能还，就提交。

### 3. `15:05` 补偿重试

固定在 `Asia/Shanghai 15:05` 触发。

行为：

- 仍只处理普通融资负债。
- 直接实时 `query_credit_detail()`。
- 用于补偿 `14:55` 失败、柜台延迟、资金状态短时变化等场景。

## 决策规则

### 候选规则

进入还款候选的基础条件：

- `system_settings.xtquant.account_type == "CREDIT"`
- `system_settings.xtquant.auto_repay.enabled is True`
- `m_dFinDebt > 0`
- `m_dAvailable > reserve_cash`

候选还款金额：

```text
candidate_amount = min(m_dAvailable - reserve_cash, m_dFinDebt)
```

### 二次确认规则

每次真正提交前都实时查询一次 XT：

- 如果二次确认后 `m_dFinDebt <= 0`，跳过
- 如果二次确认后 `m_dAvailable <= reserve_cash`，跳过
- 如果二次确认后的可还金额 `<= 0`，跳过

最终提交金额：

```text
repay_amount = min(m_dAvailable - reserve_cash, m_dFinDebt)
```

### 普通 / 专项边界

第一版只认普通融资负债：

- 普通融资负债 -> `CREDIT_DIRECT_CASH_REPAY`
- 不处理专项负债 -> 不触发 `CREDIT_DIRECT_CASH_REPAY_SPECIAL`

## 运行保护机制

### 1. 分布式锁

- 按账户维度加锁，例如：
  - `xt_auto_repay:{account_id}`
- 默认 `lock_ttl_seconds = 120`

目的：

- 避免多实例重复提交
- 避免进程重启/重复启动期间并发还款

### 2. 冷却时间

- 默认 `cooldown_seconds = 1800`

适用范围：

- 仅约束盘中低频巡检

不约束：

- `14:55` 硬结算
- `15:05` 补偿重试

目的：

- 避免盘中重复触发同一类小额还款

### 3. 最小盘中还款额

- 默认 `min_repay_amount = 1000`

适用范围：

- 仅约束盘中巡检

不约束：

- `14:55`
- `15:05`

目的：

- 避免盘中碎片小额还款噪音

### 4. `observe_only` 保护

若 `xtquant.broker_submit_mode == "observe_only"`：

- 不真实下单
- 只记录“本应提交自动还款”的事件

### 5. 幂等保护

即使未命中 cooldown，也应避免重复提交：

- 同一轮已提交成功后，不应在同一条件快照下再次提交
- `14:55` 和 `15:05` 仍受锁与事件状态保护，避免重复打单

## 数据与可观测性

建议新增两张集合：

### 1. `xt_auto_repay_state`

按账户维护最近运行态：

- `account_id`
- `enabled`
- `last_checked_at`
- `last_candidate_at`
- `last_submit_at`
- `last_submit_amount`
- `last_submit_order_id`
- `last_hard_settle_at`
- `last_retry_at`
- `last_status`
- `last_reason`

### 2. `xt_auto_repay_events`

记录每次决策事件：

- `checked`
- `skip`
- `observe_only`
- `submitted`
- `failed`
- `error`

每条事件至少保留：

- `account_id`
- `event_type`
- `reason`
- `mode`
  - `intraday`
  - `hard_settle`
  - `retry`
- `snapshot_available_amount`
- `snapshot_fin_debt`
- `confirmed_available_amount`
- `confirmed_fin_debt`
- `candidate_amount`
- `submitted_amount`
- `broker_order_id`
- `created_at`

## XT 执行适配

新增一个专门的 executor/submit adapter 负责：

- 连接 XT
- 订阅信用账户
- 查询 `credit_detail`
- 提交 `CREDIT_DIRECT_CASH_REPAY`

这样把“直接还款报单参数怎么填”限制在一个地方，便于后续依据宿主机实测收敛。

注意：

- 本地源码与文档已确认“有这个 order_type”
- 但没有现成的“直接还款”完整示例
- 因此第一版实现需要保留一层隔离，避免该细节蔓延到 worker 主逻辑

## 宿主机与部署集成

需要把 `xt_auto_repay_worker` 纳入：

- `deployment/examples/supervisord.fqnext.example.conf`
- `script/fqnext_supervisor_config.py`
- `script/fqnext_host_runtime.py`
- `script/freshquant_deploy_plan.py`
- `script/check_freshquant_runtime_post_deploy.ps1`

部署 surface 归属建议：

- 归入 `order_management`

原因：

- 这是新的自动交易执行进程，不属于仓位真值同步
- 改动影响面与 broker / order-management 更接近

## 文档同步

同一 PR 需要同步更新：

- `docs/current/configuration.md`
- `docs/current/deployment.md`
- `docs/current/runtime.md`
- `docs/current/interfaces.md`
- `docs/current/storage.md`
- `docs/current/architecture.md`
- `docs/current/troubleshooting.md`

## 风险与缓解

### 1. 直接还款报单参数口径不清

风险：

- 虽然 `xtquant` 源码确认了 order type，但没有完整示例说明 `stock_code / order_volume / price_type / price` 的精确填法。

缓解：

- 通过专门 executor 收口参数拼装
- 先在 `observe_only` 模式和信用测试账户上验证
- 宿主机正式启用前，先完成一次人工验证

### 2. 与 `xt_account_sync.worker` 状态时序不一致

风险：

- 盘中快照只作为候选，可能落后于 XT 实时状态。

缓解：

- 盘中只把快照当候选
- 真实提交前必须再实时查一次 `credit_detail`

### 3. 多实例或重启导致重复还款

缓解：

- 账户级分布式锁
- cooldown
- 事件幂等保护

## 验收标准

- `/system-settings -> XTQuant` 新增：
  - 自动还款开关
  - 留底现金
- 默认配置为：
  - `enabled = true`
  - `reserve_cash = 5000`
- 宿主机新增 `fqnext_xt_auto_repay_worker`
- 盘中默认每 `30` 分钟巡检一次
- `14:55` 固定执行一次普通融资负债硬结算
- `15:05` 固定执行一次补偿重试
- `observe_only` 下绝不真实提交还款
- 不影响 `xt_account_sync.worker` 的现有同步职责
- deploy / runtime verify / docs/current 同步完成

## 前置条件

这是高影响自动交易行为变更。进入编码前，应先创建 GitHub Issue，明确：

- 影响面
- 验收标准
- 部署影响
- 启用与回滚方式
