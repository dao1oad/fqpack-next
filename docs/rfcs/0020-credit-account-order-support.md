# RFC 0020: 信用账户订单支持

- **状态**：Done
- **负责人**：Codex
- **评审人**：User
- **创建日期**：2026-03-08
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）

目标仓库当前已经具备以下基础：

- `xtquant.account_type=CREDIT` 的信用账户连接能力
- 独立的 `freshquant/position_management/` 仓位管理模块
- 独立的 `freshquant/order_management/` 订单管理模块

但信用账户的完整交易语义尚未迁入目标架构。当前问题主要集中在三个方面：

- 信用账户买卖委托类型仍主要在 `broker/puppet` 中按普通股票单处理，未稳定接入订单域
- 融资标的判断、卖券还款判断、自动报价语义没有在新架构中形成清晰边界
- XT 回报 ingest 对信用订单类型的归因不完整，可能把融资买入错误记为卖出，进一步破坏 `buy_lot / lot_slices / Guardian / TPSL / holding projection`

旧仓库 `D:\fqpack\freshquant` 已有可工作的信用账户支持，但这些逻辑分散在以下路径：

- `freshquant\strategy\toolkit\margin_trading.py`
- `freshquant\strategy\toolkit\sync_xtquant.py`
- `morningglory\fqxtrade\fqxtrade\xtquant\puppet.py`
- `morningglory\fqxtrade\fqxtrade\xtquant\broker.py`

本 RFC 的目标不是原样复制旧仓实现，而是在目标架构下把这些信用语义收拢到订单域。

## 2. 目标（Goals）

- 在 `freshquant/order_management/` 内补齐信用账户下单语义
- 对 `CREDIT` 账户统一支持：
  - 担保品买入
  - 担保品卖出
  - 融资买入
  - 卖券还款
- 将“融资标的判断”纳入订单域提交阶段
- 将“卖券还款判断”纳入订单域执行前阶段
- 为信用账户恢复自动报价模式
- 修正 XT 回报归因，确保信用订单类型能正确映射为买卖方向
- 保持 `position_management` 继续只负责策略门禁，不负责信用委托类型
- 让信用账户语义对 `strategy / api / cli / manual` 全部来源统一生效

## 3. 非目标（Non-Goals）

- 不支持融券卖出
- 不支持买券还券
- 不支持直接还券 / 直接还款
- 不支持专项信用业务
- 不重构 `freshquant/position_management/`
- 不新增信用分析报表或前端页面
- 不恢复旧仓 `xt_credit_details` 作为独立事实源
- 不把 XT 原始常量直接暴露为对外公共 API 契约
- 不在信用账户下支持国债逆回购链路

## 4. 范围（Scope）

**In Scope**

- `freshquant/order_management/` 内新增信用订单决策组件
- 新增融资标的列表宿主机同步 worker
- 提交阶段的信用买单决策
- 执行前阶段的卖券还款决策
- 信用账户自动报价模式
- XT 回报 ingest 对信用订单类型的方向归因
- 订单主账本补充信用决策结果字段
- 宿主机 supervisor/部署文档同步更新

**Out of Scope**

- `freshquant/position_management/` 状态机与策略门禁规则调整
- Guardian / TPSL / `buy_lot` / `lot_slices` / `sell_allocations` 主账本模型重构
- 信用业务前端页面
- 融券相关任何能力
- 将宿主机 MiniQMT / XT 迁入 Docker 容器

## 5. 模块边界（Responsibilities / Boundaries）

**负责（Must）**

- `freshquant/order_management/submit/service.py`
  - 作为统一订单受理边界
  - 在提交阶段解析信用买单类型
- `freshquant/order_management/submit/execution_bridge.py`
  - 在执行前解析信用卖单类型与自动报价
- `freshquant/order_management/ingest/xt_reports.py`
  - 把信用订单类型正确归并为买卖方向
- `freshquant/order_management/credit_subjects/`
  - 保存融资标的参考数据
  - 提供宿主机同步入口
- `morningglory/fqxtrade/fqxtrade/xtquant/broker.py`
  - 消费订单域已决策结果并执行 XT 下单
