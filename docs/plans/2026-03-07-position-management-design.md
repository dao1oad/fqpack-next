# 仓位管理模块设计稿

**目标**：新增独立的仓位管理模块，基于融资账户“可用保证金”对策略订单进行三态风控。模块独立维护信用资产查询、Mongo 落库、状态计算与策略准入判断；人工单不受控；Guardian 的“强制减仓盈利标的”本轮只预留扩展点，不细化卖出算法。

## 1. 调研结论

### 1.1 项目与迁移现状

- 当前仓库是目标架构，新增独立模块必须先完成设计与 RFC，再进入实现。
- 旧仓库已有“仓位管理”语义，但主要是买单前总仓位风控，入口位于：
  - `D:\fqpack\freshquant\freshquant\strategy\toolkit\position_manager.py`
  - `D:\fqpack\freshquant\freshquant\strategy\toolkit\position_risk_guard.py`
  - `D:\fqpack\freshquant\freshquant\strategy\toolkit\order_manager.py`
- 当前目标仓库已完成订单管理独立分库与统一受理层，但尚未迁入独立的仓位管理模块；`freshquant/order_management/submit/service.py` 当前不会对策略订单执行仓位状态判定。

### 1.2 XtQuant 资产字段语义确认

- `XtAsset.cash` 在 SDK 源码与文档中定义为“可用金额”，不是“可用保证金”。
- 融资账户真正需要的字段位于 `query_credit_detail(account)` 返回的信用资产明细中：
  - `m_dEnableBailBalance`：可用保证金
  - `m_dAvailable`：可用金额
  - `m_dFetchBalance`：可取金额
  - `m_dTotalDebt`：总负债
- 当前项目写入 `xt_assets` 的字段只有：
  - `cash`
  - `frozen_cash`
  - `market_value`
  - `total_asset`
  - `position_pct`
- 结论：本模块不能使用 `xt_assets.cash` 作为状态判定口径，必须以 `query_credit_detail(account)` 的 `m_dEnableBailBalance` 为准。

### 1.3 当前账号类型能力

- 当前项目支持通过配置 `xtquant.account_type=CREDIT` 创建信用账户连接。
- 因此本模块可以合法地使用独立 xtquant 查询连接访问 `query_credit_detail(account)`。

## 2. 方案选择

本次在三种方案中选择 **方案 C**：

- A：仅给 Guardian 加门禁
- B：在策略单提交边界统一拦截
- C：做成独立模块，持续查询并产出“当前仓位状态”，策略只消费状态

选择 C 的原因：

- 后续需要接入多个策略，不应把仓位逻辑绑死在 Guardian 或某一个提交入口上。
- 需要把“信用资产查询、状态计算、状态持久化、策略判定”做成独立能力，而不是 broker 的附属逻辑。
- broker 负责实时下单，仓位模块不能和 broker 共用查询职责。

## 3. 模块边界与数据流

### 3.1 模块职责

建议新增独立目录：`freshquant/position_management/`

模块只负责 4 件事：

- 通过独立 xtquant 查询连接读取 `query_credit_detail(account)`
- 提取 `m_dEnableBailBalance` 并落库为信用资产快照
- 根据 Mongo 配置计算三态仓位状态
- 对策略订单给出准入决策与审计记录

### 3.2 明确不负责

- 不接管人工单执行
- 不替代订单管理主账本
- 不修改 broker 下单线程模型
- 不在本轮实现 Guardian 的强制卖出数量算法

### 3.3 数据流

1. `position_management worker` 独立运行
2. 按固定周期调用 `query_credit_detail(account)`
3. 查询成功：
   - 提取 `m_dEnableBailBalance`
   - 追加写入信用资产快照
   - 计算当前三态
   - 覆盖更新 `pm_current_state`
4. 查询失败：
   - 保留数据库中上一次成功状态
   - 记录失败信息
5. 策略准备下单时：
   - 仅读取 `pm_current_state`
   - 根据当前状态判定是否允许提交
   - 写入一条策略决策审计记录

### 3.4 与现有系统的关系

- 只有 `source=strategy` 的订单会经过本模块
- `/api/order/*`、`/api/stock_order`、CLI 手工单默认跳过
- Guardian 本轮只消费“状态决策结果”，不接管其内部卖出算法

## 4. 独立分库与 Mongo 数据模型

### 4.1 分库

- 独立数据库：`freshquant_position_management`
- 原则：参照订单管理模块，不向 `freshquant` 主业务库写入本模块集合

### 4.2 集合 1：`pm_configs`

用途：热更新配置，通常只有 1 条 active 配置

```json
{
  "code": "default",
  "enabled": true,
  "thresholds": {
    "allow_open_min_bail": 800000,
    "holding_only_min_bail": 100000
  },
  "refresh": {
    "interval_seconds": 3,
    "query_timeout_seconds": 2,
    "state_stale_after_seconds": 15
  },
  "fallback": {
    "default_state": "HOLDING_ONLY"
  },
  "updated_at": "2026-03-07T12:00:00+08:00",
  "updated_by": "manual"
}
```

