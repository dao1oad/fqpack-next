# RFC 0013: 融资账户仓位管理模块

- **状态**：Done
- **负责人**：Codex
- **评审人**：User
- **创建日期**：2026-03-07
- **关联进度**：`docs/migration/progress.md`

## 1. 背景与问题（Background）
目标仓库当前已经完成股票/ETF 订单管理主账本与统一提交流程，但仍缺少独立的“仓位管理”模块。现状里有两个关键缺口：

- 当前 `freshquant/order_management/submit/service.py` 会统一受理策略单与人工单，但对策略单没有独立的融资账户仓位风控状态机。
- `XtAsset.cash` 语义是“可用金额”，不是融资账户需要的“可用保证金”；若直接拿它做仓位分层，会把融资账户的真实风险口径做错。

旧仓库已经有“下单前仓位风控”的雏形，主要散落在以下路径：

- `D:\fqpack\freshquant\freshquant\strategy\toolkit\position_manager.py`
- `D:\fqpack\freshquant\freshquant\strategy\toolkit\position_risk_guard.py`
- `D:\fqpack\freshquant\freshquant\strategy\toolkit\order_manager.py`
- `D:\fqpack\freshquant\freshquant\rear\stock\trading_routes.py`

这套旧逻辑的核心是围绕 `params(code=xtquant)` 中的 `total_position`、`daily_threshold`、`is_force_stop` 计算买单容量；但它仍然基于“总仓位/市值”口径，不满足本次“按融资账户可用保证金分三态”的新需求。

本 RFC 约束新模块必须以 `query_credit_detail(account)` 返回的 `m_dEnableBailBalance` 作为唯一事实口径，并将仓位状态与策略订单准入解耦为独立模块。

## 2. 目标（Goals）
- 新增独立模块 `freshquant/position_management/`，后续可复用于多个策略。
- 新增独立 MongoDB 分库 `freshquant_position_management`，不将该模块集合写入 `freshquant` 主库。
- 通过独立 xtquant 查询连接周期读取 `query_credit_detail(account)`，提取并持久化 `m_dEnableBailBalance`。
- 产出三种可热更新的仓位状态：
  - `ALLOW_OPEN`
  - `HOLDING_ONLY`
  - `FORCE_PROFIT_REDUCE`
- 仅控制 `source=strategy` 的策略订单；人工/API/CLI 手工单保持旁路。
- 为 Guardian 在 `FORCE_PROFIT_REDUCE` 下的“盈利标的强制减仓”预留占位能力，但本轮不落地完整卖出算法。

## 3. 非目标（Non-Goals）
- 不重写 broker、MiniQMT 或 xtquant SDK。
- 不将人工单纳入该模块风控。
- 不在本 RFC 内实现 Guardian 强制卖出的最终数量算法。
- 不在本 RFC 内统一所有历史仓位/风控配置。
- 不引入新的数据库服务、中间件或消息系统。

## 4. 范围（Scope）
**In Scope**
- 独立信用资产查询 client、快照落库、当前状态计算与策略订单准入判断。
- Mongo 配置热更新。
- worker 周期刷新与“状态过旧保护”。
- 与 `OrderSubmitService` 的策略单接入。
- Guardian 的 `FORCE_PROFIT_REDUCE` 占位语义。

**Out of Scope**
- 人工/API/CLI 手工单风控。
- 期货、数字货币、债券回购等非股票/ETF 策略单。
- Guardian 盈利判定与卖出拆单细节。
- 前端仓位管理页面。

## 5. 模块边界（Responsibilities / Boundaries）
**负责（Must）**
- 使用独立 xtquant session 查询信用账户资产。
- 提取 `m_dEnableBailBalance` 并写入快照表。
- 根据 Mongo 配置计算当前仓位状态并写入唯一状态源 `pm_current_state`。
- 对策略订单给出“允许/拒绝/占位标记”的明确决策，并记录审计。
- 提供 worker 入口与稳定内部 Python API。

**不负责（Must Not）**
- 不直接调用 broker 下单。
- 不拦截人工/API/CLI 手工单。
- 不复用 broker 的 xtquant 连接。
- 不接管订单主账本、成交回报或持仓同步。

**依赖（Depends On）**
- `morningglory/fqxtrade/fqxtrade/xtquant/` 提供的 xtquant 接入能力。
- 现有 Mongo 基础设施与配置系统。
- `freshquant/data/astock/holding.py` 提供的当前持仓读模型。
- `freshquant/order_management/submit/service.py` 作为策略订单统一受理边界。

**禁止依赖（Must Not Depend On）**
- 不允许以 `xt_assets.cash` 代替可用保证金。
- 不允许将 `pm_*` 集合写回 `freshquant` 主库。
- 不允许策略下单时直接同步调用 broker 连接查询信用资产。

## 6. 对外接口（Public API）
本 RFC 的“对外接口”仅包括稳定内部 Python API 和 worker 入口，不新增 HTTP API。

### 6.1 内部 Python API
- `PositionSnapshotService.refresh_once() -> dict`
  - 单次查询信用资产、写快照、更新当前状态。
- `PositionManagementService.get_current_state() -> dict | None`
  - 读取 `pm_current_state`。
- `PositionManagementService.evaluate_strategy_order(payload) -> PositionDecision`
  - 对策略订单做准入判断并写审计。

### 6.2 Worker 入口
- `python -m freshquant.position_management.worker --once`
- `python -m freshquant.position_management.worker`

### 6.3 错误语义
- xtquant 查询失败：
  - worker 不崩溃；
  - 保留上一次成功状态；
  - 若当前状态缺失，则按默认兜底状态 `HOLDING_ONLY` 处理。
