# Credit Account Support Migration Design

## Goal

在目标架构下补齐 `CREDIT` 账户的信用下单能力，同时保持 `order_management` 负责业务决策、`broker` 负责执行适配、`ingest` 负责正确记账的边界。

## Current State

- 目标仓已支持 `xtquant.account_type=CREDIT` 的账户连接。
- 目标仓已支持基于 `query_credit_detail().m_dEnableBailBalance` 的独立仓位管理门禁。
- 目标仓尚未迁入完整信用下单语义，当前买卖执行和 XT 回报归因仍基本按普通股票单处理。
- 旧仓已实现信用买卖的关键行为，但这些逻辑散落在 `broker/puppet` 中。

## Confirmed Scope

### In Scope

- 担保品买入 / 担保品卖出
- 融资买入
- 卖券还款
- 信用账户自动报价模式
- 融资标的列表的宿主机同步与落库
- XT 回报在订单域中的信用订单类型归因

### Out of Scope

- 融券卖出
- 买券还券
- 直接还券 / 直接还款
- 专项信用业务
- `position_management` 重构
- 前端页面与信用分析报表
- 恢复旧仓 `xt_credit_details` 作为独立事实源

## Architecture Decisions

### 1. Business Ownership

- `freshquant/order_management/` 负责信用订单语义决策。
- `morningglory/fqxtrade/fqxtrade/xtquant/broker.py` 和 `puppet.py` 只负责执行已决策结果。
- `freshquant/position_management/` 继续只做策略仓位门禁，不负责信用委托类型。

### 2. Source Coverage

信用账户语义对所有订单来源统一生效：

- `strategy`
- `api`
- `cli`
- `manual`

原因：这是账户执行语义，不是策略专属风控语义。

### 3. Buy Decision

信用账户买单不实时查询券商融资标的列表，而是读取本地落库的融资标的参考数据：

- 是融资标的：下 `CREDIT_FIN_BUY`
- 不是融资标的：下 `CREDIT_BUY`

### 4. Sell Decision

信用账户卖单在执行前实时查询 `query_credit_detail()`：

- 当 `m_dAvailable > 10000` 且 `m_dFinDebt > 0` 时：下 `CREDIT_SELL_SECU_REPAY`
- 否则：下 `CREDIT_SELL`
- 查询失败时：降级为 `CREDIT_SELL`

### 5. Auto Quote Mode

自动报价模式沿用旧仓的核心行为：

- 非连续竞价：使用 `FIX_PRICE`
- 连续竞价且未显式指定价格类型时：
  - 上海：`MARKET_SH_CONVERT_5_CANCEL`
  - 深圳：`MARKET_SZ_CONVERT_5_CANCEL`
- 保护价：
  - 买入：输入价 `* 1.008`
  - 卖出：输入价 `* 0.992`

## Data Decisions

### 1. Financing Subject Storage

新增订单域参考数据集合：

- `om_credit_subjects`

用途：

- 仅保存融资标的参考数据
- 下单时直接查库判断是否为融资标的

### 2. Freshness Policy

不再做“是否过旧”的门禁判断。

只要融资标的列表曾经成功同步过一次，就允许系统继续使用该列表。不可用条件仅包括：

- 从未成功同步过
- 集合为空

### 3. Order Ledger Fields

不引入独立 `execution_plan` 主账本，只在现有订单主账本补少量字段：

- `om_order_requests`
  - `account_type`
  - `credit_trade_mode`
  - `price_mode`
- `om_orders`
  - `credit_trade_mode_requested`
  - `credit_trade_mode_resolved`
  - `broker_order_type`
  - `broker_price_type`
  - `price_mode_requested`
  - `price_mode_resolved`
- `om_trade_facts`
  - `broker_order_type`
  - `credit_trade_mode_resolved`

设计目标：让信用订单决策结果可追溯，但不额外引入一套复杂计划表。

## Runtime Design

### 1. Submission

`freshquant/order_management/submit/service.py`：

- 继续作为统一订单受理入口
- 在现有参数归一化和策略门禁之后，调用信用订单决策组件
- 将决策结果写入订单主账本并入队

### 2. Execution

`freshquant/order_management/submit/execution_bridge.py`：

- 买单直接使用提交阶段已确定的信用买入类型
- 卖单执行前实时解析是否走卖券还款
- 输出最终 `order_type / price_type / protection_price`

`broker.py` / `puppet.py`：

- 不再自行查询融资标的列表
- 不再自行承担信用业务判断
- 只做 XT 下单适配

### 3. Ingest

`freshquant/order_management/ingest/xt_reports.py` 必须正确归因：

- `23`、`27` 视为买入
- `24`、`31` 视为卖出

原因：对订单域持仓账本来说，融资买入和担保品买入都属于开仓买入；卖券还款和担保品卖出都属于减仓卖出。

## Host Worker Design

新增宿主机程序：

- `python -m freshquant.order_management.credit_subjects.worker`

职责：

- 连接宿主机 MiniQMT / XT
- 调用 `query_credit_subjects(account)`
- 批量刷新 `om_credit_subjects`

运行约束：

- 必须运行在 Windows 宿主机
- 通过 supervisor 常驻
- 启动后先同步一次
- 每个交易日开盘前固定同步一次，建议时间 `09:20 Asia/Shanghai`

## Acceptance Summary

- 信用账户买入时能正确区分 `CREDIT_FIN_BUY` 与 `CREDIT_BUY`
- 信用账户卖出时能按 `m_dAvailable > 10000 and m_dFinDebt > 0` 走卖券还款
- 自动报价模式能输出正确的 `price_type` 和保护价
- XT 回报不会把融资买入误记成卖出
- `position_management` 语义保持不变
- 非信用账户行为保持不变

## Next Step

按本设计起草 RFC，并据此拆解实现计划。RFC 必须先落地，再进入编码。