说明：

- 账号信息不在本集合重复存储，直接复用 `xtquant.account` 与 `xtquant.account_type`
- `default_state` 明确固定为第二层级 `HOLDING_ONLY`

### 4.3 集合 2：`pm_credit_asset_snapshots`

用途：保存每次成功查询得到的信用资产快照

```json
{
  "snapshot_id": "pms_...",
  "account_id": "068000076370",
  "account_type": "CREDIT",
  "queried_at": "2026-03-07T12:00:03+08:00",
  "query_latency_ms": 128,
  "available_bail_balance": 865432.12,
  "available_amount": 102345.67,
  "fetch_balance": 92345.67,
  "total_asset": 1432100.00,
  "market_value": 1210000.00,
  "total_debt": 530000.00,
  "assure_asset": 902100.00,
  "per_assure_scale_value": 235.6,
  "raw": {
    "m_dEnableBailBalance": 865432.12
  },
  "source": "xtquant"
}
```

说明：

- 该集合是事实表，采用追加写
- 核心字段是 `available_bail_balance`
- 保留必要的信用字段，便于排障和后续策略扩展

### 4.4 集合 3：`pm_current_state`

用途：唯一状态源，策略只读这张表

```json
{
  "account_id": "068000076370",
  "state": "ALLOW_OPEN",
  "available_bail_balance": 865432.12,
  "snapshot_id": "pms_...",
  "data_source": "xtquant",
  "evaluated_at": "2026-03-07T12:00:03+08:00",
  "last_query_ok": true,
  "rules": {
    "allow_open_new_position": true,
    "allow_buy_existing_position": true,
    "allow_sell_existing_position": true,
    "force_profit_reduce": false
  },
  "reason_code": "bail_gt_allow_open_threshold",
  "reason_text": "可用保证金高于 800000，允许开新仓"
}
```

说明：

- 这张表只保留当前有效状态
- 只有 worker 更新它
- 策略模块只消费它

### 4.5 集合 4：`pm_strategy_decisions`

用途：记录每次策略订单经过仓位管理后的判定结果

```json
{
  "decision_id": "pmd_...",
  "strategy_name": "Guardian",
  "action": "buy",
  "symbol": "000001",
  "is_holding_symbol": false,
  "state": "HOLDING_ONLY",
  "allowed": false,
  "reason_code": "new_position_blocked",
  "reason_text": "当前处于老股震荡状态，不允许开新仓",
  "snapshot_id": "pms_...",
  "evaluated_at": "2026-03-07T12:00:04+08:00"
}
```

### 4.6 索引建议

- `pm_configs.code` 唯一
- `pm_credit_asset_snapshots(account_id, queried_at desc)`
- `pm_current_state.account_id` 唯一
- `pm_strategy_decisions(evaluated_at desc)`
- `pm_strategy_decisions(strategy_name, evaluated_at desc)`

## 5. 三态语义与策略下单规则

### 5.1 状态 1：`ALLOW_OPEN`

- 条件：`available_bail_balance > allow_open_min_bail`
- 当前阈值：`> 800000`

行为：

- 允许策略开新仓
- 允许策略买入已有持仓标的
- 允许策略卖出已有持仓标的

### 5.2 状态 2：`HOLDING_ONLY`

- 条件：`holding_only_min_bail < available_bail_balance <= allow_open_min_bail`
- 当前阈值：`100000 < bail <= 800000`

行为：

- 禁止策略开新仓
- 允许策略买入已有持仓标的
- 允许策略卖出已有持仓标的
- 对非持仓标的买单一律拒绝

持仓判定口径：

- 直接复用当前项目已有持仓读模型
- 即 `freshquant.data.astock.holding.get_stock_holding_codes()` 与 `get_stock_positions()`

### 5.3 状态 3：`FORCE_PROFIT_REDUCE`

- 条件：`available_bail_balance <= holding_only_min_bail`
- 当前阈值：`<= 100000`

行为：

- 禁止策略开新仓
- 禁止策略买入已有持仓标的
- 允许策略卖出已有持仓标的
- 当策略产生卖点且标的处于实际盈利状态时，进入“强制减仓盈利标的”分支

本轮只占位，不细化数量算法：

- 返回 `force_profit_reduce = true`
- 返回 `profit_reduce_mode = "guardian_placeholder"`
- Guardian 后续专门实现实际卖出算法

### 5.4 判定矩阵

| 状态 | 买入持仓股 | 买入非持仓股 | 卖出持仓股 |
|---|---|---|---|
| `ALLOW_OPEN` | 允许 | 允许 | 允许 |
| `HOLDING_ONLY` | 允许 | 拒绝 | 允许 |
| `FORCE_PROFIT_REDUCE` | 拒绝 | 拒绝 | 允许 |