- 配置缺失：
  - 回退默认阈值；
  - 记录默认化事实。
- 非 `CREDIT` 账户：
  - 明确报配置错误，不进入放行逻辑。

## 7. 数据与配置（Data / Config）
### 7.1 独立分库
- 默认数据库：`freshquant_position_management`
- 配置键：`position_management.mongo_database`

### 7.2 集合
- `pm_configs`
- `pm_credit_asset_snapshots`
- `pm_current_state`
- `pm_strategy_decisions`

### 7.3 配置项
- `position_management.enabled = true`
- `position_management.thresholds.allow_open_min_bail = 800000`
- `position_management.thresholds.holding_only_min_bail = 100000`
- `position_management.refresh.interval_seconds = 3`
- `position_management.refresh.query_timeout_seconds = 2`
- `position_management.state_stale_after_seconds = 15`
- `position_management.default_state = HOLDING_ONLY`

### 7.4 三态语义
- `ALLOW_OPEN`
  - 条件：`available_bail_balance > 800000`
  - 允许开新仓、允许买入持仓股、允许卖出
- `HOLDING_ONLY`
  - 条件：`100000 < available_bail_balance <= 800000`
  - 禁止开新仓；允许对当前持仓股买卖
- `FORCE_PROFIT_REDUCE`
  - 条件：`available_bail_balance <= 100000`
  - 禁止一切买入；允许卖出；对 Guardian 卖点返回强制减仓占位标记

### 7.5 过旧保护与默认状态
- `pm_current_state` 是唯一状态源。
- 若 `evaluated_at` 超过 `state_stale_after_seconds`，状态视为过旧：
  - 策略买入拒绝
  - 策略卖出允许
- 若当前状态缺失，则默认状态为 `HOLDING_ONLY`。

## 8. 破坏性变更（Breaking Changes）
本 RFC 落地时属于行为语义扩展，需在实现完成时同步登记 `docs/migration/breaking-changes.md`：

- 新增独立分库 `freshquant_position_management`。
- `source=strategy` 的订单提交路径将新增仓位状态门禁。
- 人工/API/CLI 手工单保持不受控，与策略单行为将出现分流。

### 迁移步骤
1. 部署包含 `freshquant/position_management/` 的新代码。
2. 配置融资账户与 Mongo 分库参数。
3. 启动仓位管理 worker。
4. 确认 `pm_current_state` 正常产出后，再启用策略准入判断。

### 回滚方案
- 停用 worker 并回退 `OrderSubmitService` 的策略门禁接入。
- 保留 `freshquant_position_management` 分库数据，不删除历史快照，便于排障。

## 9. 迁移映射（From `D:\fqpack\freshquant`）
- `freshquant\strategy\toolkit\position_manager.py`
  - 旧的总仓位/阈值容量配置与占用率计算
  - 迁移为新模块的配置读取与状态计算能力
- `freshquant\strategy\toolkit\position_risk_guard.py`
  - 旧的买单准入判断
  - 迁移为 `PositionManagementService.evaluate_strategy_order()`
- `freshquant\strategy\toolkit\order_manager.py`
  - 旧的买单入队前风控接入点
  - 对应新仓库 `OrderSubmitService` 的策略单门禁接入点
- `freshquant\rear\stock\trading_routes.py`
  - 旧的手工下单路由风控
  - 本轮明确不迁移，继续保持人工旁路

## 10. 测试与验收（Acceptance Criteria）
- [ ] `pm_*` 集合全部落在独立数据库 `freshquant_position_management`（或其配置值）中。
- [ ] 信用资产口径来自 `query_credit_detail(account).m_dEnableBailBalance`，而非 `xt_assets.cash`。
- [ ] worker 查询成功后会写入 `pm_credit_asset_snapshots` 并更新 `pm_current_state`。
- [ ] worker 查询失败时会保留最近一次成功状态；若无状态则默认 `HOLDING_ONLY`。
- [ ] `ALLOW_OPEN / HOLDING_ONLY / FORCE_PROFIT_REDUCE` 三态边界符合：
  - [ ] `800000` 落入 `HOLDING_ONLY`
  - [ ] `100000` 落入 `FORCE_PROFIT_REDUCE`
- [ ] 仅 `source=strategy` 订单受控；人工/API/CLI 单不受影响。
- [ ] `HOLDING_ONLY` 仅允许持仓股买入，禁止新标的买入。
- [ ] `FORCE_PROFIT_REDUCE` 禁止一切买入，允许卖出，并能给 Guardian 产出占位标记。
- [ ] 每次策略决策都会写入 `pm_strategy_decisions`。

## 11. 风险与回滚（Risks / Rollback）
- 风险点：worker 停止刷新导致状态长期陈旧。
  - 缓解：对 `pm_current_state` 增加过旧保护。
- 风险点：xtquant 查询失败导致状态短时不可更新。
  - 缓解：回退最近一次成功状态；无状态时默认 `HOLDING_ONLY`。
- 风险点：策略持仓判定与实际持仓短时不一致。
  - 缓解：复用订单域持仓读模型，保持与现有策略读路径一致。
- 风险点：Guardian 后续强制减仓语义扩展时接口不稳定。
  - 缓解：本轮只输出明确占位标记，不提前承诺最终卖出算法。

## 12. 里程碑与拆分（Milestones）
- M1：RFC 0013 Approved
- M2：独立分库、仓库层与状态模型落地
- M3：信用资产查询、快照落库与 worker 落地
- M4：状态策略、过旧保护与策略订单决策落地
- M5：接入 `OrderSubmitService`，只控制策略订单
- M6：补齐 Guardian 占位语义、测试与迁移文档