- `morningglory/fqxtrade/fqxtrade/xtquant/puppet.py`
  - 作为 XT 执行适配层，执行已决策好的 `order_type / price_type / price`

**不负责（Must Not）**

- 不在 `position_management` 中处理信用委托类型
- 不在 `broker/puppet` 中继续保留融资标的业务判断
- 不在订单域外新增第二套信用事实源
- 不要求上游调用方传 XT 原始 `order_type / price_type`

**依赖（Depends On）**

- `xtquant` / MiniQMT 宿主机运行环境
- `freshquant/order_management/` 现有主账本与 submit/tracking/ingest 链路
- `freshquant/position_management/` 现有策略门禁能力
- 旧仓已有信用交易语义作为迁移参考：
  - `margin_trading.py`
  - `sync_xtquant.py`
  - `puppet.py`
  - `broker.py`

**禁止依赖（Must Not Depend On）**

- 不依赖实时 `query_credit_subjects()` 作为下单链路
- 不依赖旧仓 `xt_credit_details`
- 不依赖前端页面状态来决定信用委托类型

## 6. 对外接口（Public API）

### 6.1 统一下单接口

现有统一下单入口继续保持不变：

- `OrderSubmitService.submit_order(payload)`
- `/api/order/submit`
- `/api/stock_order`（兼容入口）
- `fqctl om-order`
- `xtquant buy/sell`

新增可选语义字段：

- `credit_trade_mode`
  - `auto`
  - `collateral_buy`
  - `finance_buy`
  - `collateral_sell`
  - `sell_repay`
- `price_mode`
  - `auto`
  - `limit`
  - `market_5_cancel`

说明：

- 调用方不需要传 XT 原始 `order_type / price_type`
- 绝大多数场景默认使用 `auto`

### 6.2 宿主机 worker 入口

- `python -m freshquant.order_management.credit_subjects.worker --once`
- `python -m freshquant.order_management.credit_subjects.worker`

该 worker 必须运行在 Windows 宿主机。

### 6.3 运行时规则

- 信用账户买单：
  - 下单时只查库里的融资标的列表
  - 是融资标的则用 `CREDIT_FIN_BUY`
  - 否则用 `CREDIT_BUY`
- 信用账户卖单：
  - 执行前实时 `query_credit_detail()`
  - 当 `m_dAvailable > 10000` 且 `m_dFinDebt > 0` 时，用 `CREDIT_SELL_SECU_REPAY`
  - 否则用 `CREDIT_SELL`
  - 查询失败时降级为 `CREDIT_SELL`
- 自动报价模式：
  - 非连续竞价：`FIX_PRICE`
  - 连续竞价且未显式指定价格模式：
    - 上海：`MARKET_SH_CONVERT_5_CANCEL`
    - 深圳：`MARKET_SZ_CONVERT_5_CANCEL`
  - 买入保护价：输入价 `* 1.008`
  - 卖出保护价：输入价 `* 0.992`

## 7. 数据与配置（Data / Config）

### 7.1 数据存储

新增订单域参考数据集合：

- `om_credit_subjects`

该集合位于 `freshquant_order_management` 分库，用于保存融资标的参考数据。

### 7.2 订单主账本补充字段

`om_order_requests`

- `account_type`
- `credit_trade_mode`
- `price_mode`

`om_orders`

- `credit_trade_mode_requested`
- `credit_trade_mode_resolved`
- `broker_order_type`
- `broker_price_type`
- `price_mode_requested`
- `price_mode_resolved`

`om_trade_facts`

- `broker_order_type`
- `credit_trade_mode_resolved`

### 7.3 融资标的同步

- 融资标的列表通过宿主机 worker 同步
- worker 启动后先同步一次
- 每个交易日开盘前固定同步一次，建议时间 `09:20 Asia/Shanghai`
- 下单时只查库
- 不做 freshness/stale 门禁判断
- 只要融资标的列表历史上成功同步过一次，就允许继续使用
- 不可用条件仅包括：
  - 从未成功同步过
  - 集合为空

## 8. 破坏性变更（Breaking Changes）