### 5.5 边界值

- `800000` 落入 `HOLDING_ONLY`
- `100000` 落入 `FORCE_PROFIT_REDUCE`

## 6. 最终工作机制

### 6.1 简化原则

- 不采用“周期刷新 + 下单时即时补查”的双层逻辑
- 不在策略下单路径里直接查询 xtquant
- 唯一状态源是数据库中的 `pm_current_state`

### 6.2 worker 机制

- `position_management worker` 独立运行
- 每 `3 秒` 查询一次 `query_credit_detail(account)`
- 查询超时默认 `2 秒`
- 查询成功则更新：
  - `pm_credit_asset_snapshots`
  - `pm_current_state`
- 查询失败则：
  - 保留数据库现有 `pm_current_state`
  - 记录错误日志与失败时间

### 6.3 策略读取机制

策略订单判定时：

- 只读取 `pm_current_state`
- 不直接调用 xtquant

### 6.4 状态过旧与默认状态

为避免 worker 长时间失联后继续误用旧状态，需要对唯一状态源增加过旧保护：

- 若 `pm_current_state.evaluated_at` 距今未超过 `state_stale_after_seconds`
  - 直接按 `pm_current_state.state` 判定
- 若超过该阈值，或数据库里根本没有有效状态
  - 有效状态强制回退为默认状态 `HOLDING_ONLY`

说明：

- 这不是第二层缓存，也不是第二套状态
- 只是对唯一状态源增加“失联保护”
- 默认回退到第二层级，是本次明确确认的业务要求

## 7. 模块拆分与接入点

建议新增目录 `freshquant/position_management/`：

- `db.py`
  - 连接独立数据库 `freshquant_position_management`
- `repository.py`
  - 读写 4 张集合
- `credit_client.py`
  - 管理独立 xtquant 查询连接与独立 session
- `snapshot_service.py`
  - 查询信用资产并写入快照
- `policy.py`
  - 计算三态与判定矩阵
- `service.py`
  - 对外主入口：`refresh_state()`、`get_current_state()`、`evaluate_strategy_order()`
- `worker.py`
  - 周期运行，持续更新状态
- `models.py`
  - 状态枚举与决策对象
- `errors.py`
  - 模块错误定义

### 7.1 推荐接入点

主接入点放在：

- `freshquant/order_management/submit/service.py`

规则：

- `payload.source == "strategy"` 时，调用 `PositionManagementService.evaluate_strategy_order(payload)`
- 其他来源直接跳过

这样后续不论是 Guardian 还是新增策略，只要走统一策略提交链路，都能复用仓位管理模块。

### 7.2 Guardian 接入方式

- `freshquant/order_management/submit/guardian.py` 基本保持不动
- `freshquant/strategy/guardian.py` 本轮只需识别 `FORCE_PROFIT_REDUCE` 返回的占位标志
- 实际“强制卖出盈利标的”的 Guardian 算法单独开后续 RFC/设计

## 8. 异常处理

### 8.1 查询失败

- 不阻塞 broker
- 不中断仓位模块
- 继续保留数据库现有状态
- 记录失败日志与失败时间

### 8.2 Mongo 快照写失败

- 本次查询结果不进入状态更新
- 记录错误并告警
- 保留数据库现有状态继续服务策略

### 8.3 配置缺失

- 回退默认阈值：
  - `allow_open_min_bail = 800000`
  - `holding_only_min_bail = 100000`
  - `default_state = HOLDING_ONLY`
- 同时记录 `config_defaulted=true`

### 8.4 账号类型错误

- 若 `xtquant.account_type != CREDIT`
- 模块判定为配置错误
- worker 不启动状态更新
- 策略读取时只能使用默认状态 `HOLDING_ONLY`

## 9. 验收口径

- 使用独立数据库 `freshquant_position_management`
- 不向 `freshquant` 主库新增本模块集合
- 仓位状态口径来自 `query_credit_detail().m_dEnableBailBalance`
- 不使用 `xt_assets.cash` 作为状态判定依据
- 只有策略订单受仓位模块控制，人工单不受影响
- 三种状态的订单行为符合本设计中的判定矩阵
- worker 查询成功后，能够同时写入快照和当前状态
- worker 查询失败时，策略能够继续读取数据库中的最新状态
- 状态过旧或无状态时，默认有效状态回退为 `HOLDING_ONLY`
- 每次策略订单判定都能在 `pm_strategy_decisions` 中留痕
- `FORCE_PROFIT_REDUCE` 能向 Guardian 返回“强制减仓占位模式”标志

## 10. 后续实现前置条件

由于本模块属于新增独立模块，且会引入新分库与新行为语义，进入编码前必须先完成：

1. 新 RFC 起草与评审通过
2. `docs/migration/progress.md` 登记 RFC
3. 如涉及公共接口变化，同步登记 `docs/migration/breaking-changes.md`