本 RFC 预期会带来以下行为语义变化：

- `CREDIT` 账户的订单语义从“broker/puppet 临时判断”收敛为“order_management 统一决策”
- 信用账户自动报价重新生效，连续竞价时默认报价行为将不同于当前目标仓
- XT 回报中 `27/31` 等信用类型将被重新映射为正确方向，可能改变当前错误的持仓投影结果
- 宿主机将新增一个需要 supervisor 托管的 `credit_subjects.worker`

### 迁移步骤

1. 审核并通过本 RFC
2. 新增 `om_credit_subjects` 集合与索引
3. 部署宿主机 `credit_subjects.worker`
4. 在订单域接入信用决策与 XT 回报修正
5. 更新部署文档与 supervisor 模板

### 回滚方案

1. 停止宿主机 `credit_subjects.worker`
2. 回退订单域信用决策代码
3. 回退 XT ingest 的信用类型映射
4. 恢复现有 `broker/puppet` 的普通股票语义

## 9. 迁移映射（From `D:\fqpack\freshquant`）

- `freshquant\strategy\toolkit\margin_trading.py`
  - 融资标的查询逻辑
  - → `freshquant/order_management/credit_subjects/` + submit 阶段信用买单决策
- `freshquant\strategy\toolkit\sync_xtquant.py`
  - `query_credit_subjects()` 同步逻辑
  - → `freshquant/order_management/credit_subjects/worker.py`
- `morningglory\fqxtrade\fqxtrade\xtquant\puppet.py`
  - 旧的信用买入 / 卖券还款 / 自动报价逻辑
  - → submit 阶段决策 + execution bridge 运行时解析 + XT 适配层简化
- `morningglory\fqxtrade\fqxtrade\xtquant\broker.py`
  - 旧的执行前交易判断
  - → `execution_bridge.py` 中的订单域运行时决策

## 10. 测试与验收（Acceptance Criteria）

- [ ] 信用账户买入融资标的时，下单类型为 `CREDIT_FIN_BUY`
- [ ] 信用账户买入非融资标的时，下单类型为 `CREDIT_BUY`
- [ ] 信用账户卖出在 `m_dAvailable > 10000 and m_dFinDebt > 0` 时，下单类型为 `CREDIT_SELL_SECU_REPAY`
- [ ] 信用账户卖出在其他场景下，下单类型为 `CREDIT_SELL`
- [ ] 信用账户自动报价模式在连续竞价时能产出正确 `price_type` 和保护价
- [ ] `xt_reports.py` 能把 `23/27` 归为买，把 `24/31` 归为卖
- [ ] `buy_lot / lot_slices / Guardian / TPSL / holding projection` 不会因信用订单类型而记错方向
- [ ] 非 `CREDIT` 账户行为保持不变
- [ ] 宿主机 `credit_subjects.worker` 能成功同步融资标的到 `om_credit_subjects`
- [ ] 当融资标的列表从未成功同步或集合为空时，信用买单会拒绝提交

## 11. 风险与回滚（Risks / Rollback）

- 风险点：融资标的列表长期未更新，但系统仍允许继续使用历史快照
  - 缓解：保留 `updated_at` 便于排障与人工观测，但不作为门禁
- 风险点：卖券还款判断依赖实时 `query_credit_detail()`，执行时可能受宿主机连接波动影响
  - 缓解：查询失败时降级为 `CREDIT_SELL`
- 风险点：自动报价模式恢复后，信用账户的默认成交行为可能与当前目标仓不同
  - 缓解：仅在 `price_mode=auto` 且未显式指定时启用
- 风险点：XT 回报重新映射后，可能暴露当前目标仓已有的错误投影
  - 缓解：补齐 focused tests，先在订单域验证再推广

## 12. 里程碑与拆分（Milestones）

- M1：RFC 0020 Draft / Review
- M2：`om_credit_subjects` 与宿主机 worker 落地
- M3：提交阶段信用买单决策落地
- M4：执行前卖券还款与自动报价落地
- M5：XT ingest 与兼容投影修正
- M6：宿主机部署文档、supervisor 样板与 focused verification 完成
